"""Dashboard table must span the whole viewport and resize by stealing width.

Invariants (rather than exact pixels, which vary headless):
  * columns exactly fill the viewport — no dead space, no horizontal scrollbar;
  * the two value columns split the leftover equally;
  * dragging a content column wider steals from the value columns (total stays
    put) and can never push the grid past the viewport edge.
"""
from PyQt6.QtWidgets import QApplication

from app_context import AppContext
from settings_manager import DEFAULT_SETTINGS
from gui_table import RegisterTable, COL_NAME, COL_CURRENT, COL_NEW


def _pump():
    for _ in range(6):
        QApplication.processEvents()


def _make(width=900, n=8):
    ctx = AppContext(dict(DEFAULT_SETTINGS))
    t = RegisterTable(ctx)
    t.resize(width, 400)
    _pump()
    t.populate([{"addr": i, "name": f"Register_{i}", "type": "SHORT", "rw": "RW"}
                for i in range(n)])
    _pump()
    return t


def _total(t):
    return sum(t.columnWidth(c) for c in range(t.columnCount())
               if not t.isColumnHidden(c))


def test_fills_viewport():
    t = _make()
    assert abs(_total(t) - t.viewport().width()) <= 2


def test_value_columns_split_equally():
    t = _make()
    assert abs(t.columnWidth(COL_CURRENT) - t.columnWidth(COL_NEW)) <= 1


def test_widen_content_steals_from_values():
    t = _make()
    vp = t.viewport().width()
    cur_before = t.columnWidth(COL_CURRENT)
    t.horizontalHeader().resizeSection(COL_NAME, t.columnWidth(COL_NAME) + 120)
    _pump()
    assert t.columnWidth(COL_CURRENT) < cur_before      # values gave up width
    assert abs(_total(t) - vp) <= 2                     # grid still fills exactly


def test_extreme_widen_never_overflows():
    t = _make()
    vp = t.viewport().width()
    t.horizontalHeader().resizeSection(COL_NAME, t.columnWidth(COL_NAME) + 1000)
    _pump()
    assert _total(t) <= vp + 2                          # clamped, no scrollbar


def test_hiding_a_value_column_reflows():
    t = _make()
    vp = t.viewport().width()
    t.ctx.settings["show_new"] = False
    t.apply_settings()
    _pump()
    assert t.isColumnHidden(COL_NEW)
    assert abs(_total(t) - vp) <= 2                     # CURRENT reclaimed space
