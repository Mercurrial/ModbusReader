"""Modbus TCP and RTU-over-TCP on real sockets (127.0.0.1).

The master (core/modbus_client) talks to the app's own TCP server
(core/slave_core.SlaveTcpServer) through the operating system's network
stack — no fakes between them. The frames the spec prints are checked byte
for byte with a bare socket, so the two halves cannot agree on a mistake.

Everything listens on 127.0.0.1 only: a listener on all interfaces would
make Windows ask about its firewall in the middle of a test run.
"""
import socket
import threading
import time

import pytest
from PyQt6.QtCore import Qt

from core import modbus_client as mc
from core import slave_core as sc

MAP = [
    {"addr": 0x10, "name": "Setpoint", "type": "SHORT", "rw": "RW", "default": "1234"},
    {"addr": 0x11, "name": "Mode", "type": "SHORT", "rw": "RW", "default": "7"},
    {"addr": 0x00, "name": "Temp", "type": "SHORT", "area": "input", "rw": "R", "default": "215"},
    {"addr": 0x00, "name": "Pump", "type": "BOOL", "area": "coil", "rw": "RW", "default": "1"},
    {"addr": 0x01, "name": "Fan", "type": "BOOL", "area": "coil", "rw": "RW"},
    {"addr": 0x02, "name": "Heater", "type": "BOOL", "area": "coil", "rw": "RW", "default": "1"},
    {"addr": 0x00, "name": "Door", "type": "BOOL", "area": "discrete", "rw": "R", "default": "1"},
]
SID = 10
HOST = "127.0.0.1"
DIRECT = Qt.ConnectionType.DirectConnection


def _start(framing="mbap", port=0, sid=SID, store=None, delay_ms=0):
    store = store or sc.SlaveStore.from_registers(MAP)
    srv = sc.SlaveTcpServer(HOST, port, store, sid, delay_ms=delay_ms, framing=framing)
    errors, exchanges, peers = [], [], []
    # Direct: the lists fill in the server thread itself — a queued
    # connection would wait for an event loop the tests do not run.
    srv.error.connect(errors.append, DIRECT)
    srv.exchange.connect(exchanges.append, DIRECT)
    srv.clients_changed.connect(peers.append, DIRECT)
    srv.start()
    assert srv.listening.wait(5), errors
    srv.errors, srv.exchanges, srv.peers = errors, exchanges, peers
    return srv


def _stop(srv):
    srv.request_stop()
    assert srv.wait(5000)


@pytest.fixture
def server():
    srv = _start()
    yield srv
    _stop(srv)


@pytest.fixture
def rtu_server():
    srv = _start("rtu")
    yield srv
    _stop(srv)


def _master(srv, cls=mc.TcpMaster, timeout=0.5):
    m = cls(HOST, port=srv.port, timeout=timeout, retries=0)
    assert m.connect(), m.last_error_text
    return m


# ── Modbus TCP ────────────────────────────────────────────────────────
def test_reads_every_table_over_tcp(server):
    m = _master(server)
    try:
        assert m.read_holding_registers(0x10, 2, device_id=SID).registers == [1234, 7]
        assert m.read_input_registers(0x00, 1, device_id=SID).registers == [215]
        assert m.read_coils(0x00, 3, device_id=SID).bits == [1, 0, 1]
        assert m.read_discrete_inputs(0x00, 1, device_id=SID).bits == [1]
    finally:
        m.close()


def test_writes_land_in_the_served_map(server):
    m = _master(server)
    try:
        assert m.write_register(0x11, 0xBEEF, device_id=SID).outcome == "ok"
        assert m.write_coil(0x01, True, device_id=SID).outcome == "ok"
        assert m.write_registers(0x10, [1, 2], device_id=SID).outcome == "ok"
        assert server.store.read(0x10, 2) == [1, 2]
        assert m.read_coils(0x00, 3, device_id=SID).bits == [1, 1, 1]
    finally:
        m.close()


def test_an_unserved_address_is_an_exception_not_a_timeout(server):
    m = _master(server)
    try:
        r = m.read_holding_registers(0x300, 1, device_id=SID)
        assert r.outcome == "exception" and r.exception_code == sc.ILLEGAL_ADDRESS
        assert r.function_code == 0x83
    finally:
        m.close()


def test_unit_ids_0_and_255_reach_the_device_by_its_ip(server):
    m = _master(server, timeout=0.3)
    try:
        for unit in (SID, 0, 255):
            r = m.read_holding_registers(0x10, 1, device_id=unit)
            assert r.outcome == "ok" and r.registers == [1234], unit
            assert r.raw[6] == unit                   # the answer repeats the unit id
        assert m.read_holding_registers(0x10, 1, device_id=3).outcome == "timeout"
    finally:
        m.close()


