"""Regression tests for the v2.0.0 audit.

Every test here pins a bug that was found in the running code (most of them by
driving the real widget path, a few by static analysis) and fixed in 2.0.0.
The docstring of each test says what used to happen.
"""
import copy
import json
import os
import queue
import time

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMenu

import formats
import mapimport
import profile_manager as pm
import scaling
import settings_manager
import sniffer_core
import transports
from app_context import AppContext
from settings_manager import DEFAULT_SETTINGS


def _ctx(**over):
    s = copy.deepcopy(DEFAULT_SETTINGS)
    s.update(over)
    return AppContext(s)


def _pump(n=3):
    for _ in range(n):
        QApplication.processEvents()


# ═══════════════ serial link ═══════════════
@pytest.mark.parametrize("stored,code", [
    ("None (N)", "N"), ("Even (E)", "E"), ("Odd (O)", "O"),
    ("Even", "E"), ("odd", "O"), ("E", "E"), ("n", "N"), ("", "N"),
    ("garbage", "N"), (None, "N"), ("Mark", "M"),
])
def test_parity_code_accepts_every_stored_spelling(stored, code):
    assert transports.parity_code(stored) == code


def test_even_parity_from_the_settings_page_reaches_the_client():
    """The Settings page stores "Even (E)". The transport map only knew
    "Even", so every connection was opened 8N1 whatever the user chose."""
    client = transports.get("serial").create(
        {"port": "COM99", "baudrate": "9600", "parity": "Even (E)",
         "stopbits": "2"}, 0.5)
    assert client.comm_params.parity == "E"
    assert client.comm_params.stopbits == 2


def test_garbage_baudrate_does_not_raise_in_the_factory():
    client = transports.get("serial").create({"baudrate": "fast"}, 0.5)
    assert client.comm_params.baudrate == 115200


def test_status_bar_framing_label():
    assert transports.serial_framing({"parity": "Even (E)", "stopbits": "1"}) == "8E1"
    assert transports.serial_framing({"parity": "None (N)", "stopbits": "2"}) == "8N2"


# ═══════════════ polling core ═══════════════
class _BoomTransport:
    transport_id = "boom"

    @staticmethod
    def create(settings, timeout):
        raise ValueError("could not open port 'COM?'")

    @staticmethod
    def describe(settings):
        return "COM?"


def test_a_failing_port_open_reports_instead_of_killing_the_thread():
    """An exception from the client factory ended the QThread silently: no
    status signal, nothing in the log, the window stuck on 'connecting'."""
    from modbus_core import ModbusCore
    core = ModbusCore()
    core.transport = _BoomTransport()
    statuses, logs = [], []
    core.status_changed.connect(lambda ok, m: statuses.append((ok, m)))
    core.log_msg.connect(lambda lv, m: logs.append((lv, m)))
    core.run()                                   # synchronously
    assert statuses == [(False, "")]
    assert any(lv == "ERR" and "COM?" in m for lv, m in logs)


def test_shutdown_answers_waiting_ops_and_drops_stale_writes():
    """Queued work used to survive a disconnect: a macro sat out its whole
    timeout, and a write queued before the drop fired on the NEXT connect."""
    from modbus_core import ModbusCore
    core = ModbusCore()
    logs = []
    core.log_msg.connect(lambda lv, m: logs.append((lv, m)))
    result = queue.Queue(maxsize=1)
    core.op_queue.put({"kind": "read", "addr": 1, "type": "SHORT",
                       "value": None, "slave": None, "result": result})
    core.queue_write(0x10, "SHORT", "5")
    core.queue_write(0x11, "SHORT", "6")
    finished = []
    core.array_read_finished.connect(lambda a, w: finished.append((a, w)))
    core.queue_array_read(0x40, 8)
    core._drain_queues()
    status, _msg = result.get_nowait()
    assert status == "err"
    assert core.write_queue.empty()
    assert any(lv == "ERR" and "2" in m for lv, m in logs)
    assert finished == [(0x40, [])]


