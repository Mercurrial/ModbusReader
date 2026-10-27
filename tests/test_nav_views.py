"""Navigation (2.2: the left rail), active highlight, Connect state, Ctrl+F.

The rail renders one entry per commands.VIEWS page, every one visible, in its
group; the active page (or open overlay) carries [active="true"] and the
header shows its title. The Connect button flips label, icon colour and
[connected] QSS state. Every registered shortcut must have a handler — the
registry and the dispatcher may not drift apart.
"""
import pytest
from PyQt6.QtWidgets import QApplication

from app import commands
from app.settings_manager import DEFAULT_SETTINGS


@pytest.fixture()
def win():
    from gui import main_window as gui_main
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


def test_rail_renders_every_page_and_no_overflow(win):
    rail = win.nav_rail
    assert set(rail._view_btns) == {c.cmd_id for c in commands.VIEWS}
    assert all(b.isVisibleTo(rail) for b in rail._view_btns.values())
    assert {c.group for c in commands.VIEWS} == {g for g, _ in commands.GROUPS}
    assert not hasattr(win.main_toolbar, "btn_more")       # no "⋯" any more
    assert rail._cmd_btns["help"].isVisibleTo(rail)
    # Settings sit in the header's top-right corner, not in the rail.
    assert "settings" not in rail._cmd_btns
    tb = win.main_toolbar
    assert tb._cmd_btns["settings"] is tb.btn_settings
    lo = tb.layout()
    assert lo.indexOf(tb.btn_settings) == max(
        lo.indexOf(w) for w in (tb.btn_theme, tb.btn_layout, tb.btn_settings))


def test_macros_is_a_page(win):
    win._dispatch_command("view_macros")
    _pump()
    assert win.content_stack.currentWidget() is win.macro_view
    assert not win.macro_view.isWindow()
    assert win.nav_rail._view_btns["view_macros"].property("active") == "true"
    assert win.main_toolbar.lbl_title.text() == win.t("macros")


def test_rail_collapses_and_remembers(win):
    from gui.rail import COLLAPSED_W, EXPANDED_W
    rail = win.nav_rail
    rail.set_collapsed(True)
    assert rail.width() == COLLAPSED_W and win.settings["rail_collapsed"] is True
    assert rail._view_btns["view_table"].text() == ""
    assert win.t("registerMap") in rail._view_btns["view_table"].toolTip()
    rail.set_collapsed(False)
    assert rail.width() == EXPANDED_W and win.settings["rail_collapsed"] is False


def _menu_action(menu, text):
    """The action called *text* in *menu* or its submenus."""
    for act in menu.actions():
        if act.text() == text:
            return act
        if act.menu() is not None:
            hit = _menu_action(act.menu(), text)
            if hit is not None:
                return hit
    return None


def test_rail_moves_left_right_top(win):
    from gui.rail import TOP_H, EXPANDED_W
    rail = win.nav_rail
    _menu_action(rail.build_menu(), win.t("railTop")).trigger()
    _pump()
    assert win.settings["rail_position"] == "top" and rail.position == "top"
    assert win._shell.indexOf(rail) == 0                     # above everything
    assert rail.height() == TOP_H
    assert not any(cap.isVisibleTo(rail) for cap, _k in rail._captions)
    assert not rail.btn_collapse.isVisibleTo(rail)
    # one separator between the two groups, none before the first
    seps = [sep.isVisibleTo(rail) for _c, sep, _ids in rail._groups]
    assert seps == [False, True]
    _menu_action(rail.build_menu(), win.t("railRight")).trigger()
    _pump()
    assert win.settings["rail_position"] == "right"
    row = win._shell_row
    assert row.indexOf(rail) == row.count() - 1             # after the work area
    assert rail.width() == EXPANDED_W
    assert all(cap.isVisibleTo(rail) for cap, _k in rail._captions)
    _menu_action(rail.build_menu(), win.t("railLeft")).trigger()
    _pump()
    assert row.indexOf(rail) == 0 and win._shell.indexOf(rail) == -1


def test_rail_bar_keeps_the_current_label_when_narrow(win):
    rail = win.nav_rail
    rail.set_position("top")
    rail.resize(640, rail.height())             # a hidden window defers the
    rail._fit_bar()                             # resize event: fit by hand
    assert rail._compact
    assert rail._view_btns["view_table"].text().strip() == win.t("registerMap")
    assert rail._view_btns["view_console"].text() == ""
    win._dispatch_command("view_console")
    _pump()
    assert rail._view_btns["view_console"].text().strip() == win.t("viewConsole")
    assert rail._view_btns["view_table"].text() == ""
    rail.resize(4000, rail.height())
    rail._fit_bar()
    assert not rail._compact
    assert all(b.text() for b in rail._view_btns.values())


