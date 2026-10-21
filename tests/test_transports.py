"""Transport registry: serial factory parity + fallback semantics."""
from core import modbus_client as mc
from core import transports as tr


def test_registry_shape():
    assert [t.transport_id for t in tr.TRANSPORTS] == ["serial", "tcp"]
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
    assert tr.get("tcp").describe({}) == "127.0.0.1:502"