def test_an_unacknowledged_macro_write_raises_in_the_macro():
    from modbus_core import ModbusCore

    class _Err:
        def isError(self):
            return True

    class _Client:
        def write_register(self, address, value, **kw):
            return _Err()

    core = ModbusCore()
    core.client = _Client()
    result = queue.Queue(maxsize=1)
    core._execute_op({"kind": "write", "addr": 5, "type": "SHORT",
                      "value": 1, "slave": None, "result": result})
    status, _ = result.get_nowait()
    assert status == "err"


def test_core_messages_follow_the_ui_language():
    ctx = _ctx(lang="en")
    assert ctx.core._msg("coreDisconnected") == "Disconnected"
    ctx.set_lang("ru")
    assert ctx.core._msg("coreDisconnected") == "Отключено"


# ═══════════════ formats ═══════════════
def test_a_bare_map_opened_as_a_project_keeps_its_registers():
    """{"registers": [...]} passed the project check but its TOP-level
    registers were ignored — an empty map, looking exactly like data loss."""
    proj = formats.migrate_project({"registers": [{"addr": 3, "name": "A"}]})
    assert [r["addr"] for r in proj["profile"]["registers"]] == [3]


@pytest.mark.parametrize("fn,doc", [
    (formats.migrate_project, {"profile": {"registers": []}, "version": 0}),
    (formats.migrate_dashboard, {"widgets": [], "version": 0}),
])
def test_version_zero_is_a_readable_error_not_a_keyerror(fn, doc):
    with pytest.raises(ValueError):
        fn(doc)


# ═══════════════ map import ═══════════════
def test_4x_mode_maps_40000_to_zero_not_9999():
    assert mapimport.apply_addr_mode(40000, "4x") == 0
    assert mapimport.apply_addr_mode(40001, "4x") == 0


@pytest.mark.parametrize("text,rw", [
    ("write", "W"), ("W/O", "W"), ("R/O", "R"), ("read-only", "R"),
    ("только запись", "W"), ("RW", "RW"),
])
def test_access_words_are_read_as_tokens(text, rw):
    assert mapimport.normalize_rw(text) == rw


# ═══════════════ sniffer ═══════════════
def test_carving_a_long_junk_buffer_is_fast():
    """CRC was recomputed from scratch for every candidate end: cubic time,
    seconds of CPU per flush on a noisy line."""
    junk = bytes((i * 37 + 11) & 0xFF for i in range(20000))
    t0 = time.perf_counter()
    sniffer_core.carve_frames(junk)
    assert time.perf_counter() - t0 < 0.5


def test_carving_still_splits_back_to_back_frames():
    body = bytes([1, 3, 0, 0, 0, 2])
    crc = sniffer_core.crc16(body)
    frame = body + bytes([crc & 0xFF, crc >> 8])
    assert sniffer_core.carve_frames(frame * 3) == [frame] * 3


# ═══════════════ scaling ═══════════════
@pytest.mark.parametrize("raw", [float("inf"), float("-inf"), float("nan")])
def test_non_finite_values_format_without_raising(raw):
    assert scaling.format_value({"scale": 0.1}, raw)
    assert scaling.format_value({"enum": {"1": "On"}}, raw)


def test_enum_keys_with_leading_zeros_are_kept():
    from gui_scaling_dialog import parse_enum
    assert parse_enum("01 = Работа\n0x02 = Стоп") == {"1": "Работа", "2": "Стоп"}


# ═══════════════ settings ═══════════════
def test_loaded_settings_never_share_objects_with_the_defaults(tmp_path):
    """A shallow merge handed out the very lists inside DEFAULT_SETTINGS;
    editing one in place changed the defaults for everything after."""
    old = settings_manager.SETTINGS_FILE
    try:
        settings_manager.SETTINGS_FILE = str(tmp_path / "s.json")
        s = settings_manager.load_settings()
        s["recent_profiles"].append("x")
        s["viewer_configs"]["k"] = 1
        assert DEFAULT_SETTINGS["recent_profiles"] == []
        assert DEFAULT_SETTINGS["viewer_configs"] == {}
    finally:
        settings_manager.SETTINGS_FILE = old


