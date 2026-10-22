"""«Проверить связь» (core/linktest) and the network scan (core/netscan),
against the app's own TCP server on 127.0.0.1 — real sockets, no fakes."""
import socket
import time

import pytest
from PyQt6.QtCore import Qt

from core import linktest, netscan
from core import slave_core as sc

DIRECT = Qt.ConnectionType.DirectConnection
HOST = "127.0.0.1"
SID = 10
MAP = [{"addr": 0x10, "name": "Setpoint", "type": "SHORT", "rw": "RW", "default": "1234"},
       {"addr": 0x00, "name": "Temp", "type": "SHORT", "area": "input", "rw": "R",
        "default": "215"}]


def _server(framing="mbap", sid=SID):
    srv = sc.SlaveTcpServer(HOST, 0, sc.SlaveStore.from_registers(MAP), sid,
                            framing=framing)
    srv.start()
    assert srv.listening.wait(5)
    return srv


def _stop(srv):
    srv.request_stop()
    assert srv.wait(5000)


@pytest.fixture
def mbap():
    srv = _server()
    yield srv
    _stop(srv)


@pytest.fixture
def rtu():
    srv = _server("rtu")
    yield srv
    _stop(srv)


def _free_port() -> int:
    s = socket.socket()
    s.bind((HOST, 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _tcp(port, transport="tcp"):
    return {"transport": transport, "host": HOST, "tcp_port": port}


# ── the link test ─────────────────────────────────────────────────────
def test_a_device_that_answers(mbap):
    r = linktest.run(_tcp(mbap.port), SID, 0.5, "holding", 0x10)
    assert r.status == "ok" and r.alive and r.ms is not None


def test_an_exception_still_means_the_link_works(mbap):
    r = linktest.run(_tcp(mbap.port), SID, 0.5, "holding", 0x300)
    assert r.status == "exception" and r.alive and r.exception_code == 2


def test_the_probe_reads_the_maps_own_table(mbap):
    area, addr = linktest.probe_target([{"addr": 0, "area": "input", "type": "SHORT"}])
    assert (area, addr) == ("input", 0)
    assert linktest.run(_tcp(mbap.port), SID, 0.5, area, addr).status == "ok"
    assert linktest.probe_target([]) == ("holding", 0)


def test_a_silent_unit_id_gets_a_working_one_suggested(mbap):
    """The server answers its own id and 0 / 255 — asking unit 7 is silent,
    and the test names a unit id that does answer."""
    r = linktest.run(_tcp(mbap.port), 7, 0.3, "holding", 0x10)
    assert r.status == "silent" and r.suggest_unit in (1, 255, 0)
    assert r.suggest_unit != 1                           # id 1 is not served either


def test_rtu_over_tcp_behind_a_modbus_tcp_setting_is_recognised(rtu):
    """A converter in transparent mode, configured as Modbus TCP: the test
    finds out that RTU framing is what answers."""
    r = linktest.run(_tcp(rtu.port, "tcp"), SID, 0.3, "holding", 0x10)
    assert not r.alive
    assert r.suggest_transport == "rtu_tcp"


def test_modbus_tcp_behind_an_rtu_over_tcp_setting_is_recognised(mbap):
    r = linktest.run(_tcp(mbap.port, "rtu_tcp"), SID, 0.3, "holding", 0x10)
    assert not r.alive
    assert r.suggest_transport == "tcp"


def test_rtu_over_tcp_answers_as_itself(rtu):
    assert linktest.run(_tcp(rtu.port, "rtu_tcp"), SID, 0.5, "holding", 0x10).status == "ok"


def test_a_closed_port_is_refused_not_timed_out():
    r = linktest.run(_tcp(_free_port()), SID, 0.5)
    assert r.status == "open_fail" and r.kind == "refused"


def test_the_reasons_are_words_in_both_languages():
    from app.i18n import get_translator
    for lang in ("ru", "en"):
        t = get_translator(lang)
        for kind in linktest.WHY_KEYS:
            text = linktest.why(kind, {"port": "COM3", "host": "plc", "tcp_port": 502},
                                "os text", t)
            assert text and "{" not in text and text != linktest.WHY_KEYS[kind], (lang, kind)
        assert linktest.why("weird", {}, "os text", t) == "os text"
        for code in linktest.EXCEPTION_KEYS:
            assert linktest.exception_name(code, t) != linktest.EXCEPTION_KEYS[code]
    assert linktest.exception_name(0x42, get_translator("en")) == "0x42"


def test_link_error_kinds():
    from core.modbus_client import link_error_kind
    assert link_error_kind(ConnectionRefusedError()) == "refused"
    assert link_error_kind(TimeoutError()) == "timeout"
    assert link_error_kind(socket.gaierror()) == "resolve"
    assert link_error_kind(ConnectionResetError()) == "closed"
    unreach = OSError()
    unreach.winerror = 10065
    assert link_error_kind(unreach) == "unreachable"
    assert link_error_kind(Exception(
        "could not open port 'COM3': PermissionError(13, 'Access is denied.')")) == "busy"
    assert link_error_kind(Exception(
        "could not open port 'COM9': FileNotFoundError(2, 'The system cannot find "
        "the file specified.')")) == "missing"
    assert link_error_kind(Exception(
        "[Errno 13] could not open port /dev/ttyUSB0: [Errno 13] Permission denied")) == "denied"
    assert link_error_kind(Exception("something else")) == "other"


# ── the network scan ──────────────────────────────────────────────────
def test_hosts_between():
    assert netscan.hosts_between("10.0.0.3", "10.0.0.1") == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]
    assert len(netscan.hosts_between("10.0.0.0", "10.0.3.255")) == netscan.MAX_HOSTS
    with pytest.raises(ValueError):
        netscan.hosts_between("10.0.0.0", "10.0.4.0")
    with pytest.raises(ValueError):
        netscan.hosts_between("10.0.0.300", "10.0.0.1")
    assert netscan.subnet_range("192.168.7.42") == ("192.168.7.1", "192.168.7.254")


def test_real_lans_are_preferred_over_virtual_adapters():
    order = sorted(["192.168.56.1", "172.19.0.1", "10.1.2.3", "192.168.1.5"],
                   key=netscan._lan_rank)
    assert order == ["192.168.1.5", "10.1.2.3", "172.19.0.1", "192.168.56.1"]
    for ip in netscan.local_ipv4():
        assert not ip.startswith("127.") and not ip.startswith("169.254.")


def test_probe_tells_modbus_from_an_open_port(mbap):
    hit = netscan.probe(HOST, mbap.port)
    assert hit["state"] == "modbus" and hit["unit"] in (1, 255, 0) and hit["ms"] > 0
    assert netscan.probe(HOST, _free_port(), connect_s=0.3) is None
    # a TCP server that is not Modbus: accepts and says nothing
    quiet = socket.socket()
    quiet.bind((HOST, 0))
    quiet.listen(1)
    try:
        hit = netscan.probe(HOST, quiet.getsockname()[1], answer_s=0.2)
        assert hit["state"] == "open" and hit["unit"] is None
    finally:
        quiet.close()


def test_the_scan_worker_reports_what_answers(mbap):
    w = netscan.NetScanWorker(["127.0.0.1", "127.0.0.2"], mbap.port, answer_s=0.3)
    found, done = [], []
    w.found.connect(found.append, DIRECT)
    w.finished_scan.connect(lambda *a: done.append(a), DIRECT)
    w.start()
    assert w.wait(15000)
    assert [h["ip"] for h in found] == ["127.0.0.1"]
    assert done and done[0][:2] == (1, 2)


def test_the_scan_stops_when_asked():
    # loopback only: a test must not knock on addresses of a real network
    w = netscan.NetScanWorker(netscan.hosts_between("127.0.1.1", "127.0.1.200"), 502)
    w.start()
    time.sleep(0.2)
    t0 = time.monotonic()
    w.request_stop()
    assert w.wait(10000)
    assert time.monotonic() - t0 < 5
