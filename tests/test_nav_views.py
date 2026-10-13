"""Nav switcher (4 views), active-button highlight, Connect state, Ctrl+F.

The toolbar renders one nav button per commands.VIEWS entry; the active view
(or open overlay) carries [active="true"]. The Connect button flips label,
icon colour and [connected] QSS state. Every registered shortcut must have a
handler — the registry and the dispatcher may not drift apart.
"""
import pytest
from PyQt6.QtWidgets import QApplication

import commands
from settings_manager import DEFAULT_SETTINGS


@pytest.fixture()
def win():
    import gui_main
    w = gui_main.ModernScadaApp()
    yield w
    w.close()
    QApplication.processEvents()


def _pump():
    for _ in range(3):
        QApplication.processEvents()


def test_every_shortcut_has_a_handler(win):
    handlers = win._command_handler_map()
    missing = [c.cmd_id for c in commands.SHORTCUTS if c.cmd_id not in handlers]
    assert missing == []


def test_toolbar_renders_all_view_buttons(win):
    assert set(win.main_toolbar._view_btns) == {c.cmd_id for c in commands.VIEWS}


def test_switch_views_and_highlight(win):
    tb = win.main_toolbar
    win._dispatch_command("view_console")
    _pump()
    assert win.content_stack.currentWidget() is win.console_view
    assert tb._view_btns["view_console"].property("active") == "true"
    assert tb._view_btns["view_table"].property("active") == "false"

    win._dispatch_command("view_slave")
    _pump()
    assert win.content_stack.currentWidget() is win.slave_view

    win._dispatch_command("view_table")
    _pump()
    assert win.content_stack.currentWidget() is win.main_view
    assert tb._view_btns["view_table"].property("active") == "true"


def test_settings_overlay_highlights_and_restores(win):
    tb = win.main_toolbar
    win._dispatch_command("view_console")
    _pump()
    win._dispatch_command("settings")
    _pump()
    assert win._overlay_page is not None
    assert tb._cmd_btns["settings"].property("active") == "true"
    win._overlay_page.reject()                        # pristine -> closes
    _pump()
    assert win._overlay_page is None
    assert win.content_stack.currentWidget() is win.console_view
    assert tb._view_btns["view_console"].property("active") == "true"


def test_map_editor_opens_as_overlay(win):
    """Ctrl+2 / profile menu opens the editor over the MAP view — the map nav
    button stays highlighted (the editor belongs to that view)."""
    from profile_editor import ProfileEditorDialog
    win._dispatch_command("view_console")
    _pump()
    win._dispatch_command("view_map")
    _pump()
    assert isinstance(win._overlay_page, ProfileEditorDialog)
    assert win.main_toolbar._view_btns["view_table"].property("active") == "true"
    win._overlay_page.reject()
    _pump()
    assert win._overlay_page is None


def test_profile_dropdown_lives_in_head_bar(win):
    # Moved out of the top bar into the map head bar (next to search).
    assert not hasattr(win.main_toolbar, "btn_profile")
    assert win.btn_profile is not None
    assert win.btn_profile.parent() is not None
    assert "view_map" not in win.main_toolbar._view_btns   # hidden command now


def test_connect_button_state(win):
    tb = win.main_toolbar
    tb.set_connect_state(True)
    assert tb.btn_connect.property("connected") == "true"
    tb.set_connect_state(False)
    assert tb.btn_connect.property("connected") == "false"


def test_console_view_receives_log_lines(win):
    win._log("TX", "01 03 00 00 00 02 C4 0B")
    assert "01 03 00 00 00 02" in win.console_view.view.toPlainText()


def test_ctrl_f_focuses_search_from_other_view(win):
    win._dispatch_command("view_slave")
    _pump()
    win._dispatch_command("search")
    _pump()
    assert win.content_stack.currentWidget() is win.main_view


def test_project_save_and_reopen_roundtrip(win, tmp_path):
    """A project bundles connection + register map + every dashboard. Saving
    and re-applying must restore all three."""
    import formats
    regs = [{"addr": 0x10, "name": "Пуск", "type": "SHORT", "rw": "RW"}]
    win.profile_data = regs
    win.register_table.populate(regs)
    win.dash_view.load_boards([
        {"name": "Обзор",
         "widgets": [{"uid": "w1", "kind": "value", "reg_id": "0x0010",
                      "x": 10, "y": 10}], "links": []},
        {"name": "Наладка",
         "widgets": [{"uid": "t1", "kind": "timer", "x": 0, "y": 0},
                     {"uid": "b1", "kind": "button", "reg_id": "0x0010",
                      "x": 200, "y": 0}],
         "links": [{"from": "t1", "to": "b1"}]},
    ])
    win.settings["port"] = "COM9"
    path = str(tmp_path / "stend.mbproj")
    formats.dump_project(path, "Стенд", win.settings, win.profile_data,
                         win.dash_view.all_boards())

    # wipe the workspace, then reopen the project
    win.profile_data = []
    win.register_table.populate([])
    win.dash_view.load_boards([{"name": "пусто", "widgets": [], "links": []}])
    win.settings["port"] = "COM1"

    win.apply_project(formats.load_project(path))
    _pump()
    assert win.settings["port"] == "COM9"                  # connection back
    assert [r["name"] for r in win.profile_data] == ["Пуск"]   # map back
    assert [b["name"] for b in win.dash_view.boards] == ["Обзор", "Наладка"]
    win.dash_view.switch_board(1)
    assert set(win.dash_view.cards) == {"t1", "b1"}        # widgets back
    assert win.dash_view.graph.as_list() == [{"from": "t1", "to": "b1"}]


def test_version_is_at_least_1_1():
    from version import APP_VERSION
    major, minor = (int(x) for x in APP_VERSION.split(".")[:2])
    assert (major, minor) >= (1, 1)


def _clear_trends(win):
    # The window may have restored the REAL user session (load_last) — reset.
    for rid in list(win.trends_manager.active_trends):
        win.trends_manager.remove_trend(rid)


def test_session_state_saved_on_close(win):
    _clear_trends(win)
    win.register_table.populate(
        [{"addr": 1, "name": "R1", "type": "SHORT", "rw": "RW"}])
    win._add_to_trend("0x0001", "R1")
    win._dispatch_command("view_console")
    _pump()
    win._save_window_geometry()
    assert win.settings["last_view"] == "view_console"
    assert win.settings["open_trends"] == [
        {"id": "0x0001", "name": "R1", "unit": "", "win": 30}]


def test_session_state_restored(win):
    _clear_trends(win)
    win.register_table.populate(
        [{"addr": 1, "name": "R1", "type": "SHORT", "rw": "RW"}])
    win.settings["open_trends"] = [
        {"id": "0x0001", "name": "R1", "unit": "V", "win": 120},
        {"id": "0x0099", "name": "Gone", "unit": "", "win": 30},  # not in profile
    ]
    win.settings["last_view"] = "view_console"
    win._restore_session_state()
    _pump()
    assert set(win.trends_manager.active_trends) == {"0x0001"}   # dead one skipped
    assert win.trends_manager.active_trends["0x0001"].window_seconds == 120
    assert win.content_stack.currentWidget() is win.console_view