def test_the_shortcuts_page_lists_every_registered_shortcut():
    """The page was hand-written and had drifted (Ctrl+7 shown as Slave,
    Ctrl+S/8/9 missing). It is now generated from commands.COMMANDS."""
    import commands
    from gui_settings import SettingsDialog
    from settings_schema import PAGES
    dlg = SettingsDialog(copy.deepcopy(DEFAULT_SETTINGS))
    dlg.nav.setCurrentRow([p.key for p in PAGES].index("shortcuts"))
    page = dlg._page_scrolls[dlg._page_keys.index("shortcuts")].widget()
    from PyQt6.QtWidgets import QLabel
    pills = [lb.text() for lb in page.findChildren(QLabel)
             if lb.objectName() == "kbdPill"]
    for cmd in commands.SHORTCUTS:
        assert cmd.shortcut.split("+")[-1] in pills, cmd.cmd_id
    dlg.deleteLater()


# ═══════════════ register table ═══════════════
@pytest.fixture()
def table():
    from gui_table import RegisterTable
    t = RegisterTable(_ctx())
    t.populate([
        {"addr": 1, "name": "A", "type": "SHORT", "rw": "RW"},
        {"addr": 2, "name": "V", "type": "SHORT", "rw": "R", "scale": 0.1,
         "unit": "V"},
        {"addr": 4, "name": "L", "type": "LONG", "rw": "R"},
        {"addr": 6, "name": "F", "type": "FLOAT", "rw": "R"},
        {"addr": 8, "name": "W", "type": "SHORT", "rw": "W"},
    ])
    return t


def test_the_context_menu_opens(table, monkeypatch):
    """The menu called self.t(...) on a table that had no `t`: every
    right-click raised, and with it the only way onto a live chart."""
    shown = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *a: shown.append(
        [a.text() for a in self.actions()]))
    from gui_table import COL_NAME
    rect = table.visualItemRect(table.item(0, COL_NAME))
    table._show_context_menu(rect.center())
    assert shown and table.t("ctxTrendAdd") in shown[0]


def test_a_nan_reading_does_not_leave_the_table_deaf(table):
    """An exception between blockSignals(True)/(False) left every later cell
    edit — i.e. every write the operator typed — silently ignored."""
    table.update_value(2, "inf")
    table.update_value(2, "nan")
    assert not table.signalsBlocked()


def test_non_finite_readings_never_reach_the_charts(table):
    fed = []
    table.value_sampled.connect(lambda rid, v: fed.append(v))
    table.update_value(1, "inf")
    table.update_value(1, "5")
    assert fed == [5.0]


def test_current_values_are_clean_numbers(table):
    """Snapshots/logger got the cell text: "12.3 V" (shown "12.3 V V"),
    or "0x002A" for a register viewed in hex."""
    table.update_value(1, "42")
    table.update_value(2, "123")
    table.set_view_mode("0x0001", table.addr_to_row[1], "hex")
    vals = table.current_values()
    assert vals[1] == "42"
    assert vals[2] == "12.3"


def test_fresh_only_drops_values_after_a_disconnect(table):
    table.update_value(1, "42")
    assert table.current_values(fresh_only=True) == {1: "42"}
    table.mark_all_stale()
    assert table.current_values(fresh_only=True) == {}
    assert table.current_values() == {1: "42"}      # still on screen


