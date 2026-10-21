# core/modbus_client.py
"""The app's own Modbus client: RTU on a serial port, and Modbus TCP.

Why not a library
-----------------
The app speaks the rest of Modbus itself: the slave emulator
(core/slave_core), the sniffer's framing and the CRC (core/sniffer_core). Of
pymodbus it used a thin slice — open the link, read FC 01–04, write FC 05/06
— and kept fighting its internals: the line statistics wrapped its RTU framer
to tell CRC errors from silence (pymodbus 3.16 silently broke that), the raw
console wrote to its private serial handle, the device-address keyword was
renamed twice. The protocol itself has not changed since 2006. This module
does exactly what the app needs and reports exactly what happened.

What core/modbus_core uses
    connect() -> bool, close(), .socket (for RTU the pyserial port: the raw
    console writes to it), read_holding_registers / read_input_registers /
    read_coils / read_discrete_inputs (address, count, device_id),
    write_register / write_coil / write_registers (address, value(s),
    device_id) → Response.

Response
    .registers / .bits, .function_code (fc | 0x80 for an exception),
    .exception_code, isError() and .outcome: "ok", "exception", "timeout"
    (nothing came back) or "crc" (something came back that is not a valid
    answer — bad CRC, cut short, garbled). core/linestats counts .outcome as
    it is.

RTU on the wire
    A request goes out after the line has been quiet for t3.5 (3.5 character
    times; 1.75 ms above 19200 Bd, as the standard says). The answer's length
    is known from its first bytes — an exception 5, a read 5 + byte count, a
    write 8 — so reading stops the moment it is complete instead of waiting
    out the timeout. Noise before the answer is skipped. An adapter that
    echoes what it sends (2-wire RS-485 without echo suppression) is handled:
    the echo of the request is dropped; for FC 05/06, whose answer IS a copy
    of the request, the master learns from the reads whether the adapter
    echoes.

TCP on the wire
    The same PDU behind a 7-byte MBAP header (transaction id, protocol 0,
    length, unit id) and no CRC. A late answer to an earlier, timed-out
    request carries the old transaction id and is skipped.
"""
import socket as _socket
import time
from dataclasses import dataclass, field

from core.sniffer_core import crc16

READ_FCS = (0x01, 0x02, 0x03, 0x04)
BIT_FCS = (0x01, 0x02)
POLL_S = 0.001                 # how often the port is looked at while waiting
MIN_GAP_S = 0.05               # silence that ends a started RTU answer (USB latency)


class ModbusLinkError(ConnectionError):
    """The link itself failed (unplugged adapter, closed port, dropped TCP
    connection) — not an unanswered request. core/modbus_core counts it like
    a timeout, and its reconnect logic takes over."""


@dataclass
class Response:
    function_code: int = 0
    registers: list = field(default_factory=list)
    bits: list = field(default_factory=list)
    exception_code: int = 0
    outcome: str = "ok"            # ok | exception | timeout | crc
    device_id: int = 0
    raw: bytes = b""               # the answer as it came off the link
    pdu: bytes = b""               # function code + data, without address / CRC / MBAP

    def isError(self) -> bool:     # the name core/modbus_core has always called
        return self.outcome != "ok"


def with_crc(body: bytes) -> bytes:
    crc = crc16(body)
    return bytes(body) + bytes((crc & 0xFF, crc >> 8))


def t35(baudrate: int) -> float:
    """3.5 character times (11 bits each); fixed 1.75 ms above 19200 Bd."""
    return 0.00175 if baudrate > 19200 else 3.5 * 11 / max(1, baudrate)


def answer_length(buf: bytes, fc: int):
    """Total length of the RTU answer that starts *buf*, once enough of it
    has arrived to know; None while that is still unknown; -1 when *buf*
    cannot start an answer to *fc* at all."""
    if len(buf) < 2:
        return None
    if buf[1] == (fc | 0x80):
        return 5                               # id, fc|80, code, crc×2
    if buf[1] != fc:
        return -1
    if fc in READ_FCS:
        return None if len(buf) < 3 else 5 + buf[2]
    return 8                                   # FC 05/06/15/16: id fc addr val/count crc


def _u16(v: int) -> bytes:
    return (int(v) & 0xFFFF).to_bytes(2, "big")


