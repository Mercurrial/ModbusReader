"""The app's own Modbus client (core/modbus_client) against its own slave emulator.

FakeLine is a serial port wired to core/slave_core.build_response — the same
pure responder the app's «Эмулятор (Slave)» uses — with the knobs a real line
has: an adapter that echoes what it sends, noise before the answer, a
corrupted CRC, an answer that arrives in pieces, a device that stays silent.
Nothing here needs hardware.
"""
import time

import pytest

from core import modbus_client as rm
from core import slave_core as sc
from core.sniffer_core import crc16

MAP = [
    {"addr": 0x10, "name": "Setpoint", "type": "SHORT", "rw": "RW"},
    {"addr": 0x11, "name": "Mode", "type": "SHORT", "rw": "RW"},
    {"addr": 0x00, "name": "Temp", "type": "SHORT", "area": "input", "rw": "R"},
    {"addr": 0x00, "name": "Pump", "type": "BOOL", "area": "coil", "rw": "RW"},
    {"addr": 0x01, "name": "Fan", "type": "BOOL", "area": "coil", "rw": "RW"},
    {"addr": 0x02, "name": "Heater", "type": "BOOL", "area": "coil", "rw": "RW"},
    {"addr": 0x00, "name": "Door", "type": "BOOL", "area": "discrete", "rw": "R"},
]
SID = 10