def test_hex_view_of_32_bit_types(table):
    from gui_table import COL_CURRENT
    table.update_value(4, "-2")
    table.set_view_mode("0x0004", table.addr_to_row[4], "hex")
    assert table.item(table.addr_to_row[4], COL_CURRENT).text() == "0xFFFFFFFE"
    table.update_value(6, "1.0")
    table.set_view_mode("0x0006", table.addr_to_row[6], "hex")
    assert table.item(table.addr_to_row[6], COL_CURRENT).text() == "0x3F800000"


def test_write_only_registers_are_writable(table):
    from gui_table import COL_NEW
    row = table.addr_to_row[8]
    assert table.item(row, COL_NEW).flags() & Qt.ItemFlag.ItemIsEditable


def test_typing_while_disconnected_is_reported_not_swallowed(table):
    from gui_table import COL_NEW
    blocked = []
    table.write_blocked.connect(lambda a, v: blocked.append((a, v)))
    row = table.addr_to_row[1]
    table.item(row, COL_NEW).setText("7")
    assert blocked == [(1, "7")]
    assert table.item(row, COL_NEW).text() == ""


def test_an_enum_label_can_be_typed_to_write(table):
    table._regs_by_addr[1]["enum"] = {"0": "Стоп", "1": "Работа"}
    writes = []
    table.write_requested.connect(lambda a, d, v: writes.append(v))
    table._emit_write(1, "SHORT", "работа")
    assert writes == ["1"]


# ═══════════════ log + console ═══════════════
def test_one_log_two_views():
    """The bottom panel and the Консоль view kept separate buffers with
    different rules; now both render the same store."""
    from gui_log import LogPanel
    from gui_views import ConsoleView
    ctx = _ctx()
    panel = LogPanel(ctx)
    view = ConsoleView(ctx, store=panel.store)
    ctx.settings["log_verbosity"] = "min"
    panel.log("TX", "frame-out")
    panel.log("SYS", "hello")
    assert "hello" in view.view.toPlainText()
    assert "frame-out" not in view.view.toPlainText()


def test_console_history_is_shared_between_consoles():
    from gui_console import RawConsole
    ctx = _ctx()
    a, b = RawConsole(ctx), RawConsole(ctx)
    a._push_history("01 03")
    b._push_history("02 03")
    assert ctx.settings["console_history"] == ["01 03", "02 03"]
    assert DEFAULT_SETTINGS["console_history"] == []


# ═══════════════ editor addressing ═══════════════
def test_chain_flags():
    regs = [{"addr": 0, "type": "SHORT"}, {"addr": 1, "type": "FLOAT"},
            {"addr": 16, "type": "SHORT"}, {"addr": 17, "type": "SHORT"}]
    assert pm.chained_flags(regs) == [False, True, False, True]


@pytest.fixture()
def editor():
    from profile_editor import ProfileEditorDialog
    gapped = [{"addr": 0x00, "name": "A", "type": "SHORT"},
              {"addr": 0x01, "name": "B", "type": "SHORT"},
              {"addr": 0x10, "name": "C", "type": "SHORT"},
              {"addr": 0x11, "name": "D", "type": "SHORT"}]
    ed = ProfileEditorDialog(None, gapped, _ctx())
    yield ed
    ed.is_modified = False
    ed.close()


def _addrs(ed):
    return [r["addr"] for r in ed.profile_data]


def test_a_type_change_keeps_the_gap(editor):
    """Every structural edit renumbered ALL rows from 0: an imported vendor
    map with gaps was silently rewritten and then polled at wrong addresses."""
    editor._on_type_changed(1, "FLOAT")
    assert _addrs(editor) == [0x00, 0x01, 0x10, 0x11]
    editor._on_type_changed(0, "FLOAT")              # chained neighbour moves
    assert _addrs(editor) == [0x00, 0x02, 0x10, 0x11]


def test_delete_keeps_explicit_addresses(editor):
    editor._delete_selected(2)
    assert _addrs(editor) == [0x00, 0x01, 0x11]
    editor._delete_selected(0)                       # anchor keeps its addr
    assert _addrs(editor) == [0x01, 0x11]


