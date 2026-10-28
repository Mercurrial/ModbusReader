"""Transport registry: factories, descriptions, the recent-links list."""
from core import modbus_client as mc
from core import transports as tr


def test_registry_shape():
    assert [t.transport_id for t in tr.TRANSPORTS] == ["serial", "tcp", "rtu_tcp", "sim"]
    assert tr.DEFAULT_ID == "serial"
    assert tr.get("nope").transport_id == "serial"   # unknown -> serial


def test_serial_factory():
    """Every shape of the parity / stop-bits / baud settings reaches the port."""
    settings = {"port": "COM7", "baudrate": "9600", "stopbits": "2",
                "parity": "Even"}
    made = tr.get("serial").create(settings, 0.2)
    assert isinstance(made, mc.RtuMaster)
    assert (made.port, made.baudrate, made.stopbits, made.parity) == ("COM7", 9600, 2.0, "E")
    assert (made.timeout, made.retries) == (0.2, 1)


def test_serial_describe():
    assert tr.get("serial").describe({"port": "COM5", "baudrate": "9600"}) == "COM5 (9600)"
    assert tr.get("serial").describe({}) == "COM1 (115200)"


def test_tcp_factory():
    c = tr.get("tcp").create({"host": "10.0.0.5", "tcp_port": "5020"}, 0.2)
    assert isinstance(c, mc.TcpMaster)
    assert (c.host, c.port, c.timeout, c.retries) == ("10.0.0.5", 5020, 0.2, 1)
    assert tr.get("tcp").describe({}) == "?:502"           # no host yet
    assert tr.get("tcp").describe({"host": " plc.local ", "tcp_port": "x"}) == "plc.local:502"
    assert tr.get("tcp").describe({"host": "fe80::1", "tcp_port": 1502}) == "[fe80::1]:1502"


def test_rtu_over_tcp_factory():
    c = tr.get("rtu_tcp").create({"host": "10.0.0.7", "tcp_port": 4001}, 0.5)
    assert isinstance(c, mc.RtuOverTcpMaster) and isinstance(c, mc.RtuMaster)
    assert (c.host, c.tcp_port, c.timeout, c.retries) == ("10.0.0.7", 4001, 0.5, 1)


def test_tcp_port_value_is_tolerant():
    assert [tr.tcp_port_value(v) for v in ("502", 1502.0, "0", "70000", None, "abc")]         == [502, 1502, 502, 502, 502, 502]


def test_summary_per_transport():
    assert tr.summary({"port": "COM3", "baudrate": "9600", "parity": "Even (E)"})         == "COM3 · 9600 · 8E1"
    assert tr.summary({"transport": "tcp", "host": "192.168.1.20"}) == "TCP · 192.168.1.20:502"
    assert tr.summary({"transport": "rtu_tcp", "host": "10.0.0.7", "tcp_port": 4001})         == "RTU/TCP · 10.0.0.7:4001"


def test_id_range_widens_for_tcp():
    assert tr.id_range({"transport": "serial"}) == (1, 247)
    assert tr.id_range({"transport": "tcp"}) == (0, 255)
    assert tr.id_range("rtu_tcp") == (0, 255)
    assert tr.is_network({"transport": "rtu_tcp"}) and not tr.is_network({})


def test_link_of_keeps_only_what_the_transport_uses():
    s = {"transport": "tcp", "host": "plc", "tcp_port": "502", "port": "COM3",
         "baudrate": "9600", "slave_id": "3", "theme": "Dark"}
    assert tr.link_of(s) == {"transport": "tcp", "host": "plc", "tcp_port": 502,
                             "slave_id": 3}
    s["transport"] = "serial"
    assert set(tr.link_of(s)) == {"transport", "port", "baudrate", "parity",
                                  "stopbits", "slave_id"}


def test_remember_moves_a_link_to_the_front_without_duplicates():
    a = {"transport": "tcp", "host": "10.0.0.1", "tcp_port": 502, "slave_id": 1}
    b = {"transport": "serial", "port": "COM3", "baudrate": "9600", "slave_id": 10}
    recent = tr.remember([], a)
    recent = tr.remember(recent, b)
    recent = tr.remember(recent, a, when=5.0)
    assert [r["transport"] for r in recent] == ["tcp", "serial"]
    assert recent[0]["used"] == 5.0
    junk = ["x", {"transport": "carrier-pigeon"}, None]
    assert tr.remember(junk, b) == [tr.link_of(b)]
    many = []
    for i in range(20):
        many = tr.remember(many, {"transport": "tcp", "host": f"10.0.0.{i}"})
    assert len(many) == tr.RECENT_MAX and many[0]["host"] == "10.0.0.19"
