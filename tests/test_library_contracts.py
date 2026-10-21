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


# ── Modbus is the app's own (core/modbus_client) ──────────────────────
def test_pymodbus_is_gone_for_good():
    """The protocol is implemented in core/modbus_client; the library that
    once did it must not creep back in — not as an import, not as a pin, not
    in a build spec."""
    import glob
    offenders = []
    for pattern in ("main.py", "app/*.py", "core/*.py", "gui/*.py", "tools/*.py", "*.spec"):
        for path in glob.glob(os.path.join(ROOT, pattern)):
            with open(path, encoding="utf-8") as f:
                text = f.read()
            if re.search(r"^\s*(import|from)\s+pymodbus|collect_submodules\(.pymodbus", text, re.M):
                offenders.append(os.path.relpath(path, ROOT))
    assert offenders == []
    assert "pymodbus" not in _pins("requirements-dev.txt")


# ── pyqtgraph ────────────────────────────────────────────────────────
def test_pyqtgraph_api_used_by_the_trends():
    import pyqtgraph as pg
    for name in ("PlotWidget", "DateAxisItem", "ScatterPlotItem", "mkPen", "mkBrush",
                 "setConfigOptions", "setConfigOption"):
        assert hasattr(pg, name), name


# ── pyserial ─────────────────────────────────────────────────────────
def test_pyserial_serial_has_what_the_rtu_master_uses():
    """core/modbus_client.RtuMaster opens serial.Serial(port, baudrate,
    bytesize, parity, stopbits, timeout, write_timeout) and uses in_waiting,
    read, write, flush, reset_input_buffer, close and is_open."""
    import serial
    # serial.Serial is the platform class (*args); the parameters are SerialBase's.
    params = inspect.signature(serial.SerialBase.__init__).parameters
    for name in ("port", "baudrate", "bytesize", "parity", "stopbits", "timeout",
                 "write_timeout"):
        assert name in params, name
    for name in ("in_waiting", "read", "write", "flush", "reset_input_buffer", "close"):
        assert hasattr(serial.Serial, name), name    # on the class: in_waiting is a property
    assert serial.Serial().is_open is False         # no port given: nothing is opened
    assert (serial.PARITY_NONE, serial.PARITY_EVEN, serial.PARITY_ODD) == ("N", "E", "O")


def test_pyserial_lists_ports():
    """Settings → port list (app/settings_schema)."""
    from serial.tools import list_ports
    assert callable(list_ports.comports)