def test_a_typed_address_moves_its_chain(editor):
    from profile_editor import COL_ADDR
    item = editor.table.item(2, COL_ADDR)
    item.setText("0x20")
    _pump()
    assert _addrs(editor) == [0x00, 0x01, 0x20, 0x21]
    item = editor.table.item(2, COL_ADDR)
    item.setText("nonsense")                         # reverted, not applied
    _pump()
    assert _addrs(editor) == [0x00, 0x01, 0x20, 0x21]


def test_a_contiguous_map_still_packs_after_a_drag():
    from profile_editor import ProfileEditorDialog
    regs = [{"addr": 0x100 + i, "name": f"R{i}", "type": "SHORT"} for i in range(3)]
    ed = ProfileEditorDialog(None, regs, _ctx())
    ed.table.verticalHeader().moveSection(2, 0)
    ed._on_reorder_committed()
    assert [r["name"] for r in ed.profile_data] == ["R2", "R0", "R1"]
    assert _addrs(ed) == [0x100, 0x101, 0x102]      # start address kept
    ed.is_modified = False
    ed.close()


# ═══════════════ memory viewer ═══════════════
def test_the_memory_viewer_opens():
    """The title used self.t before it was assigned: AttributeError, the
    viewer never opened."""
    from memory_viewer import MemoryViewerDialog
    ctx = _ctx()
    d = MemoryViewerDialog(0x20, 8, "Mem", ctx=ctx)
    d.set_real_data([1, 2, 3, 4, 5, 6, 7, 8])
    assert d.table.rowCount() == 8
    d.deleteLater()


# ═══════════════ macros ═══════════════
class _FakeCore:
    is_running = True

    def request_op(self, *a, **k):
        return 0


def test_stop_cannot_be_swallowed_by_except_exception():
    from macro_engine import MacroRunner
    code = "while True:\n    try:\n        pass\n    except Exception:\n        pass\n"
    r = MacroRunner(code, _FakeCore(), [])
    done = []
    r.sig_finished.connect(lambda ok, m: done.append(ok))
    r.start()
    time.sleep(0.2)
    r.request_stop()
    assert r.wait(3000), "the macro thread did not stop"
    _pump()
    assert done == [False]


def test_a_nul_byte_in_the_script_finishes_cleanly():
    from macro_engine import MacroRunner
    r = MacroRunner("x = 1\x00", _FakeCore(), [])
    done = []
    r.sig_finished.connect(lambda ok, m: done.append((ok, m)))
    r.run()
    assert done and done[0][0] is False


# ═══════════════ trends ═══════════════
def test_chart_settings_are_applied():
    """«Автомасштаб Y» and «Анимация» were stored and read by nothing."""
    from gui_trends import TrendsManager
    ctx = _ctx(graph_autofit_y=False, graph_anim="off")
    tm = TrendsManager(ctx)
    tm.add_trend("0x0001", "A")
    card = tm.active_trends["0x0001"]
    assert card.autofit is False and card._antialias is False
    ctx.settings["graph_autofit_y"] = True
    ctx.settings["graph_anim"] = "smooth"
    tm.apply_settings()
    assert card.autofit is True and card._antialias is True
    card.add_value(float("nan"))
    assert len(card._vs) == 0


# ═══════════════ the window ═══════════════
@pytest.fixture()
def win(tmp_path, monkeypatch):
    import gui_main
    monkeypatch.setattr(settings_manager, "SETTINGS_FILE",
                        str(tmp_path / "settings.json"), raising=False)
    w = gui_main.ModernScadaApp()
    yield w
    w.logger_view.stop_if_running()
    w.deleteLater()


def test_errors_are_counted_by_level(win):
    """The counter searched messages for the word "error" — it missed
    «Соединение потеряно» and counted harmless lines."""
    win._log("SYS", "no error here")
    win._log("ERR", "Соединение потеряно")
    assert win.error_counter == 1