def test_the_frames_the_spec_prints_byte_for_byte(server):
    """MBAP request built by hand — not by the master under test."""
    with socket.create_connection((HOST, server.port), timeout=2) as s:
        # tid 0x1501, protocol 0, length 6, unit 10, FC03, addr 0x0010, count 2
        s.sendall(bytes.fromhex("1501 0000 0006 0a 03 0010 0002"))
        answer = _recv_exact(s, 13)
        assert answer == bytes.fromhex("1501 0000 0007 0a 03 04 04d2 0007")
        # FC06 to 0x0011 → the echo of the request
        s.sendall(bytes.fromhex("0002 0000 0006 0a 06 0011 00ff"))
        assert _recv_exact(s, 12) == bytes.fromhex("0002 0000 0006 0a 06 0011 00ff")
        # FC10, two registers from 0x0010 → addr + count
        s.sendall(bytes.fromhex("0003 0000 000b 0a 10 0010 0002 04 0001 0002"))
        assert _recv_exact(s, 12) == bytes.fromhex("0003 0000 0006 0a 10 0010 0002")
        # unknown function 0x2B → exception 01
        s.sendall(bytes.fromhex("0004 0000 0002 0a 2b"))
        assert _recv_exact(s, 9) == bytes.fromhex("0004 0000 0003 0a ab 01")


def test_two_requests_in_one_packet_get_two_answers(server):
    with socket.create_connection((HOST, server.port), timeout=2) as s:
        s.sendall(bytes.fromhex("0001 0000 0006 0a 03 0010 0001"
                                "0002 0000 0006 0a 03 0011 0001"))
        got = _recv_exact(s, 22)
    assert got[:11] == bytes.fromhex("0001 0000 0005 0a 03 02 04d2")
    assert got[11:] == bytes.fromhex("0002 0000 0005 0a 03 02 0007")


def test_a_request_split_across_packets_is_reassembled(server):
    with socket.create_connection((HOST, server.port), timeout=2) as s:
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        for part in ("0001 00", "00 0006 0a", " 03 0010", " 0001"):
            s.sendall(bytes.fromhex(part))
            time.sleep(0.03)
        assert _recv_exact(s, 11) == bytes.fromhex("0001 0000 0005 0a 03 02 04d2")


def test_a_non_modbus_stream_is_dropped(server):
    with socket.create_connection((HOST, server.port), timeout=2) as s:
        s.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
        s.settimeout(2)
        assert s.recv(100) == b""                   # the server closed it
    assert any(e.get("reason") == "mbap" for e in server.exchanges)


def test_several_masters_at_once(server):
    masters = [_master(server) for _ in range(4)]
    results, errors = [], []

    def poll(m):
        try:
            for _ in range(20):
                results.append(m.read_holding_registers(0x10, 2, device_id=SID).registers)
        except Exception as e:                        # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=poll, args=(m,)) for m in masters]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    for m in masters:
        m.close()
    assert not errors and len(results) == 80
    assert all(r == [1234, 7] for r in results)
    assert max(len(p) for p in server.peers) == 4


def test_a_late_answer_does_not_shift_the_next_one():
    """A slow device answers after the master gave up: that answer must be
    thrown away, not read as the answer to the next request."""
    srv = _start(delay_ms=250)
    try:
        m = _master(srv, timeout=0.1)
        assert m.read_holding_registers(0x10, 1, device_id=SID).outcome == "timeout"
        m.timeout = 1.0
        time.sleep(0.3)                               # the late answer arrives now
        r = m.read_holding_registers(0x11, 1, device_id=SID)
        assert r.outcome == "ok" and r.registers == [7]
        m.close()
    finally:
        _stop(srv)


def test_a_connection_the_device_closed_is_opened_again():
    """Devices drop idle connections. The next request reconnects instead
    of failing — the operator never sees it."""
    lsock = socket.socket()
    lsock.bind((HOST, 0))
    lsock.listen(4)
    port = lsock.getsockname()[1]
    store = sc.SlaveStore.from_registers(MAP)
    served = []

    def device():
        for _ in range(2):                            # two connections, one request each
            conn, _ = lsock.accept()
            with conn:
                req = _recv_exact(conn, 12)
                conn.sendall(sc.tcp_response(req, store, SID)["response"])
                served.append(req)
            # closed after one answer: an "idle timeout" on the device side

    t = threading.Thread(target=device, daemon=True)
    t.start()
    m = mc.TcpMaster(HOST, port=port, timeout=1.0, retries=0)
    assert m.connect()
    assert m.read_holding_registers(0x10, 1, device_id=SID).registers == [1234]
    time.sleep(0.1)                                   # the device has closed it by now
    assert m.read_holding_registers(0x11, 1, device_id=SID).registers == [7]
    m.close()
    t.join(5)
    lsock.close()
    assert len(served) == 2


