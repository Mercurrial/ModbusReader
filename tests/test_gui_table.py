"""RegisterTable (MVC view): populate variants, value updates, view modes,
intent signals."""
import pytest
from PyQt6.QtCore import Qt

from app.app_context import AppContext
from app.settings_manager import DEFAULT_SETTINGS
from gui.register_table import (RegisterTable, COL_CURRENT, COL_STATE, COL_NEW,
                       COL_NAME, format_value)


@pytest.fixture()
def table():
    return RegisterTable(AppContext(dict(DEFAULT_SETTINGS)))


def test_register_names_follow_language():
    ctx = AppContext(dict(DEFAULT_SETTINGS, lang="ru"))
    t = RegisterTable(ctx)
    t.populate([{"addr": 1, "name": "Напряжение", "name_en": "Voltage",
                 "type": "SHORT", "rw": "RW"},
                {"addr": 2, "name": "Только RU", "type": "SHORT", "rw": "RW"}])
    assert t.item(0, COL_NAME).text() == "Напряжение"
    ctx.set_lang("en")
    t.retranslate()
    assert t.item(0, COL_NAME).text() == "Voltage"      # switched to name_en
    assert t.item(1, COL_NAME).text() == "Только RU"    # no name_en -> fallback
    ctx.set_lang("ru")
    t.retranslate()
    assert t.item(0, COL_NAME).text() == "Напряжение"


PROFILE = [
    {"addr": 5, "name": "A", "type": "SHORT", "rw": "RW", "length": 1},
    {"addr": "0x10", "name": "B", "type": "FLOAT", "rw": "R", "length": 2},
    {"addr": 0x20, "name": "M", "type": "MEMORY_AREA", "rw": "R", "length": 4},
]


def test_populate_variants(table):
    table.populate([])
    assert table.rowCount() == 0
    table.populate(PROFILE)
    assert table.rowCount() == 3
    assert set(table.addr_to_row) == {5, 0x10}     # area excluded, str parsed


def test_update_value_paths(table):
    table.populate(PROFILE)
    table.update_value(5, "123")
    assert table.item(table.addr_to_row[5], COL_CURRENT).text() == "123"
    table.update_value(5, "???")                    # non-numeric text kept
    assert table.item(table.addr_to_row[5], COL_CURRENT).text() == "???"
    table.update_value(0xDEAD, "1")                 # unknown addr: no-op


def test_value_sampled_feeds_trends(table):
    table.populate(PROFILE)
    fed = []
    table.value_sampled.connect(lambda rid, v: fed.append((rid, v)))
    table.update_value(5, "42")
    assert fed == [("0x0005", 42.0)]
    table.update_value(5, "not-a-number")           # no emit for text
    assert len(fed) == 1


def test_write_gated_on_connection(table):
    table.populate(PROFILE)
    writes = []
    table.write_requested.connect(lambda a, d, v: writes.append((a, d, v)))
    row = table.addr_to_row[5]
    table.set_connected(False)
    table.item(row, COL_NEW).setText("7")
    table._on_cell_changed(row, COL_NEW)
    assert writes == []                              # disconnected: swallowed
    table.set_connected(True)
    table.item(row, COL_NEW).setText("7")
    table._on_cell_changed(row, COL_NEW)
    assert writes == [(5, "SHORT", "7")]


def test_view_modes(table):
    table.populate(PROFILE)
    row = table.addr_to_row[5]
    table.update_value(5, "42")
    table.set_view_mode("0x0005", row, "hex")
    assert table.item(row, COL_CURRENT).text() == "0x002A"
    table.set_view_mode("0x0005", row, "bin")
    assert table.item(row, COL_CURRENT).text() == "0b0000 0000 0010 1010"
    table.set_view_mode("0x0005", row, "dec")
    assert table.item(row, COL_CURRENT).text() == "42"


def test_mark_all_stale(table):
    table.populate(PROFILE)
    table.mark_all_stale()
    for r in range(table.rowCount()):
        item = table.item(r, COL_STATE)
        assert item.data(Qt.ItemDataRole.UserRole) == "stale"


def test_highlight_changes_flashes_cell(table):
    table.ctx.settings["highlight_changes"] = True
    table.apply_settings()
    table.populate(PROFILE)
    row = table.addr_to_row[5]
    table.update_value(5, "1")                       # first value: no flash
    assert table.item(row, COL_CURRENT).background().style() == Qt.BrushStyle.NoBrush
    table.update_value(5, "2")                       # change -> flash applied
    assert table.item(row, COL_CURRENT).background().style() != Qt.BrushStyle.NoBrush


def test_highlight_disabled_no_flash(table):
    table.ctx.settings["highlight_changes"] = False
    table.apply_settings()
    table.populate(PROFILE)
    row = table.addr_to_row[5]
    table.update_value(5, "1")
    table.update_value(5, "2")
    assert table.item(row, COL_CURRENT).background().style() == Qt.BrushStyle.NoBrush