def test_rail_hides_pages_but_never_the_map(win):
    rail = win.nav_rail
    _menu_action(rail.build_menu("view_sniffer"),
                 win.t("railHidePage").format(name=win.t("viewSniffer"))).trigger()
    assert not rail._view_btns["view_sniffer"].isVisibleTo(rail)
    assert win.settings["rail_hidden"] == ["view_sniffer"]
    menu = rail.build_menu("view_table")                    # no «remove» for the map
    assert _menu_action(menu, win.t("railHidePage").format(
        name=win.t("registerMap"))) is None
    assert not _menu_action(menu, win.t("registerMap")).isEnabled()
    win._dispatch_command("view_sniffer")                   # still reachable
    _pump()
    assert win.content_stack.currentWidget() is win.sniffer_view
    _menu_action(rail.build_menu(), win.t("railShowAll")).trigger()
    assert rail._view_btns["view_sniffer"].isVisibleTo(rail)
    assert win.settings["rail_hidden"] == []
    rail.set_hidden(["view_table", "nonsense", "view_logger"])
    assert rail.hidden == {"view_logger"}


def test_rail_follows_the_settings_page(win):
    win.settings.update({"rail_position": "top", "rail_collapsed": True})
    win._apply_settings(restyle=False)
    _pump()
    assert win.nav_rail.position == "top" and win.nav_rail.collapsed
    assert win._shell.indexOf(win.nav_rail) == 0
    assert all(b.text() == "" for b in win.nav_rail._view_btns.values())
    win.settings.update({"rail_position": "sideways", "rail_collapsed": False})
    win._apply_settings(restyle=False)
    assert win.nav_rail.position == "left"


def test_rail_marks_a_busy_tool(win):
    rail = win.nav_rail
    rail.set_busy({"view_logger": True})
    assert rail._view_btns["view_logger"].busy_color is not None
    assert rail._view_btns["view_scanner"].busy_color is None
    assert win.t("navBusy") in rail._view_btns["view_logger"].toolTip()
    rail.set_busy({})
    assert rail._view_btns["view_logger"].busy_color is None


def test_switch_views_and_highlight(win):
    tb = win.nav_rail
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
    tb = win.nav_rail
    win._dispatch_command("view_console")
    _pump()
    win._dispatch_command("settings")
    _pump()
    assert win._overlay_page is not None
    assert win.main_toolbar.btn_settings.property("active") == "true"
    win._overlay_page.reject()                        # pristine -> closes
    _pump()
    assert win._overlay_page is None
    assert win.content_stack.currentWidget() is win.console_view
    assert tb._view_btns["view_console"].property("active") == "true"


def test_map_editor_opens_as_overlay(win):
    """Ctrl+2 / profile menu opens the editor over the MAP view — the map nav
    button stays highlighted (the editor belongs to that view)."""
    from gui.map_editor import ProfileEditorDialog
    win._dispatch_command("view_console")
    _pump()
    win._dispatch_command("view_map")
    _pump()
    assert isinstance(win._overlay_page, ProfileEditorDialog)
    assert win.nav_rail._view_btns["view_table"].property("active") == "true"
    assert win.main_toolbar.lbl_title.text() == win.t("profileEditor")
    win._overlay_page.reject()
    _pump()
    assert win._overlay_page is None


def test_project_dropdown_is_the_first_header_crumb(win):
    # The project owns the map, the boards and the link: it sits at the left
    # of the HEADER, on every page (the window owns its menu).
    assert win.btn_profile.parent() is win.main_toolbar
    assert "view_map" not in win.nav_rail._view_btns       # hidden command now
    win._dispatch_command("view_scanner")
    _pump()
    assert win.btn_profile.isVisibleTo(win)


def test_header_link_chip_follows_the_settings(win):
    win.settings.update({"port": "COM9", "baudrate": "9600", "parity": "Even (E)",
                         "slave_id": 7})
    win._refresh_link_label()
    text = win.main_toolbar.btn_link.text()
    assert "COM9" in text and "9600" in text and "8E1" in text and "ID 7" in text


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
    from core import formats
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
    from app.version import APP_VERSION
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
