"""What the code relies on INSIDE its libraries — one test per assumption.

The libraries are pinned (requirements.txt); a weekly Dependabot pull request
proposes newer versions and CI runs the suite on them. These tests are the
ones meant to fail on such a pull request, loudly and with the place to fix
named, when an update changes something the app quietly depends on. pymodbus
3.16 already did: its RTU framer started swallowing bad-CRC frames, and the
line statistics stopped counting CRC errors without any test noticing.
"""
import inspect
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pins(name: str) -> dict:
    import sys
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import build_installer
    return build_installer.pins(os.path.join(ROOT, name))


# ── the pins themselves ───────────────────────────────────────────────
def test_every_runtime_dependency_is_pinned_exactly():
    with open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8") as f:
        lines = [l.split("#", 1)[0].strip() for l in f]
    reqs = [l for l in lines if l and not l.startswith("-")]
    assert reqs and all(re.fullmatch(r"[A-Za-z0-9_.-]+==[\w.]+", r) for r in reqs), reqs


def test_the_tests_run_on_the_pinned_versions():
    """Tests on other versions than the ones shipped prove nothing about the
    release. Fix: python -m pip install -r requirements-dev.txt"""
    import sys
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import build_installer
    assert build_installer.environment_drift(_pins("requirements-dev.txt")) == []


def test_the_build_refuses_a_drifted_environment():
    import sys
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import build_installer
    drift = build_installer.environment_drift({"pymodbus": "0.0.1", "no-such-pkg": "1.0"})
    assert any(d.startswith("pymodbus ") and "(pinned 0.0.1)" in d for d in drift)
    assert "no-such-pkg missing (pinned 1.0)" in drift


# ── pymodbus ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("method", ["read_holding_registers", "read_input_registers",
                                    "read_coils", "read_discrete_inputs",
                                    "write_register", "write_coil"])
def test_pymodbus_takes_the_device_address_under_a_known_name(method):
    """core/modbus_core tries device_id=, then slave=, then unit= (pymodbus
    renamed it twice). A fourth name would make every request fail."""
    from pymodbus.client import ModbusSerialClient
    params = inspect.signature(getattr(ModbusSerialClient, method)).parameters
    assert {"device_id", "slave", "unit"} & set(params), (method, list(params))
    assert "address" in params


def test_pymodbus_serial_client_exposes_its_port_as_socket():
    """The raw-frame console writes straight to client.socket (a pyserial
    Serial once connected) — core/modbus_core._execute_raw."""
    from core import transports
    client = transports.get("serial").create({"port": "COM99"}, 0.5)
    assert hasattr(client, "socket")


def test_pymodbus_rtu_framer_internals_used_by_the_crc_probe():
    """core/linestats.install_crc_probe wraps FramerRTU.decode and re-checks
    a frame with decoder.lookupPduClass → calculateRtuFrameSize → check_CRC.
    decode must return (used, device_id, tid, payload)."""
    from core import transports
    from pymodbus.framer import FramerRTU
    client = transports.get("serial").create({"port": "COM99"}, 0.5)
    framer = client.framer
    assert isinstance(framer, FramerRTU)
    assert callable(framer.decode) and callable(framer.check_CRC)
    assert callable(framer.decoder.lookupPduClass)
    result = framer.decode(b"\x0a\x03")                    # too short: nothing yet
    assert isinstance(result, tuple) and len(result) == 4 and not result[3]


def test_pymodbus_io_exception_is_where_the_core_imports_it():
    from pymodbus.exceptions import ModbusIOException      # core/modbus_core
    assert issubclass(ModbusIOException, Exception)


# ── pyqtgraph ────────────────────────────────────────────────────────
def test_pyqtgraph_api_used_by_the_trends():
    import pyqtgraph as pg
    for name in ("PlotWidget", "DateAxisItem", "ScatterPlotItem", "mkPen", "mkBrush",
                 "setConfigOptions", "setConfigOption"):
        assert hasattr(pg, name), name


# ── pyserial ─────────────────────────────────────────────────────────
def test_pyserial_lists_ports():
    """Settings → port list (app/settings_schema)."""
    from serial.tools import list_ports
    assert callable(list_ports.comports)