def test_mono_values_toggle_applies_font(table):
    from app.fonts import mono_family
    table.populate(PROFILE)
    row = table.addr_to_row[5]
    assert table.item(row, COL_CURRENT).font().family() == mono_family()
    table.ctx.settings["mono_values"] = False
    table.apply_settings()
    assert table.item(row, COL_CURRENT).font().family() == table.font().family()
    table.ctx.settings["mono_values"] = True
    table.apply_settings()
    assert table.item(row, COL_CURRENT).font().family() == mono_family()


def test_format_value_edges():
    assert format_value(255, "hex") == "0x00FF"
    assert format_value(-1, "hex") == "0xFFFF"
    assert format_value(255, "bin") == "0b0000 0000 1111 1111"
    assert format_value(3.5, "dec") == "3.5"
    assert format_value(3.0, "dec") == "3"
    assert format_value(float("inf"), "dec") == "inf"
    assert format_value(float("nan"), "hex") == "nan"


# ── the state column: a status dot + a separate log toggle ──────────
def _state(table, addr, now=None):
    from gui.register_table import StateDotDelegate
    idx = table.model().index(table.addr_to_row[addr], COL_STATE)
    return StateDotDelegate.freshness(idx, table._connected, now)


def test_state_dot_tells_freshness(table):
    import time
    table.populate(PROFILE)
    table.set_connected(True)
    assert _state(table, 5) == "none"                 # nothing yet: a hollow ring
    table.update_value(5, "1")
    t0 = time.monotonic()
    assert _state(table, 5, t0) == "fresh"
    assert _state(table, 5, t0 + 2.0) == "fresh"      # never late under 3 s
    assert _state(table, 5, t0 + 4.0) == "late"       # connected, no answers
    table.set_connected(False)
    table.mark_all_stale()
    assert _state(table, 5, t0) == "offline"          # grey, the value stays
    table.set_connected(True)
    assert _state(table, 5, t0) == "waiting"          # until the next reading
    table.update_value(5, "2")
    assert _state(table, 5) == "fresh"


def test_state_late_follows_the_poll_gap(table):
    """A register read every 5 s is not «late» after 4 s."""
    from gui.register_table import _ROLE_TS, _ROLE_GAP
    table.populate(PROFILE)
    table.set_connected(True)
    table.update_value(5, "1")
    item = table.item(table.addr_to_row[5], COL_STATE)
    item.setData(_ROLE_GAP, 5.0)
    ts = item.data(_ROLE_TS)
    assert _state(table, 5, ts + 12.0) == "fresh"
    assert _state(table, 5, ts + 16.0) == "late"


def test_log_toggle_is_its_own_button(table):
    """Clicking the dot does nothing; the console glyph beside it (and the
    menu) switch the register's frames into the log."""
    from PyQt6.QtCore import QPoint
    from gui.register_table import _ROLE_VERBOSE
    table.resize(900, 300)
    table.populate(PROFILE)
    got = []
    table.verbose_changed.connect(got.append)
    row = table.addr_to_row[5]
    rect = table.visualRect(table.model().index(row, COL_STATE))
    table._on_cell_clicked(row, COL_STATE)
    assert got == []                                   # the dot is not a switch
    assert not table._in_log_zone(QPoint(rect.left() + 10, rect.center().y()))
    assert table._in_log_zone(QPoint(rect.left() + 34, rect.center().y()))
    table.toggle_verbose(row)
    assert got[-1] == {5} and table.item(row, COL_STATE).data(_ROLE_VERBOSE)
    table.toggle_verbose(row)
    assert got[-1] == set() and not table.item(row, COL_STATE).data(_ROLE_VERBOSE)
    mem = 2                                            # the memory area: no toggle
    table.toggle_verbose(mem)
    assert got[-1] == set()


def test_state_tips_say_what_the_dot_means(table):
    from PyQt6.QtCore import QPoint
    table.resize(900, 300)
    table.populate(PROFILE)
    table.set_connected(True)
    row = table.addr_to_row[5]
    rect = table.visualRect(table.model().index(row, COL_STATE))
    dot = QPoint(rect.left() + 13, rect.center().y())
    log = QPoint(rect.left() + 34, rect.center().y())
    assert table._state_tip(dot) == table.t("stateNone")
    table.update_value(5, "1")
    assert table._state_tip(dot) == table.t("stateFresh").format(age=table.t("ageUnderSec"))
    assert table._state_tip(log) == table.t("logToggleOff")
    table.toggle_verbose(row)
    assert table._state_tip(log) == table.t("logToggleOn")
    assert table._age_text(75) == table.t("ageMin").format(n=1)


def test_write_field_only_where_writable(table):
    table.populate(PROFILE)
    rw = table.item(table.addr_to_row[5], COL_NEW)
    ro = table.item(table.addr_to_row[0x10], COL_NEW)
    assert rw.flags() & Qt.ItemFlag.ItemIsEditable
    assert not ro.flags() & Qt.ItemFlag.ItemIsEditable
    assert ro.toolTip() == table.t("newValReadOnly")
    assert rw.toolTip() == table.t("newValTip")
