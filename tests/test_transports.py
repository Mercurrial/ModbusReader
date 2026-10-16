"""Transport registry: serial factory parity + fallback semantics."""
from pymodbus.client import ModbusSerialClient, ModbusTcpClient

from core import transports as tr


def test_registry_shape():
    assert [t.transport_id for t in tr.TRANSPORTS] == ["serial", "tcp"]
    assert tr.DEFAULT_ID == "serial"
    assert tr.get("nope").transport_id == "serial"   # unknown -> serial


def test_serial_factory_parity():
    """Factory output must equal the historical inline construction."""
    settings = {"port": "COM7", "baudrate": "9600", "stopbits": "2",
                "parity": "Even"}
    made = tr.get("serial").create(settings, 0.2)
    ref = ModbusSerialClient(port="COM7", baudrate=9600, stopbits=2.0,
                             parity="E", timeout=0.2, retries=1)
    assert isinstance(made, ModbusSerialClient)
    assert made.comm_params == ref.comm_params
    assert made.retries == 1


def test_serial_describe():
    assert tr.get("serial").describe({"port": "COM5", "baudrate": "9600"}) == "COM5 (9600)"
    assert tr.get("serial").describe({}) == "COM1 (115200)"


def test_tcp_factory():
    c = tr.get("tcp").create({"host": "10.0.0.5", "tcp_port": "5020"}, 0.2)
    assert isinstance(c, ModbusTcpClient)
    assert c.comm_params.host == "10.0.0.5"
    assert int(c.comm_params.port) == 5020
    assert tr.get("tcp").describe({}) == "127.0.0.1:502"
