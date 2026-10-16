"""Integration: the whole window builds; theme/lang round-trips; overlays open;
profile loading normalizes and validates."""
import json

import pytest

from gui import main_window as gui_main
from app.app_context import AppContext
from app.settings_manager import DEFAULT_SETTINGS
from gui.map_editor import ProfileEditorDialog


@pytest.fixture()
def window():
    w = gui_main.ModernScadaApp()
    yield w
    w.close()


def test_window_builds_on_context(window):
    assert isinstance(window.ctx, AppContext)
    assert window.settings is window.ctx.settings
    assert window.modbus_core is window.ctx.core


def test_theme_and_lang_roundtrip(window):
    window._on_theme_changed("Light")
    window._on_theme_changed("Dark")
    window._on_lang_changed("en")
    assert window.lang == "en"
    assert window.register_table.horizontalHeaderItem(1).text() == window.t("address")
    window._on_lang_changed("ru")
    assert window.lang == "ru"


def test_overlays_open_and_close(window):
    window._create_config()
    assert window._overlay_page is not None
    window._close_overlay()
    assert window._overlay_page is None
    window._open_settings()
    assert window._overlay_page is not None
    window._close_overlay()


def test_load_profile_normalizes_and_validates(window, tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps([
        {"addr": "0x10", "name": "A", "type": "FLOAT", "rw": "R", "length": 2},
        {"addr": 0x11, "name": "A", "type": "SHORT", "rw": "R", "length": 1},
    ]), encoding="utf-8")
    window._load_profile(str(p))
    # str addr coerced for the poll loop / macros
    assert all(isinstance(r["addr"], int) for r in window.profile_data)
    # overlapping spans + duplicate names surfaced in the log
    logtxt = window.log_panel.view.toPlainText()
    assert window.t("addrOverlaps") in logtxt
    assert window.t("dupNames") in logtxt


def test_data_path_updates_cell(window):
    prof = [{"addr": 0x10, "name": "T", "type": "SHORT", "rw": "RW", "length": 1}]
    window.profile_data = prof
    window.register_table.populate(prof)
    window._on_data_updated(0x10, "42")
    row = window.register_table.addr_to_row[0x10]
    assert window.register_table.item(row, 5).text() == "42"


def test_load_last_toggle_respected(tmp_path, monkeypatch):
    p = tmp_path / "last.json"
    p.write_text(json.dumps(
        [{"addr": 1, "name": "R", "type": "SHORT", "rw": "R", "length": 1}]),
        encoding="utf-8")
    base = dict(DEFAULT_SETTINGS)
    base["last_profile_path"] = str(p)

    monkeypatch.setattr(gui_main, "load_settings",
                        lambda: {**base, "load_last": False})
    w = gui_main.ModernScadaApp()
    assert w.profile_data == []                    # toggle off: NOT loaded
    w.close()

    monkeypatch.setattr(gui_main, "load_settings",
                        lambda: {**base, "load_last": True})
    w2 = gui_main.ModernScadaApp()
    assert len(w2.profile_data) == 1               # toggle on: loaded
    w2.close()


def test_editor_validation_badge():
    ctx = AppContext(dict(DEFAULT_SETTINGS))
    dirty = [{"addr": 0, "name": "A", "type": "FLOAT"},
             {"addr": 1, "name": "A", "type": "SHORT"}]
    ed = ProfileEditorDialog(None, dirty, ctx)
    assert ed.lbl_stats_warn.isVisibleTo(ed)
    assert ed.ico_warn.isVisibleTo(ed)                 # SVG warning icon shown
    assert ed.t("addrOverlaps") in ed.lbl_stats_warn.text()
    ed.close()
    clean = [{"addr": 0, "name": "A", "type": "SHORT"},
             {"addr": 1, "name": "B", "type": "SHORT"}]
    ed2 = ProfileEditorDialog(None, clean, ctx)
    assert not ed2.lbl_stats_warn.isVisibleTo(ed2)
    ed2.close()