def test_stop_then_start_on_the_same_port(server):
    """Stop → Start in the emulator must not fail with "port in use"
    (connections left in TIME_WAIT on the server's port)."""
    m = _master(server)
    assert m.read_holding_registers(0x10, 1, device_id=SID).outcome == "ok"
    port = server.port
    _stop(server)
    again = _start(port=port)
    try:
        assert not again.errors
        # and the same master carries on without a manual reconnect
        r = m.read_holding_registers(0x10, 1, device_id=SID)
        assert r.outcome == "ok", r
    finally:
        m.close()
        _stop(again)
    server.start = lambda: None                       # the fixture stops it again


def test_a_busy_port_is_reported(server):
    clash = sc.SlaveTcpServer(HOST, server.port, sc.SlaveStore.from_registers(MAP), SID)
    errors = []
    clash.error.connect(errors.append, DIRECT)
    clash.start()
    assert clash.wait(5000)
    assert errors and errors[0][0] == "slvTcpInUse"


def test_refused_and_unresolvable_hosts_are_told_apart():
    s = socket.socket()
    s.bind((HOST, 0))
    port = s.getsockname()[1]
    s.close()                                         # nothing listens there now
    m = mc.TcpMaster(HOST, port=port, timeout=0.5)
    assert m.connect() is False and m.last_error == "refused"
    bad = mc.TcpMaster("no-such-host.invalid", timeout=0.5)
    assert bad.connect() is False and bad.last_error == "resolve"
    assert mc.TcpMaster("", timeout=0.5).connect() is False


# ── RTU over TCP ──────────────────────────────────────────────────────
def test_rtu_over_tcp_reads_and_writes(rtu_server):
    m = _master(rtu_server, cls=mc.RtuOverTcpMaster)
    try:
        assert m.read_holding_registers(0x10, 2, device_id=SID).registers == [1234, 7]
        assert m.read_coils(0x00, 3, device_id=SID).bits == [1, 0, 1]
        assert m.write_register(0x11, 99, device_id=SID).outcome == "ok"
        assert m.write_registers(0x10, [5, 6], device_id=SID).outcome == "ok"
        assert rtu_server.store.read(0x10, 2) == [5, 6]
        r = m.read_holding_registers(0x300, 1, device_id=SID)
        assert r.outcome == "exception" and r.exception_code == sc.ILLEGAL_ADDRESS
        # RTU rules: another address gets no answer
        m.timeout = 0.2
        assert m.read_holding_registers(0x10, 1, device_id=3).outcome == "timeout"
    finally:
        m.close()


def test_rtu_over_tcp_frames_carry_a_crc(rtu_server):
    with socket.create_connection((HOST, rtu_server.port), timeout=2) as s:
        req = mc.with_crc(bytes.fromhex("0a 03 0010 0001"))
        s.sendall(req)
        assert _recv_exact(s, 7) == mc.with_crc(bytes.fromhex("0a 03 02 04d2"))


def test_socket_line_looks_like_a_serial_port(rtu_server):
    line = mc.SocketLine(socket.create_connection((HOST, rtu_server.port), timeout=2))
    try:
        assert line.in_waiting == 0
        line.write(mc.with_crc(bytes.fromhex("0a 03 0011 0001")))
        deadline = time.monotonic() + 2
        while line.in_waiting < 7 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert line.read(3) == bytes.fromhex("0a 03 02")
        assert line.read(100) == mc.with_crc(bytes.fromhex("0a 03 02 0007"))[3:]
        line.reset_input_buffer()
        assert line.is_open
    finally:
        line.close()
    assert not line.is_open


# ── the whole app path: ModbusCore over TCP ───────────────────────────
def test_modbus_core_polls_over_tcp(server):
    from core.modbus_core import ModbusCore
    core = ModbusCore()
    core.setup_connection({"transport": "tcp", "host": HOST, "tcp_port": server.port,
                           "timeout": 500}, SID)
    status = []
    core.status_changed.connect(lambda ok, text: status.append(ok))
    core.start()
    try:
        deadline = time.monotonic() + 5
        while not core.is_running and time.monotonic() < deadline:
            time.sleep(0.01)
        assert core.is_running, status
        assert core.request_op("read", 0x10, "SHORT", timeout=3) == 1234
        assert core.request_op("probe", 0x10, "SHORT", timeout=3) == "alive"
        assert core.request_op("probe", 0x300, "SHORT", timeout=3) == "exception"
        core.request_op("write", 0x11, "SHORT", value="42", timeout=3)
        assert server.store.read(0x11, 1) == [42]
        snap = core.stats.snapshot()
        assert snap["responses"] >= 3 and snap["timeouts"] == 0 and snap["crc"] == 0
    finally:
        core.stop()
        assert core.wait(5000)


def _recv_exact(sock, n, timeout=2.0):
    sock.settimeout(timeout)
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf
