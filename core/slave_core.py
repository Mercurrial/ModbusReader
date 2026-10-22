# core/slave_core.py
"""Slave (device-simulation) mode: the app answers a Modbus RTU master.

Load a register map, type values, and any master on the line — a PLC, a
SCADA, another copy of this program on a second adapter — reads them as if a
real device were connected; its writes land in the table.

Built as a hand-rolled RTU responder rather than on a library's server:

* ``build_response(request, store, slave_id)`` is a PURE function — bytes in,
  bytes out — so every protocol rule is unit-tested without a port;
* the values are encoded with the SAME codecs the master side reads with
  (``datatypes``), so a map read by the master and served by the slave are
  guaranteed to agree;
* the thread (``SlaveServer``) is only an I/O pump: frame the stream by
  t3.5 silence, ask build_response, write the answer.

Function codes: 03 (holding), 04 (input registers; a map without any input
registers serves FC04 from the holding table, like many real devices), 06 /
16 (write holding), 01 / 02 (read coils / discrete inputs), 05 / 15 (write
coils). Every Modbus table is its own address space — the store is keyed by
``datatypes.reg_key`` (area << 16 | address). Anything else gets exception
01; an address outside the served map exception 02; a bad count or length
exception 03. A frame with a bad CRC, or for another slave ID, gets no
answer at all (that is what a real device does). Broadcast (ID 0) writes are
applied and never answered.

One port, one owner: the master poller and the slave server cannot share a
COM port — testing one against the other needs two adapters and a null-modem
link (or a virtual COM pair).

Modbus TCP: ``SlaveTcpServer`` listens on a TCP port (502 by default) and
serves any number of masters at once. A request arrives as MBAP + PDU;
``tcp_response`` hands the PDU to the same ``build_response`` and wraps the
answer back. Over TCP the device is addressed by its IP, so unit ids 0 and
255 reach it as well as its own id (the Modbus TCP implementation guide
asks a server to accept them). Here the app's own master CAN talk to its
own emulator — connect to 127.0.0.1 — which needs no hardware at all.
"""

import os
import selectors
import socket
import struct
import threading
import time

from PyQt6.QtCore import QThread, pyqtSignal

from core import datatypes
from core.sniffer_core import crc16, carve_frames, frame_crc_ok

ILLEGAL_FUNCTION, ILLEGAL_ADDRESS, ILLEGAL_VALUE = 0x01, 0x02, 0x03
MAX_READ = 125           # FC03/04: registers per request (Modbus spec)
MAX_WRITE = 123          # FC16
MAX_BITS_READ = 2000     # FC01/02
MAX_BITS_WRITE = 1968    # FC15

_AREA = datatypes.AREAS


def _key(area: str, addr: int) -> int:
    return (_AREA[area].code << 16) | (addr & 0xFFFF)


def _pack_bits(bits) -> bytes:
    """Coil states → bytes, LSB of the first byte = the first coil."""
    out = bytearray((len(bits) + 7) // 8)
    for i, b in enumerate(bits):
        if b:
            out[i // 8] |= 1 << (i % 8)
    return bytes(out)


def with_crc(body: bytes) -> bytes:
    c = crc16(body)
    return body + bytes((c & 0xFF, c >> 8))


# ═══════════════════════════════════════════════════════════════════════
#  STORE — the served address space
# ═══════════════════════════════════════════════════════════════════════
class SlaveStore:
    """16-bit words (a coil: 0/1) for every address the map covers, keyed by
    register KEY (area << 16 | address), plus the map itself.

    Written by the server thread (master writes) and by the GUI (typed
    values), hence the lock."""

    def __init__(self):
        self._lock = threading.Lock()
        self.words: dict[int, int] = {}
        self.registers: list[dict] = []
        self.areas: set[str] = set()          # Modbus tables the map uses
        self.access: dict[int, list] = {}     # reg key -> [reads, writes, last_ts]

    @classmethod
    def from_registers(cls, registers) -> "SlaveStore":
        st = cls()
        for reg in registers or []:
            if not isinstance(reg, dict):
                continue
            try:
                addr = int(reg.get("addr", 0))
            except (TypeError, ValueError):
                continue
            span = datatypes.addr_span(reg)
            if not 0 <= addr <= 0xFFFF:
                continue
            st.registers.append(reg)
            area = datatypes.area_of(reg)
            st.areas.add(area.key)
            for a in range(addr, min(addr + span, 0x10000)):
                st.words.setdefault((area.code << 16) | a, 0)
            default = str(reg.get("default", "") or "").strip()
            if default and datatypes.is_scalar(reg.get("type", "")):
                try:
                    st.set_value(reg, default)
                except (ValueError, TypeError, OverflowError):
                    pass                     # a bad default stays 0
        return st

    # ── word access (protocol side) ──────────────────────────────────
    def covers(self, addr: int, count: int) -> bool:
        """*addr* is a key; the run must stay inside its own table."""
        if (addr & 0xFFFF) + count > 0x10000:
            return False
        with self._lock:
            return all((addr + i) in self.words for i in range(count))

    def read(self, addr: int, count: int) -> list[int]:
        with self._lock:
            return [self.words[addr + i] for i in range(count)]

    def write(self, addr: int, values) -> None:
        with self._lock:
            for i, v in enumerate(values):
                if (addr + i) in self.words:
                    self.words[addr + i] = int(v) & 0xFFFF

    def touched(self, addr: int, count: int, kind: str) -> list[int]:
        """Book a read/write against every register it overlapped; returns
        the start addresses of those registers (the GUI refreshes them)."""
        hit = []
        end = addr + count
        now = time.time()
        with self._lock:
            for reg in self.registers:
                a = datatypes.reg_key(reg)
                if a < end and addr < a + datatypes.addr_span(reg):
                    rec = self.access.setdefault(a, [0, 0, 0.0])
                    rec[0 if kind == "read" else 1] += 1
                    rec[2] = now
                    hit.append(a)
        return hit

    def access_of(self, addr: int) -> tuple:
        """(reads, writes, last unix time) for the register at *addr*."""
        with self._lock:
            rec = self.access.get(int(addr))
            return tuple(rec) if rec else (0, 0, 0.0)

    # ── value access (GUI side, through the shared codecs) ───────────
    def reg_words(self, reg: dict) -> list[int]:
        return self.read(datatypes.reg_key(reg), datatypes.addr_span(reg))

    def get_value(self, reg: dict) -> str:
        dtype = reg.get("type", "SHORT")
        if not datatypes.is_scalar(dtype):
            return "—"
        words = self.reg_words(reg)
        n = datatypes.reg_read_count(reg)
        return datatypes.read_to_str(dtype, words[:n])

    def set_value(self, reg: dict, text: str) -> None:
        """Encode *text* with the register's type and store it. Raises
        ValueError for a value the type cannot hold."""
        dtype = reg.get("type", "SHORT")
        if not datatypes.is_scalar(dtype):
            raise ValueError(dtype)
        span = datatypes.addr_span(reg)
        if datatypes.is_text(dtype):
            words = datatypes.encode(dtype, str(text), span)
        else:
            words = datatypes.encode(dtype, str(text).strip().replace(",", "."))
        if not words:
            raise ValueError(dtype)
        self.write(datatypes.reg_key(reg), words)

    def span(self) -> tuple:
        with self._lock:
            if not self.words:
                return None, None
            return min(self.words), max(self.words)


# ═══════════════════════════════════════════════════════════════════════
#  THE RESPONDER (pure)
# ═══════════════════════════════════════════════════════════════════════
def _exception(sid: int, fc: int, code: int) -> bytes:
    return with_crc(bytes((sid, (fc | 0x80) & 0xFF, code)))


def build_response(request: bytes, store: SlaveStore, slave_id: int) -> dict:
    """One request frame → what a device with *slave_id* would do.

    Returns ``{"response": bytes | None, "fc", "addr", "count",
    "exception": code | None, "kind", "touched": [reg addrs]}``; *kind* is
    "read" / "write" / "exception" / "ignored" (no answer: bad CRC, another
    slave, a broadcast, junk)."""
    out = {"response": None, "fc": None, "addr": None, "count": None,
           "key": None, "exception": None, "kind": "ignored", "touched": [],
           "reason": ""}
    req = bytes(request)
    if len(req) < 4:
        out["reason"] = "short"
        return out
    if not frame_crc_ok(req):
        out["reason"] = "crc"
        return out
    sid, fc = req[0], req[1]
    out["fc"] = fc
    broadcast = sid == 0
    if sid != slave_id and not broadcast:
        out["reason"] = "other"
        return out
    body = req[2:-2]

    def fail(code):
        out["exception"], out["kind"] = code, "exception"
        if not broadcast:
            out["response"] = _exception(slave_id, fc, code)
        return out

    def head(area: str):
        """(key, count) from the usual addr+count header."""
        addr = int.from_bytes(body[0:2], "big")
        count = int.from_bytes(body[2:4], "big")
        key = _key(area, addr)
        out["addr"], out["count"], out["key"] = addr, count, key
        return key, count

    if fc in (0x01, 0x02, 0x03, 0x04):
        if broadcast:                        # a read cannot be broadcast
            out["reason"] = "broadcast"
            return out
        if len(body) != 4:
            return fail(ILLEGAL_VALUE)
        if fc == 0x04 and "input" not in store.areas:
            area = "holding"                 # a map without input registers
        else:
            area = {0x01: "coil", 0x02: "discrete",
                    0x03: "holding", 0x04: "input"}[fc]
        key, count = head(area)
        bits = _AREA[area].bits
        if not 1 <= count <= (MAX_BITS_READ if bits else MAX_READ):
            return fail(ILLEGAL_VALUE)
        if not store.covers(key, count):
            return fail(ILLEGAL_ADDRESS)
        words = store.read(key, count)
        data = (_pack_bits(words) if bits
                else b"".join(w.to_bytes(2, "big") for w in words))
        out["response"] = with_crc(bytes((slave_id, fc, len(data))) + data)
        out["kind"] = "read"
        out["touched"] = store.touched(key, count, "read")
        return out

    if fc in (0x05, 0x06):
        if len(body) != 4:
            return fail(ILLEGAL_VALUE)
        key, value = head("coil" if fc == 0x05 else "holding")
        out["count"] = 1
        if fc == 0x05:
            if value not in (0xFF00, 0x0000):   # the only two legal values
                return fail(ILLEGAL_VALUE)
            value = 1 if value else 0
        if not store.covers(key, 1):
            return fail(ILLEGAL_ADDRESS)
        store.write(key, [value])
        out["kind"] = "write"
        out["touched"] = store.touched(key, 1, "write")
        if not broadcast:
            out["response"] = req           # FC05/06 answer with an echo
        return out

    if fc in (0x0F, 0x10):
        if len(body) < 5:
            return fail(ILLEGAL_VALUE)
        key, count = head("coil" if fc == 0x0F else "holding")
        nbytes = body[4]
        if fc == 0x0F:
            ok = 1 <= count <= MAX_BITS_WRITE and nbytes == (count + 7) // 8
        else:
            ok = 1 <= count <= MAX_WRITE and nbytes == 2 * count
        if not ok or len(body) != 5 + nbytes:
            return fail(ILLEGAL_VALUE)
        if not store.covers(key, count):
            return fail(ILLEGAL_ADDRESS)
        data = body[5:]
        if fc == 0x0F:
            values = [(data[i // 8] >> (i % 8)) & 1 for i in range(count)]
        else:
            values = [int.from_bytes(data[2 * i:2 * i + 2], "big")
                      for i in range(count)]
        store.write(key, values)
        out["kind"] = "write"
        out["touched"] = store.touched(key, count, "write")
        if not broadcast:
            out["response"] = with_crc(bytes((slave_id, fc)) + body[0:4])
        return out

    return fail(ILLEGAL_FUNCTION)


# ═══════════════════════════════════════════════════════════════════════
#  THE SERVER THREAD
# ═══════════════════════════════════════════════════════════════════════
class SlaveServer(QThread):
    """Owns its serial port, frames requests by silence, answers them."""

    exchange = pyqtSignal(dict)     # one handled frame (request, response, info)
    error = pyqtSignal(object)      # (i18n_key, params)
    stopped = pyqtSignal()

    def __init__(self, port: str, baudrate: int, store: SlaveStore,
                 slave_id: int, parity: str = "N", stopbits: float = 1,
                 delay_ms: int = 0, parent=None):
        super().__init__(parent)
        self.port = port
        self.baudrate = int(baudrate)
        self.parity = parity
        self.stopbits = stopbits
        self.store = store
        self.slave_id = int(slave_id)
        self.delay = max(0, int(delay_ms)) / 1000.0
        self._stop = False

    def request_stop(self):
        self._stop = True

    def run(self):
        try:
            import serial
            ser = serial.Serial(self.port, self.baudrate, parity=self.parity,
                                stopbits=self.stopbits, timeout=0.001)
        except Exception as e:
            self.error.emit(("slvPortFail", {"err": str(e)}))
            self.stopped.emit()
            return
        gap = max(0.00175, 3.5 * 11.0 / self.baudrate)
        buf = bytearray()
        last_rx = time.monotonic()
        try:
            while not self._stop:
                chunk = ser.read(256)
                now = time.monotonic()
                if chunk:
                    if buf and (now - last_rx) > gap:
                        self._handle(ser, buf)
                    buf.extend(chunk)
                    last_rx = now
                    if len(buf) > 1024:
                        self._handle(ser, buf)
                elif buf and (now - last_rx) > gap:
                    self._handle(ser, buf)
        except Exception as e:
            self.error.emit(("slvReadFail", {"err": str(e)}))
        finally:
            try:
                ser.close()
            except Exception:
                pass
            self.stopped.emit()

    def _handle(self, ser, buf: bytearray):
        frames = carve_frames(bytes(buf))
        buf.clear()
        for frame in frames:
            info = build_response(frame, self.store, self.slave_id)
            resp = info["response"]
            if resp is not None:
                if self.delay:
                    time.sleep(self.delay)   # emulate a slow device
                ser.write(resp)
                flush = getattr(ser, "flush", None)
                if flush:
                    flush()
            info["request"] = bytes(frame)
            info["time"] = time.time()
            self.exchange.emit(info)


# ═══════════════════════════════════════════════════════════════════════
#  MODBUS TCP
# ═══════════════════════════════════════════════════════════════════════
UNIT_DIRECT = (0, 255)       # unit ids that address "the device at this IP"
DEFAULT_TCP_PORT = 502
MAX_TCP_CLIENTS = 16


def tcp_response(adu: bytes, store: SlaveStore, slave_id: int) -> dict:
    """One Modbus TCP request (MBAP header + PDU) → what the emulator does.

    The same dict as ``build_response``; "request" / "response" are the
    MBAP frames as they travel, "unit" the unit id the master used. The
    answer repeats the request's transaction id and unit id."""
    adu = bytes(adu)
    unit = adu[6] if len(adu) > 6 else 0
    pdu = adu[7:]
    target = slave_id if unit in UNIT_DIRECT else unit
    info = build_response(with_crc(bytes((target,)) + pdu), store, slave_id)
    resp = info["response"]
    if resp is not None:
        body = bytes((unit,)) + resp[1:-2]            # unit + PDU, no CRC
        resp = adu[0:2] + b"\x00\x00" + len(body).to_bytes(2, "big") + body
    info["response"] = resp
    info["request"] = adu
    info["unit"] = unit
    return info


def bind_error_key(e: OSError) -> str:
    """i18n key that explains why the server could not listen."""
    codes = {getattr(e, "winerror", None), getattr(e, "errno", None)}
    if codes & {98, 48, 10048}:                       # EADDRINUSE
        return "slvTcpInUse"
    if codes & {13, 10013}:                           # EACCES
        return "slvTcpDenied"
    if codes & {99, 49, 10049}:                       # EADDRNOTAVAIL
        return "slvTcpBadHost"
    return "slvTcpFail"


def rtu_request_length(buf) -> int | None:
    """Length of the RTU request that starts *buf* (None: not known yet,
    0: not a request this emulator can frame — take what is there)."""
    if len(buf) < 2:
        return None
    fc = buf[1]
    if 0x01 <= fc <= 0x06:
        return 8                                       # id fc addr count/value crc
    if fc in (0x0F, 0x10):
        return None if len(buf) < 7 else 9 + buf[6]
    return 0


class SlaveTcpServer(QThread):
    """Listens on a TCP port and answers every connected master. One
    selector loop: requests are short, the store is shared and locked.

    framing "mbap" — Modbus TCP; "rtu" — RTU frames (with CRC) through the
    socket, the way a serial-to-Ethernet converter passes them on."""

    exchange = pyqtSignal(dict)     # one handled request (as SlaveServer)
    error = pyqtSignal(object)      # (i18n_key, params)
    stopped = pyqtSignal()
    clients_changed = pyqtSignal(list)    # "ip:port" of every connected master

    def __init__(self, host: str, port: int, store: SlaveStore, slave_id: int,
                 delay_ms: int = 0, framing: str = "mbap", parent=None):
        super().__init__(parent)
        self.framing = "rtu" if framing == "rtu" else "mbap"
        self.host = str(host or "0.0.0.0")
        self.port = int(port)
        self.store = store
        self.slave_id = int(slave_id)
        self.delay = max(0, int(delay_ms)) / 1000.0
        self.baudrate = 0               # the serial server's field, for callers
        self.listening = threading.Event()   # set once the port is open
        self._stop = False

    def request_stop(self):
        self._stop = True

    def _listen(self) -> socket.socket:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name == "nt":
                # Windows' SO_REUSEADDR would let a second program bind the
                # same port and steal half the connections; exclusive use
                # makes a busy port fail loudly instead.
                opt = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
                if opt is not None:
                    srv.setsockopt(socket.SOL_SOCKET, opt, 1)
            else:
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((self.host, self.port))
            srv.listen(8)
            srv.setblocking(False)
        except OSError:
            srv.close()
            raise
        return srv

    def run(self):
        try:
            srv = self._listen()
        except OSError as e:
            self.error.emit((bind_error_key(e), {"port": self.port, "err": str(e)}))
            self.stopped.emit()
            return
        self.port = srv.getsockname()[1]          # the real one when 0 was asked
        self.listening.set()
        sel = selectors.DefaultSelector()
        sel.register(srv, selectors.EVENT_READ, None)
        clients: dict = {}                         # socket -> [peer, buffer]
        try:
            while not self._stop:
                for key, _mask in sel.select(timeout=0.1):
                    if key.data is None:
                        self._accept(srv, sel, clients)
                    else:
                        self._serve(key.fileobj, sel, clients)
        except Exception as e:                     # never die silently
            self.error.emit(("slvReadFail", {"err": str(e)}))
        finally:
            for sock in list(clients):
                self._drop(sock, sel, clients, announce=False)
            try:
                sel.close()
            except Exception:
                pass
            srv.close()
            self.listening.clear()
            self.clients_changed.emit([])
            self.stopped.emit()

    def _accept(self, srv, sel, clients):
        try:
            sock, addr = srv.accept()
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            return
        if len(clients) >= MAX_TCP_CLIENTS:
            sock.close()                           # a device has a limit too
            return
        sock.setblocking(False)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        peer = f"{addr[0]}:{addr[1]}"
        clients[sock] = [peer, bytearray()]
        sel.register(sock, selectors.EVENT_READ, peer)
        self.clients_changed.emit([c[0] for c in clients.values()])

    def _drop(self, sock, sel, clients, announce=True):
        clients.pop(sock, None)
        try:
            sel.unregister(sock)
        except (KeyError, ValueError, OSError):
            pass
        if not announce:
            # The server is stopping: reset instead of the polite close. A
            # politely closed connection lingers in TIME_WAIT on OUR port,
            # and Windows then refuses to listen on it again for minutes —
            # Stop → Start would fail with "port in use".
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                                struct.pack("ii", 1, 0))
            except OSError:
                pass
        try:
            sock.close()
        except OSError:
            pass
        if announce:
            self.clients_changed.emit([c[0] for c in clients.values()])

    def _serve(self, sock, sel, clients):
        entry = clients.get(sock)
        if entry is None:
            return
        peer, buf = entry
        try:
            chunk = sock.recv(4096)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            chunk = b""
        if not chunk:
            self._drop(sock, sel, clients)
            return
        buf += chunk
        if self.framing == "rtu":
            self._serve_rtu(sock, sel, clients, peer, buf)
            return
        while len(buf) >= 7:
            proto = int.from_bytes(buf[2:4], "big")
            length = int.from_bytes(buf[4:6], "big")
            if proto != 0 or not 2 <= length <= 254:
                # Not Modbus TCP (or out of step): a real device drops the
                # connection rather than guess where the next frame starts.
                self.exchange.emit({"response": None, "fc": None, "addr": None,
                                    "count": None, "key": None, "exception": None,
                                    "kind": "ignored", "touched": [],
                                    "reason": "mbap", "request": bytes(buf[:64]),
                                    "time": time.time(), "peer": peer})
                self._drop(sock, sel, clients)
                return
            total = 6 + length
            if len(buf) < total:
                break
            adu = bytes(buf[:total])
            del buf[:total]
            info = tcp_response(adu, self.store, self.slave_id)
            resp = info["response"]
            if resp is not None:
                if self.delay:
                    time.sleep(self.delay)         # emulate a slow device
                try:
                    sock.settimeout(1.0)
                    sock.sendall(resp)
                    sock.setblocking(False)
                except OSError:
                    self._drop(sock, sel, clients)
                    return
            info["time"] = time.time()
            info["peer"] = peer
            self.exchange.emit(info)

    def _serve_rtu(self, sock, sel, clients, peer, buf):
        while buf:
            need = rtu_request_length(buf)
            if need is None or (need and len(buf) < need):
                if len(buf) > 512:                 # junk that never ends
                    buf.clear()
                return
            frame = bytes(buf[:need] if need else buf)
            del buf[:len(frame)]
            info = build_response(frame, self.store, self.slave_id)
            resp = info["response"]
            if resp is not None:
                if self.delay:
                    time.sleep(self.delay)
                try:
                    sock.settimeout(1.0)
                    sock.sendall(resp)
                    sock.setblocking(False)
                except OSError:
                    self._drop(sock, sel, clients)
                    return
            info["request"] = frame
            info["time"] = time.time()
            info["peer"] = peer
            self.exchange.emit(info)