class _Client:
    """The requests the app makes — the same over both links. A link only
    has to implement _exchange(device_id, pdu) → Response (with .pdu)."""

    retries = 1

    def read_coils(self, address: int, count: int = 1, device_id: int = 1) -> Response:
        return self._read(0x01, address, count, device_id)

    def read_discrete_inputs(self, address: int, count: int = 1, device_id: int = 1) -> Response:
        return self._read(0x02, address, count, device_id)

    def read_holding_registers(self, address: int, count: int = 1, device_id: int = 1) -> Response:
        return self._read(0x03, address, count, device_id)

    def read_input_registers(self, address: int, count: int = 1, device_id: int = 1) -> Response:
        return self._read(0x04, address, count, device_id)

    def write_coil(self, address: int, value, device_id: int = 1) -> Response:
        pdu = bytes((0x05,)) + _u16(address) + (b"\xff\x00" if value else b"\x00\x00")
        return self._transact(device_id, pdu)

    def write_register(self, address: int, value: int, device_id: int = 1) -> Response:
        return self._transact(device_id, bytes((0x06,)) + _u16(address) + _u16(value))

    def write_registers(self, address: int, values, device_id: int = 1) -> Response:
        values = [int(v) & 0xFFFF for v in values]
        pdu = (bytes((0x10,)) + _u16(address) + _u16(len(values))
               + bytes((2 * len(values),)) + b"".join(_u16(v) for v in values))
        return self._transact(device_id, pdu)

    def _read(self, fc: int, address: int, count: int, device_id: int) -> Response:
        res = self._transact(device_id, bytes((fc,)) + _u16(address) + _u16(count))
        if res.outcome != "ok":
            return res
        pdu = res.pdu
        if len(pdu) < 2 or pdu[1] != len(pdu) - 2:
            res.outcome = "crc"                    # a byte count that does not fit
            return res
        data = pdu[2:]
        if fc in BIT_FCS:
            if len(data) < (count + 7) // 8:
                res.outcome = "crc"
                return res
            res.bits = [(data[i // 8] >> (i % 8)) & 1 for i in range(count)]
        else:
            if len(data) != 2 * count:
                res.outcome = "crc"
                return res
            res.registers = [int.from_bytes(data[i:i + 2], "big")
                             for i in range(0, len(data), 2)]
        return res

    def _transact(self, device_id: int, pdu: bytes) -> Response:
        res = Response(outcome="timeout")
        for _attempt in range(1 + max(0, int(self.retries))):
            res = self._exchange(int(device_id) & 0xFF, pdu)
            if res.outcome in ("ok", "exception"):
                break
        return res

    def _exchange(self, device_id: int, pdu: bytes) -> Response:   # pragma: no cover
        raise NotImplementedError


# ═══════════════════════════════════════════════════════════════════════
#  RTU — a serial port
# ═══════════════════════════════════════════════════════════════════════
class RtuMaster(_Client):
    """A Modbus RTU master on one serial port. Not thread-safe: one owner
    (the ModbusCore thread)."""

    def __init__(self, port: str, baudrate: int = 9600, parity: str = "N",
                 stopbits: float = 1, bytesize: int = 8, timeout: float = 1.0,
                 retries: int = 1, serial_factory=None):
        self.port = port
        self.baudrate = int(baudrate)
        self.parity = parity
        self.stopbits = stopbits
        self.bytesize = bytesize
        self.timeout = float(timeout)
        self.retries = max(0, int(retries))
        self._factory = serial_factory
        self.socket = None
        self.echo = None               # does the adapter echo? None = not known yet
        self._t35 = t35(self.baudrate)
        self._quiet_since = 0.0        # when the line last went quiet
        self.last_request = b""
        self.last_answer = b""

    def connect(self) -> bool:
        if self.connected:
            return True
        factory = self._factory
        if factory is None:
            import serial
            factory = serial.Serial
        try:
            self.socket = factory(port=self.port, baudrate=self.baudrate,
                                  bytesize=self.bytesize, parity=self.parity,
                                  stopbits=self.stopbits, timeout=0,
                                  write_timeout=max(1.0, self.timeout))
        except Exception:              # SerialException, OSError, ValueError…
            self.socket = None
            return False
        self._quiet_since = time.monotonic()
        return True

    def close(self):
        sock, self.socket = self.socket, None
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass

    @property
    def connected(self) -> bool:
        return self.socket is not None and getattr(self.socket, "is_open", True)

    def _exchange(self, device_id: int, pdu: bytes) -> Response:
        ser = self.socket
        if ser is None:
            raise ModbusLinkError(f"{self.port} is not open")
        request = with_crc(bytes((device_id,)) + pdu)
        fc = pdu[0]
        wait = self._quiet_since + self._t35 - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            ser.reset_input_buffer()               # a late answer to an earlier request
            ser.write(request)
            ser.flush()
        except Exception as e:
            raise ModbusLinkError(str(e)) from e
        self.last_request, self.last_answer = request, b""
        if device_id == 0:                         # broadcast: nobody answers
            self._quiet_since = time.monotonic()
            return Response(function_code=fc, outcome="ok")
        try:
            buf = self._receive(ser, request, fc, device_id)
        finally:
            self._quiet_since = time.monotonic()
        return self._parse(buf, fc, device_id)

    def _receive(self, ser, request: bytes, fc: int, device_id: int) -> bytearray:
        """Bytes of the answer (echo and leading noise removed), as soon as
        the answer is complete — or whatever came before the deadline or
        before a silence that ended it."""
        tx_time = len(request) * 11 / max(1, self.baudrate)
        deadline = time.monotonic() + tx_time + self.timeout
        gap = max(MIN_GAP_S, 4 * self._t35)
        buf = bytearray()
        echo_done = False              # decided whether the start is an echo
        last_rx = None
        while True:
            try:
                n = ser.in_waiting
                if n:
                    buf += ser.read(n)
                    last_rx = time.monotonic()
            except Exception as e:
                raise ModbusLinkError(str(e)) from e
            if not echo_done:
                # While what came is still the start of the request, it may be
                # the adapter's echo: nothing can be judged before it is whole.
                if len(buf) >= len(request):
                    echo_done = self._drop_echo(buf, request, fc, ser, gap)
                elif buf and not request.startswith(bytes(buf)):
                    echo_done = True
                    if fc in READ_FCS:
                        self.echo = False
            if echo_done:
                _skip_noise(buf, device_id, fc)
                need = answer_length(buf, fc)
                if need is not None and need > 0 and len(buf) >= need:
                    return buf[:need]
            now = time.monotonic()
            if now >= deadline:
                return buf
            if echo_done and buf and last_rx is not None and now - last_rx > gap:
                return buf                         # the line went quiet mid-answer
            time.sleep(POLL_S)

    def _drop_echo(self, buf: bytearray, request: bytes, fc: int, ser, gap: float) -> bool:
        """*buf* holds at least as many bytes as the request. If it starts
        with the request, decide whether that is the adapter's echo (and drop
        it). Always returns True: the question is settled."""
        if bytes(buf[:len(request)]) != request:
            if fc in READ_FCS:
                self.echo = False
            return True
        if fc not in (0x05, 0x06):
            # A read's (or a multi-write's) answer never equals its request.
            del buf[:len(request)]
            self.echo = True
            return True
        # FC 05/06: the answer IS a copy of the request.
        if self.echo is True:
            del buf[:len(request)]
            return True
        if self.echo is False:
            return True                            # it is the answer
        if len(buf) > len(request):                # a second copy / an exception follows
            del buf[:len(request)]
            self.echo = True
            return True
        end = time.monotonic() + gap               # not known yet: a second copy?
        while time.monotonic() < end:
            if ser.in_waiting:
                buf += ser.read(ser.in_waiting)
                del buf[:len(request)]
                self.echo = True
                return True
            time.sleep(POLL_S)
        self.echo = False                          # it was the answer: no echo
        return True

    def _parse(self, buf: bytearray, fc: int, device_id: int) -> Response:
        raw = bytes(buf)
        self.last_answer = raw
        if not raw:
            return Response(function_code=0, outcome="timeout", device_id=device_id)
        need = answer_length(raw, fc)
        if (need is None or need <= 0 or len(raw) < need or raw[0] != device_id
                or crc16(raw[:-2]) != (raw[-2] | raw[-1] << 8)):
            return Response(function_code=0, outcome="crc", device_id=device_id, raw=raw)
        if raw[1] == (fc | 0x80):
            return Response(function_code=raw[1], exception_code=raw[2],
                            outcome="exception", device_id=device_id, raw=raw,
                            pdu=raw[1:-2])
        return Response(function_code=fc, outcome="ok", device_id=device_id,
                        raw=raw, pdu=raw[1:-2])


def _skip_noise(buf: bytearray, device_id: int, fc: int):
    """Drop bytes before the answer's start (id, fc or fc|0x80): a driver
    switching on the bus can put a stray 0x00 / 0xFF on the line."""
    for i in range(len(buf) - 1):
        if buf[i] == device_id and buf[i + 1] in (fc, fc | 0x80):
            if i:
                del buf[:i]
            return
    if len(buf) > 1 and buf[-1] == device_id:
        del buf[:-1]                               # the start may just be arriving


# ═══════════════════════════════════════════════════════════════════════
#  TCP — a socket
# ═══════════════════════════════════════════════════════════════════════
class TcpMaster(_Client):
    """A Modbus TCP client. Not thread-safe: one owner (the ModbusCore thread)."""

    def __init__(self, host: str, port: int = 502, timeout: float = 1.0,
                 retries: int = 1, socket_factory=None):
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self.retries = max(0, int(retries))
        self._factory = socket_factory
        self.socket = None
        self._tid = 0
        self.last_request = b""
        self.last_answer = b""

    def connect(self) -> bool:
        if self.socket is not None:
            return True
        factory = self._factory or _socket.create_connection
        try:
            self.socket = factory((self.host, self.port), timeout=max(0.1, self.timeout))
        except OSError:
            self.socket = None
            return False
        return True

    def close(self):
        sock, self.socket = self.socket, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    @property
    def connected(self) -> bool:
        return self.socket is not None

    def _exchange(self, device_id: int, pdu: bytes) -> Response:
        sock = self.socket
        if sock is None:
            raise ModbusLinkError(f"{self.host}:{self.port} is not connected")
        self._tid = (self._tid + 1) & 0xFFFF
        request = _u16(self._tid) + b"\x00\x00" + _u16(len(pdu) + 1) + bytes((device_id,)) + pdu
        try:
            sock.sendall(request)
        except OSError as e:
            raise ModbusLinkError(str(e)) from e
        self.last_request, self.last_answer = request, b""
        fc = pdu[0]
        deadline = time.monotonic() + self.timeout
        while True:
            head = self._recv(sock, 7, deadline)
            if not head:
                return Response(outcome="timeout", device_id=device_id)
            if len(head) < 7:
                return Response(outcome="crc", device_id=device_id, raw=head)
            tid = int.from_bytes(head[0:2], "big")
            proto = int.from_bytes(head[2:4], "big")
            length = int.from_bytes(head[4:6], "big")
            if proto != 0 or not 2 <= length <= 254:
                return Response(outcome="crc", device_id=device_id, raw=head)
            body = self._recv(sock, length - 1, deadline)
            raw = head + body
            if len(body) < length - 1:
                return Response(outcome="crc", device_id=device_id, raw=raw)
            if tid != self._tid:
                continue                           # a late answer to an earlier request
            self.last_answer = raw
            if head[6] != device_id:
                return Response(outcome="crc", device_id=device_id, raw=raw)
            if body[0] == (fc | 0x80) and len(body) >= 2:
                return Response(function_code=body[0], exception_code=body[1],
                                outcome="exception", device_id=device_id, raw=raw, pdu=body)
            if body[0] != fc:
                return Response(outcome="crc", device_id=device_id, raw=raw)
            return Response(function_code=fc, outcome="ok", device_id=device_id,
                            raw=raw, pdu=body)

    @staticmethod
    def _recv(sock, n: int, deadline: float) -> bytes:
        """Up to *n* bytes before *deadline* (fewer when it passes)."""
        buf = b""
        while len(buf) < n:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            try:
                sock.settimeout(left)
                chunk = sock.recv(n - len(buf))
            except _socket.timeout:
                break
            except OSError as e:
                raise ModbusLinkError(str(e)) from e
            if not chunk:
                raise ModbusLinkError("the connection was closed by the device")
            buf += chunk
        return buf
