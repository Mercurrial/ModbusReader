"""The demo project's made-up device (core/simulator.py, transport "sim"):
the model, the device on the "wire", and the rule that only the demo
project has it."""
import json
import os
import time

import pytest
from PyQt6.QtWidgets import QApplication

from core import datatypes, formats, linktest, simulator, transports
from core.simulator import ThermoModel, MODE_RUN, MODE_FAULT, ERR_DOOR

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "examples", "demo.mbproj")


def _regs():
    return formats.load_project(DEMO)["profile"]["registers"]


@pytest.fixture()
def device():
    dev = simulator.attach(_regs())
    yield dev
    simulator.detach()


# ── the model ─────────────────────────────────────────────────────────
def test_the_model_holds_and_follows_the_setpoint():
    m = ThermoModel(seed=1)
    m.next_door = 1e9                       # no door for this one
    m.step(120, 25.0, MODE_RUN, True, False, 30)
    assert abs(m.temp - 25.0) < 0.6
    m.step(60, 30.0, MODE_RUN, True, False, 30)
    assert abs(m.temp - 30.0) < 0.6


def test_the_fan_costs_heater_power_and_stop_cools_down():
    m = ThermoModel(seed=1)
    m.next_door = 1e9
    m.step(120, 25.0, MODE_RUN, True, False, 30)
    calm = m.power
    m.step(120, 25.0, MODE_RUN, True, True, 30)
    assert m.power > calm + 15
    m.step(60, 25.0, 0, True, False, 30)
    assert m.power == 0 and m.temp < 23.0


def test_a_door_left_open_raises_the_alarm():
    m = ThermoModel(seed=1)
    m.next_door = 1.0
    mode = m.step(20, 25.0, MODE_RUN, True, False, alarm_delay=3)
    assert mode == MODE_FAULT and m.error == ERR_DOOR


# ── the device on the wire ────────────────────────────────────────────
def test_the_device_answers_like_one(device):
    m = simulator.SimMaster(timeout=0.05)
    assert m.connect()
    res = m.read_holding_registers(0, 11, device_id=1)
    assert res.outcome == "ok" and len(res.registers) == 11
    temp = float(datatypes.read_to_str("FLOAT", res.registers[0:2]))
    assert 15.0 < temp < 35.0
    assert m.read_input_registers(0, 2, device_id=1).registers[1] in range(4, 21)
    assert m.read_holding_registers(0, 1, device_id=5).outcome == "timeout"   # not its address
    bad = m.read_holding_registers(100, 1, device_id=1)
    assert bad.outcome == "exception" and bad.exception_code == 2
    assert m.write_registers(2, datatypes.encode("FLOAT", "31"), device_id=1).outcome == "ok"
    sp = m.read_holding_registers(2, 2, device_id=1).registers
    assert float(datatypes.read_to_str("FLOAT", sp)) == 31.0


def test_mode_run_acknowledges_a_fault(device):
    m = simulator.SimMaster(timeout=0.05)
    m.connect()
    device.model.error = ERR_DOOR
    m.write_register(4, MODE_FAULT, device_id=1)
    m.write_register(4, MODE_RUN, device_id=1)
    assert m.read_holding_registers(9, 1, device_id=1).registers == [0]


def test_no_demo_project_no_device():
    simulator.detach()
    m = simulator.SimMaster()
    assert not m.connect() and m.last_error == "sim_off"
    report = linktest.run({"transport": "sim", "slave_id": 1}, 1, 0.1)
    assert report.status == "open_fail" and report.kind == "sim_off"


def test_the_link_test_works_on_the_demo_device(device):
    report = linktest.run({"transport": "sim", "slave_id": 1}, 1, 0.2)
    assert report.status == "ok"


def test_the_demo_device_is_never_a_recent_link():
    recent = [{"transport": "tcp", "host": "10.0.0.5", "tcp_port": 502, "slave_id": 1}]
    out = transports.remember(recent, {"transport": "sim", "slave_id": 1})
    assert out == recent
    out = transports.remember(recent + [{"transport": "sim", "slave_id": 1}],
                              {"transport": "serial", "port": "COM3", "slave_id": 1})
    assert all(i["transport"] != "sim" for i in out)
    assert not transports.is_network({"transport": "sim"})


# ── the project format ───────────────────────────────────────────────
def test_only_a_marked_project_carries_the_simulation(tmp_path):
    demo, plain = tmp_path / "demo.mbproj", tmp_path / "plain.mbproj"
    formats.dump_project(str(demo), "d", {}, [], simulation="thermo")
    formats.dump_project(str(plain), "p", {}, [])
    assert formats.project_simulation(str(demo)) == "thermo"
    assert formats.project_simulation(str(plain)) == ""
    assert formats.project_simulation(str(tmp_path / "missing.mbproj")) == ""
    for name in ("demo.mbproj", "demo_en.mbproj"):
        doc = json.load(open(os.path.join(ROOT, "examples", name), encoding="utf-8"))
        assert doc["simulation"] == "thermo" and doc["connection"]["transport"] == "sim"


# ── the window: only the demo project has it ────────────────────────
@pytest.fixture()
def win(monkeypatch, tmp_path):
    from app import projects
    from gui import main_window as gui_main
    monkeypatch.setattr(projects, "_cache", {"dir": str(tmp_path / "Projects")})
    w = gui_main.ModernScadaApp()
    yield w
    core = w.modbus_core
    if core.is_running or core.isRunning():
        core.stop()
        core.wait(3000)
    simulator.detach()
    w.close()
    w.deleteLater()
    QApplication.processEvents()


def _pump_until(cond, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_the_demo_comes_alive_and_another_map_ends_it(win, tmp_path):
    from gui import register_table as rt
    win._open_demo()
    assert win._sim_kind == "thermo" and simulator.current() is not None
    assert win.settings["transport"] == "sim"
    assert win.conn_card.seg._buttons["sim"].isVisibleTo(win.conn_card)
    assert win.main_toolbar.btn_link.text().strip().startswith(win.t("simChip"))

    win._toggle_connection()
    table = win.register_table
    row = table.addr_to_row[0]
    assert _pump_until(lambda: table.item(row, rt.COL_CURRENT).text() not in ("", "—"), 5)
    assert win.modbus_core.stats.snapshot()["ok"] > 0

    m = tmp_path / "map.json"
    m.write_text(json.dumps([{"addr": 1, "name": "X", "type": "SHORT"}]), encoding="utf-8")
    win._load_profile(str(m))
    assert simulator.current() is None and win._sim_kind == ""
    assert win.settings["transport"] == "serial"
    assert not win.modbus_core.is_running
    assert not win.conn_card.seg._buttons["sim"].isVisibleTo(win.conn_card)


def test_saving_keeps_the_mark_and_a_copy_loses_it(win, tmp_path):
    win._open_demo()
    demo = win.project_path
    win._save_project()
    assert formats.project_simulation(demo) == "thermo"
    copy = str(tmp_path / "mine.mbproj")
    win._write_project(copy, "mine")
    assert formats.project_simulation(copy) == ""
    assert json.load(open(copy, encoding="utf-8"))["connection"]["transport"] == "serial"
    assert win._sim_kind == "" and win.settings["transport"] == "serial"