class FakeLine:
    """What the master sees of the port. Bytes become readable at the time
    a real line would deliver them."""

    def __init__(self, store, slave_id=SID, echo=False, noise=b"", corrupt=False,
                 pieces=1, piece_gap=0.0, delay=0.0, silent=False):
        self.store, self.slave_id = store, slave_id
        self.echo, self.noise, self.corrupt = echo, noise, corrupt
        self.pieces, self.piece_gap, self.delay, self.silent = pieces, piece_gap, delay, silent
        self.is_open = True
        self.written = []
        self.kwargs = {}
        self._rx = bytearray()
        self._pending = []               # (when, bytes)

    # the factory RtuMaster calls
    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self

    def _deliver(self):
        now = time.monotonic()
        ready = [p for p in self._pending if p[0] <= now]
        self._pending = [p for p in self._pending if p[0] > now]
        for _, data in sorted(ready, key=lambda p: p[0]):
            self._rx += data

    @property
    def in_waiting(self):
        self._deliver()
        return len(self._rx)

    def read(self, n):
        self._deliver()
        out, self._rx = bytes(self._rx[:n]), self._rx[n:]
        return out

    def reset_input_buffer(self):
        self._deliver()
        self._rx.clear()

    def write(self, data):
        data = bytes(data)
        self.written.append(data)
        now = time.monotonic()
        if self.echo:
            self._pending.append((now, data))
        if self.silent:
            return len(data)
        answer = sc.build_response(data, self.store, self.slave_id)["response"]
        if answer is None:
            return len(data)
        if self.corrupt:
            answer = answer[:-1] + bytes((answer[-1] ^ 0x5A,))
        answer = self.noise + answer
        size = max(1, -(-len(answer) // self.pieces))
        t = now + self.delay + 0.0005
        for i in range(0, len(answer), size):
            self._pending.append((t, answer[i:i + size]))
            t += self.piece_gap
        return len(data)

    def flush(self):
        pass

    def close(self):
        self.is_open = False


def _store():
    st = sc.SlaveStore.from_registers(MAP)
    st.write(0x10, [1234])
    st.write(0x11, [7])
    st.write(sc._key("input", 0), [215])
    st.write(sc._key("coil", 0), [1])
    st.write(sc._key("coil", 2), [1])
    st.write(sc._key("discrete", 0), [1])
    return st


def _master(line, **kw):
    m = rm.RtuMaster("COM7", baudrate=115200, parity="E", stopbits=1,
                     timeout=kw.pop("timeout", 0.3), retries=kw.pop("retries", 0),
                     serial_factory=line)
    assert m.connect()
    return m


# ── the frames themselves ─────────────────────────────────────────────
def test_the_request_frame_is_byte_exact():
    line = FakeLine(_store())
    _master(line).read_holding_registers(0x10, 2, device_id=SID)
    body = bytes((SID, 0x03, 0x00, 0x10, 0x00, 0x02))
    crc = crc16(body)
    assert line.written == [body + bytes((crc & 0xFF, crc >> 8))]


def test_the_port_is_opened_as_configured():
    line = FakeLine(_store())
    _master(line)
    assert line.kwargs["port"] == "COM7" and line.kwargs["baudrate"] == 115200
    assert line.kwargs["parity"] == "E" and line.kwargs["stopbits"] == 1
    assert line.kwargs["bytesize"] == 8 and line.kwargs["timeout"] == 0


@pytest.mark.parametrize("baud,expected", [(9600, 3.5 * 11 / 9600), (19200, 3.5 * 11 / 19200),
                                           (38400, 0.00175), (115200, 0.00175)])
def test_t35_follows_the_standard(baud, expected):
    assert rm.t35(baud) == pytest.approx(expected)


# ── every table the app reads, both writes ────────────────────────────
def test_reads_every_table():
    m = _master(FakeLine(_store()))
    r = m.read_holding_registers(0x10, 2, device_id=SID)
    assert (r.outcome, r.registers, r.isError()) == ("ok", [1234, 7], False)
    assert m.read_input_registers(0x00, 1, device_id=SID).registers == [215]
    assert m.read_coils(0x00, 3, device_id=SID).bits == [1, 0, 1]
    assert m.read_discrete_inputs(0x00, 1, device_id=SID).bits == [1]


def test_writes_reach_the_device():
    st = _store()
    m = _master(FakeLine(st))
    r = m.write_register(0x11, 0xBEEF, device_id=SID)
    assert r.outcome == "ok" and st.read(0x11, 1) == [0xBEEF]
    assert m.write_coil(0x01, True, device_id=SID).outcome == "ok"
    assert st.read(sc._key("coil", 1), 1) == [1]
    assert m.write_coil(0x00, False, device_id=SID).outcome == "ok"
    assert st.read(sc._key("coil", 0), 1) == [0]
    assert m.write_registers(0x10, [1, 2], device_id=SID).outcome == "ok"
    assert st.read(0x10, 2) == [1, 2]


def test_a_device_exception_is_an_answer_not_a_failure():
    m = _master(FakeLine(_store()))
    r = m.read_holding_registers(0x200, 1, device_id=SID)       # outside the map
    assert r.outcome == "exception" and r.isError()
    assert r.function_code == 0x83 and r.exception_code == sc.ILLEGAL_ADDRESS


# ── what goes wrong on real lines ─────────────────────────────────────
def test_silence_is_a_timeout_after_the_set_time():
    m = _master(FakeLine(_store(), silent=True), timeout=0.15)
    t0 = time.monotonic()
    r = m.read_holding_registers(0x10, 1, device_id=SID)
    took = time.monotonic() - t0
    assert r.outcome == "timeout" and r.function_code == 0 and r.isError()
    assert 0.14 <= took < 0.6


def test_another_device_id_is_not_answered():
    m = _master(FakeLine(_store()), timeout=0.15)
    assert m.read_holding_registers(0x10, 1, device_id=SID + 1).outcome == "timeout"


def test_a_bad_crc_is_reported_as_such():
    r = _master(FakeLine(_store(), corrupt=True)).read_holding_registers(0x10, 1, device_id=SID)
    assert r.outcome == "crc" and r.isError() and r.raw


def test_an_answer_in_pieces_is_put_together():
    line = FakeLine(_store(), pieces=4, piece_gap=0.01)
    r = _master(line).read_holding_registers(0x10, 2, device_id=SID)
    assert r.outcome == "ok" and r.registers == [1234, 7]


def test_noise_before_the_answer_is_skipped():
    r = _master(FakeLine(_store(), noise=b"\x00\xff")).read_holding_registers(
        0x10, 1, device_id=SID)
    assert r.outcome == "ok" and r.registers == [1234]


def test_an_answer_cut_short_is_corrupt_not_silence():
    line = FakeLine(_store())
    m = _master(line, timeout=0.3)
    real_write = line.write

    def cut(data):
        n = real_write(data)
        line._pending = [(t, b[:3]) for t, b in line._pending]     # only 3 bytes arrive
        return n
    line.write = cut
    assert m.read_holding_registers(0x10, 2, device_id=SID).outcome == "crc"


def test_it_does_not_wait_out_the_timeout_once_the_answer_is_complete():
    m = _master(FakeLine(_store()), timeout=2.0)
    t0 = time.monotonic()
    m.read_holding_registers(0x10, 2, device_id=SID)
    assert time.monotonic() - t0 < 0.3


@pytest.mark.parametrize("first", ["read", "write"])
def test_an_echoing_adapter(first):
    """2-wire RS-485 adapters without echo suppression hand back every byte
    sent. A read's echo is dropped; for FC 06, whose answer IS a copy of the
    request, the master learns from the first exchange that the line echoes."""
    st = _store()
    m = _master(FakeLine(st, echo=True))
    if first == "read":
        assert m.read_holding_registers(0x10, 1, device_id=SID).registers == [1234]
        assert m.echo is True
    r = m.write_register(0x11, 99, device_id=SID)
    assert r.outcome == "ok" and st.read(0x11, 1) == [99]
    assert m.echo is True
    assert m.read_holding_registers(0x11, 1, device_id=SID).registers == [99]


def test_a_line_without_echo_is_learned_too():
    m = _master(FakeLine(_store()))
    m.read_holding_registers(0x10, 1, device_id=SID)
    assert m.echo is False
    t0 = time.monotonic()
    assert m.write_register(0x11, 5, device_id=SID).outcome == "ok"
    assert time.monotonic() - t0 < rm.MIN_GAP_S  # no waiting for a second copy


def test_a_first_write_on_a_line_without_echo_learns_it():
    """Writing before any read: the master waits once for a possible second
    copy, finds none, and never waits for it again."""
    m = _master(FakeLine(_store()))
    assert m.write_register(0x11, 5, device_id=SID).outcome == "ok"
    assert m.echo is False
    t0 = time.monotonic()
    assert m.write_register(0x11, 6, device_id=SID).outcome == "ok"
    assert time.monotonic() - t0 < rm.MIN_GAP_S


def test_retries_repeat_only_failures():
    line = FakeLine(_store(), silent=True)
    m = _master(line, timeout=0.05, retries=2)
    assert m.read_holding_registers(0x10, 1, device_id=SID).outcome == "timeout"
    assert len(line.written) == 3
    line2 = FakeLine(_store())
    _master(line2, retries=2).read_holding_registers(0x10, 1, device_id=SID)
    assert len(line2.written) == 1


def test_broadcast_writes_wait_for_nobody():
    st = _store()
    m = _master(FakeLine(st), timeout=1.0)
    t0 = time.monotonic()
    assert m.write_register(0x11, 42, device_id=0).outcome == "ok"
    assert time.monotonic() - t0 < 0.1 and st.read(0x11, 1) == [42]


def test_a_dead_port_raises_a_link_error():
    line = FakeLine(_store())
    m = _master(line)

    def broken(_data):
        raise OSError("device disconnected")
    line.write = broken
    with pytest.raises(rm.ModbusLinkError):
        m.read_holding_registers(0x10, 1, device_id=SID)
    m.close()
    with pytest.raises(rm.ModbusLinkError):
        m.read_holding_registers(0x10, 1, device_id=SID)


def test_a_port_that_will_not_open_is_reported_by_connect():
    def refuse(**_kw):
        raise OSError("could not open port COM7")
    assert rm.RtuMaster("COM7", serial_factory=refuse).connect() is False


# ── inside the app ───────────────────────────────────────────────────
def test_the_transports_build_the_apps_own_clients():
    from core import transports
    c = transports.get("serial").create({"port": "COM9", "baudrate": "19200",
                                         "parity": "Even (E)"}, 0.5)
    assert isinstance(c, rm.RtuMaster)
    assert (c.port, c.baudrate, c.parity, c.timeout, c.retries) == ("COM9", 19200, "E", 0.5, 1)
    t = transports.get("tcp").create({"host": "10.0.0.5", "tcp_port": "5020"}, 0.2)
    assert isinstance(t, rm.TcpMaster) and (t.host, t.port, t.timeout) == ("10.0.0.5", 5020, 0.2)


def _core_with(line):
    from core.modbus_core import ModbusCore
    core = ModbusCore()
    core.setup_connection({"port": "COM7"}, SID)
    core.client = _master(line, timeout=0.15)
    return core


def test_the_core_reads_and_writes_through_the_builtin_master():
    from core import datatypes
    st = _store()
    core = _core_with(FakeLine(st))
    got = []
    core.data_updated.connect(lambda key, text: got.append((key, text)))
    assert core._execute_read(0x10, "SHORT", 1) is True
    assert got[-1][0] == 0x10 and "1234" in got[-1][1]
    coil = datatypes.reg_key({"addr": 2, "area": "coil"})
    assert core._execute_read(coil, "BOOL", 1) is True and got[-1][0] == coil
    assert core._safe_write_single(0x11, 321).outcome == "ok"
    assert st.read(0x11, 1) == [321]
    assert core.stats.snapshot()["ok"] == 2


@pytest.mark.parametrize("line_kw,result,counter", [
    ({"silent": True}, None, "timeouts"),       # no answer → counts towards "link lost"
    ({"corrupt": True}, None, "crc"),           # a CRC error, told apart without any probe
])
def test_the_core_counts_line_failures(line_kw, result, counter):
    core = _core_with(FakeLine(_store(), **line_kw))
    assert core._execute_read(0x10, "SHORT", 1) is result
    snap = core.stats.snapshot()
    assert snap[counter] == 1 and snap["responses"] == 0


def test_a_device_exception_keeps_the_link_alive():
    """An exception answer means the device is there: _execute_read returns
    False (not None), so the poll loop does not count it as a lost link."""
    core = _core_with(FakeLine(_store()))
    assert core._execute_read(0x300, "SHORT", 1) is False
    snap = core.stats.snapshot()
    assert snap["exceptions"] == 1 and snap["responses"] == 1


def test_the_scanner_probe_tells_alive_exception_and_silence():
    core = _core_with(FakeLine(_store()))
    assert core._probe(0x10, SID) == "alive"
    assert core._probe(0x300, SID) == "exception"
    assert core._probe(0x10, SID + 3) == "silent"


def test_the_raw_console_writes_to_the_builtin_masters_port():
    line = FakeLine(_store())
    core = _core_with(line)
    frame = sc.with_crc(bytes((SID, 0x03, 0x00, 0x10, 0x00, 0x01)))
    logs = []
    core.log_msg.connect(lambda kind, text: logs.append((kind, text)))
    core._execute_raw(frame)
    assert line.written[-1] == frame
    assert any(kind == "RX" for kind, _ in logs)


# ═══════════════ Modbus TCP ═══════════════
class FakeTcp:
    """A TCP connection to the slave emulator: MBAP in, MBAP out (the
    emulator speaks RTU, so the CRC is added and stripped on the way)."""

    def __init__(self, store, slave_id=SID, silent=False, stale=False, close=False):
        self.store, self.slave_id = store, slave_id
        self.silent, self.stale, self.close_on_send = silent, stale, close
        self._rx = b""
        self.sent = []
        self.timeout = None
        self.addr = None

    def __call__(self, addr, timeout=None):        # the socket factory
        self.addr = addr
        return self

    def sendall(self, data):
        self.sent.append(bytes(data))
        if self.close_on_send:
            self._rx = None
            return
        tid, unit, pdu = data[0:2], data[6], data[7:]
        if self.silent:
            return
        answer = sc.build_response(sc.with_crc(bytes((unit,)) + pdu), self.store,
                                   self.slave_id)["response"]
        if answer is None:
            return
        body = answer[:-2]                           # unit + pdu, no CRC
        frame = tid + b"\x00\x00" + len(body).to_bytes(2, "big") + body
        if self.stale:                               # a late answer to request 0 first
            self._rx += b"\x00\x00" + frame[2:]
        self._rx += frame

    def settimeout(self, t):
        self.timeout = t

    def recv(self, n):
        import socket
        if self._rx is None:
            return b""                               # the device closed the connection
        if not self._rx:
            time.sleep(min(self.timeout or 0.05, 0.05))
            raise socket.timeout()
        out, self._rx = self._rx[:n], self._rx[n:]
        return out

    def close(self):
        pass


def _tcp(conn, **kw):
    m = rm.TcpMaster("plc.local", port=502, timeout=kw.pop("timeout", 0.3),
                     retries=kw.pop("retries", 0), socket_factory=conn)
    assert m.connect() and conn.addr == ("plc.local", 502)
    return m


def test_tcp_frames_carry_an_mbap_header():
    conn = FakeTcp(_store())
    _tcp(conn).read_holding_registers(0x10, 2, device_id=SID)
    assert conn.sent == [b"\x00\x01\x00\x00\x00\x06" + bytes((SID, 3, 0, 0x10, 0, 2))]


def test_tcp_reads_and_writes():
    st = _store()
    m = _tcp(FakeTcp(st))
    assert m.read_holding_registers(0x10, 2, device_id=SID).registers == [1234, 7]
    assert m.read_coils(0x00, 3, device_id=SID).bits == [1, 0, 1]
    assert m.write_register(0x11, 77, device_id=SID).outcome == "ok"
    assert st.read(0x11, 1) == [77]
    r = m.read_holding_registers(0x300, 1, device_id=SID)
    assert r.outcome == "exception" and r.exception_code == sc.ILLEGAL_ADDRESS


def test_tcp_silence_is_a_timeout():
    m = _tcp(FakeTcp(_store(), silent=True), timeout=0.1)
    assert m.read_holding_registers(0x10, 1, device_id=SID).outcome == "timeout"


def test_tcp_skips_a_late_answer_to_an_earlier_request():
    m = _tcp(FakeTcp(_store(), stale=True))
    r = m.read_holding_registers(0x10, 1, device_id=SID)
    assert r.outcome == "ok" and r.registers == [1234]


def test_tcp_a_dropped_connection_is_a_link_error():
    m = _tcp(FakeTcp(_store(), close=True))
    with pytest.raises(rm.ModbusLinkError):
        m.read_holding_registers(0x10, 1, device_id=SID)


def test_tcp_a_refused_connection_is_reported_by_connect():
    def refuse(addr, timeout=None):
        raise ConnectionRefusedError(addr)
    assert rm.TcpMaster("10.9.9.9", socket_factory=refuse).connect() is False
