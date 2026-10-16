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
    table.populate(PROFILE)
    row = table.addr_to_row[5]
    assert table.item(row, COL_CURRENT).font().family() in ("JetBrains Mono", "Consolas")
    table.ctx.settings["mono_values"] = False
    table.apply_settings()
    assert table.item(row, COL_CURRENT).font().family() == table.font().family()
    table.ctx.settings["mono_values"] = True
    table.apply_settings()
    assert table.item(row, COL_CURRENT).font().family() in ("JetBrains Mono", "Consolas")


def test_format_value_edges():
    assert format_value(255, "hex") == "0x00FF"
    assert format_value(-1, "hex") == "0xFFFF"
    assert format_value(255, "bin") == "0b0000 0000 1111 1111"
    assert format_value(3.5, "dec") == "3.5"
    assert format_value(3.0, "dec") == "3"
    assert format_value(float("inf"), "dec") == "inf"
    assert format_value(float("nan"), "hex") == "nan"
