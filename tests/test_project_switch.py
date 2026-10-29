"""Opening another project hides the old one's values: the old link stops,
the watch window and the charts start empty (values jumped otherwise)."""
import pytest
from PyQt6.QtWidgets import QApplication

from core import formats

REGS_A = [{"addr": 1, "name": "A", "type": "SHORT", "rw": "R"},
          {"addr": 2, "name": "B", "type": "SHORT", "rw": "R"}]
REGS_B = [{"addr": 1, "name": "A2", "type": "SHORT", "rw": "R"}]


@pytest.fixture()
def win():
    from gui import main_window as gui_main
    w = gui_main.ModernScadaApp()
    w._set_profile([dict(r) for r in REGS_A], "")
    yield w
    w.watch_window.hide()
    w.close()
    w.deleteLater()
    QApplication.processEvents()


def _project(settings_update):
    from app.settings_manager import DEFAULT_SETTINGS
    s = dict(DEFAULT_SETTINGS)
    s.update(settings_update)
    return formats.migrate_project(formats.make_project("B", s, REGS_B))


def _load_values(win):
    win._add_to_trend("0x0001", "A")
    win._add_to_trend("0x0002", "B")
    win.watch_window.add(1)
    win._on_data_updated(1, "42")
    win._on_data_updated(2, "7")
    QApplication.processEvents()


def test_another_link_stops_polling_and_clears_values(win, monkeypatch):
    _load_values(win)
    stopped = []
    core = win.modbus_core
    monkeypatch.setattr(core, "is_running", True)
    monkeypatch.setattr(core, "stop", lambda: stopped.append(True))
    monkeypatch.setattr(core, "wait", lambda *_a: True)
    win.apply_project(_project({"port": "COM42", "slave_id": 77}), persist=False)
    assert stopped
    row = win.watch_window._rows[0]
    assert row.text is None and row.vmax is None
    assert list(win.trends_manager.active_trends) == ["0x0001"]   # B is not in the map
    assert not win.trends_manager.active_trends["0x0001"]._vs     # history gone


def test_the_same_link_keeps_polling(win, monkeypatch):
    stopped = []
    core = win.modbus_core
    monkeypatch.setattr(core, "is_running", True)
    monkeypatch.setattr(core, "stop", lambda: stopped.append(True))
    from core import transports
    same = {k: win.settings.get(k) for k in transports.LINK_FIELDS}
    win.apply_project(_project(same), persist=False)
    assert not stopped