def test_ctrl_s_saves_the_map_while_the_editor_is_open(win, monkeypatch):
    """Two window-level Ctrl+S shortcuts are ambiguous to Qt: neither fired."""
    win._open_map_editor()
    saved = []
    monkeypatch.setattr(win._overlay_page, "_save", lambda: saved.append(1))
    win._dispatch_command("save_project")
    assert saved == [1]
    win._overlay_page.is_modified = False
    win._overlay_page.reject()


def test_the_editor_opens_on_the_current_map(win, tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps([{"addr": 5, "name": "X", "type": "SHORT"}]),
                 encoding="utf-8")
    win._load_profile(str(p))
    win._open_map_editor()
    ed = win._overlay_page
    assert [r["addr"] for r in ed.profile_data] == [5]
    assert ed.file_path == str(p)
    ed.reject()


def test_the_logger_plan_follows_a_loaded_map(win, tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps([{"addr": 5, "name": "X", "type": "SHORT"}]),
                 encoding="utf-8")
    win._load_profile(str(p))
    assert win.logger_view.table.rowCount() == 1
    assert not win.logger_view.lbl_empty.isVisibleTo(win.logger_view)


def test_a_project_map_is_what_comes_back_after_restart(tmp_path, monkeypatch):
    """Only the bare .json path used to be restored: the window came back
    showing the project's name over a different, older map."""
    import gui_main
    proj = str(tmp_path / "plant.mbproj")
    formats.dump_project(proj, "plant", dict(DEFAULT_SETTINGS),
                         [{"addr": 7, "name": "P", "type": "SHORT"}], [])
    other = tmp_path / "old.json"
    other.write_text(json.dumps([{"addr": 1, "name": "O", "type": "SHORT"}]),
                     encoding="utf-8")
    base = copy.deepcopy(DEFAULT_SETTINGS)
    base.update(last_project_path=proj, last_project_name="plant",
                last_profile_path="", guide_seen_main=True)
    monkeypatch.setattr(gui_main, "load_settings", lambda: copy.deepcopy(base))
    w = gui_main.ModernScadaApp()
    assert [r["addr"] for r in w.profile_data] == [7]
    assert w.project_name == "plant"
    w.deleteLater()


def test_a_new_project_forgets_the_old_map_file(win, tmp_path, monkeypatch):
    p = tmp_path / "m.json"
    p.write_text(json.dumps([{"addr": 5, "name": "X", "type": "SHORT"}]),
                 encoding="utf-8")
    win._load_profile(str(p))
    import gui_main
    monkeypatch.setattr(gui_main, "themed_message", lambda *a, **k: 0)
    win._new_project()
    assert win.settings["last_profile_path"] == ""
    assert win.status_bar.lbl_config.text() == win.t("stNoProfile")


def test_a_bare_map_picked_in_the_project_dialog_opens_as_the_map(win, tmp_path):
    p = tmp_path / "bare.json"
    p.write_text(json.dumps([{"addr": 9, "name": "B", "type": "SHORT"}]),
                 encoding="utf-8")
    win._open_project(str(p))
    assert [r["addr"] for r in win.profile_data] == [9]


def test_applying_a_project_updates_the_status_bar_slave_id(win):
    proj = formats.migrate_project({"connection": {"slave_id": 42},
                                    "profile": {"registers": []}})
    win.apply_project(proj)
    assert win.status_bar._slave_ed._value == 42


def test_the_dashboard_add_button_is_reachable_in_run_mode(win, monkeypatch):
    import gui_dash

    class _Dlg:
        result_cfg = None

        def __init__(self, *a, **k):
            pass

        def exec(self):
            return 0

    monkeypatch.setattr(gui_dash, "WidgetDialog", _Dlg)
    dv = win.dash_view
    dv.set_edit(False)
    assert dv.btn_add.isVisibleTo(dv)
    dv._add_widget()
    assert dv.edit is True
