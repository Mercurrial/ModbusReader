"""The logger VIEW (the writer itself is covered by test_datalog.py).

A recorder that shows nothing has to be verified by hand, so the view's job is
to answer two questions without leaving it: what will this file contain, and
what is it writing right now.
"""
import os

import pytest

from app_context import AppContext
from settings_manager import DEFAULT_SETTINGS
from gui_logger import LoggerView, human_size, human_elapsed

REGS = [
    {"addr": 0x10, "name": "Температура", "type": "SHORT", "unit": "°C"},
    {"addr": 0x12, "name": "Давление", "type": "SHORT", "unit": "бар"},
]


@pytest.fixture()
def view(qt_app, tmp_path):
    ctx = AppContext(dict(DEFAULT_SETTINGS))
    values = {0x10: "25.4", 0x12: "3.0"}
    v = LoggerView(ctx, lambda: REGS, lambda: dict(values))
    v.ed_path.setText(str(tmp_path / "run.csv"))
    v.values = values
    yield v
    v.stop_if_running()
    v.deleteLater()


# ═══════════════ the column plan ═══════════════
def test_the_columns_are_listed_before_you_start(view):
    """The column set freezes when the file opens — finding a missing
    register in the morning means the night is gone."""
    assert view.table.rowCount() == 2
    texts = [view.table.item(r, 1).text() for r in range(2)]
    assert texts == ["0x0010", "0x0012"]


def test_the_plan_shows_names_and_units(view):
    assert view.table.item(0, 2).text() == "Температура"
    assert view.table.item(0, 3).text() == "°C"


def test_the_forecast_says_how_big_an_hour_costs(view):
    view.spin_period.setValue(1000)
    assert "3600" in view.lbl_forecast.text()
    view.spin_period.setValue(100)
    assert "36000" in view.lbl_forecast.text()


def test_with_no_map_the_view_says_so_instead_of_showing_an_empty_grid(qt_app):
    ctx = AppContext(dict(DEFAULT_SETTINGS))
    v = LoggerView(ctx, lambda: [], lambda: {})
    assert v.lbl_empty.isVisible() or v.lbl_empty.text()
    assert not view_is_showing_table(v)
    v.deleteLater()


def view_is_showing_table(v):
    return v.table.isVisibleTo(v) and v.table.rowCount() > 0


def test_the_plan_follows_the_register_map(qt_app):
    regs = list(REGS)
    ctx = AppContext(dict(DEFAULT_SETTINGS))
    v = LoggerView(ctx, lambda: regs, lambda: {})
    regs.append({"addr": 0x20, "name": "Ток", "type": "SHORT", "unit": "А"})
    v.apply_settings()
    assert v.table.rowCount() == 3
    v.deleteLater()


# ═══════════════ the live preview ═══════════════
def test_running_shows_the_rows_it_writes(view):
    view.start()
    assert view.running
    view._tick()
    assert view.table.rowCount() >= 2
    assert view.table.columnCount() == 1 + 2      # timestamp + two registers


def test_the_newest_row_is_on_top(view):
    """Scrolling to the bottom of 40 000 rows to find the current one is not
    monitoring."""
    view.start()
    view.values[0x10] = "111"
    view._tick()
    view.values[0x10] = "222"
    view._tick()
    assert view.table.item(0, 1).text() == "222"
    assert view.table.item(1, 1).text() == "111"


def test_the_preview_is_bounded(view, monkeypatch):
    import gui_logger
    monkeypatch.setattr(gui_logger, "PREVIEW_ROWS", 5)
    view.start()
    for _ in range(20):
        view._tick()
    assert view.table.rowCount() <= 5


def test_a_missing_value_is_an_empty_cell_not_a_shift(view):
    view.start()
    view.values.pop(0x10)
    view._tick()
    assert view.table.item(0, 1).text() == ""
    assert view.table.item(0, 2).text() == "3.0"


def test_stopping_returns_to_the_column_plan(view):
    view.start()
    view._tick()
    view.stop()
    assert not view.running
    assert view.lbl_section.text() == view.ctx.t("logColumns")
    assert view.table.columnCount() == 4


# ═══════════════ status line ═══════════════
def test_the_status_reports_rows_size_and_elapsed(view):
    view.start()
    view._tick()
    text = view.lbl_status.text()
    assert view.ctx.t("logRunning").split("{")[0].strip() in text
    assert "0:00:" in text, text


def test_the_status_after_stopping_still_names_the_file(view):
    view.start()
    view._tick()
    view.stop()
    assert "run.csv" in view.lbl_status.text()


def test_a_write_failure_is_shown_and_stops_the_run(view):
    view.start()

    class _Broken:
        def writerow(self, _row):
            raise OSError("disk full")
    view.writer._writer = _Broken()
    view._tick()
    assert not view.running
    assert "disk full" in view.lbl_status.text()


# ═══════════════ formatting helpers ═══════════════
@pytest.mark.parametrize("n,expect", [
    (0, "0 B"), (512, "512 B"), (2048, "2.0 KB"),
    (5 << 20, "5.0 MB"), (3 << 30, "3.0 GB"),
])
def test_human_size(n, expect):
    assert human_size(n) == expect


@pytest.mark.parametrize("s,expect", [
    (0, "0:00:00"), (59, "0:00:59"), (61, "0:01:01"),
    (3661, "1:01:01"), (-5, "0:00:00"),
])
def test_human_elapsed(s, expect):
    assert human_elapsed(s) == expect


# ═══════════════ i18n ═══════════════
def test_a_language_switch_redraws_the_whole_view(view):
    view.ctx.update({"language": "en"})
    view.retranslate(view.ctx.t)
    assert view.lbl_section.text() == view.ctx.t("logColumns")
    assert view.table.rowCount() == 2, "the plan must survive the switch"


def test_a_language_switch_during_a_run_keeps_the_live_rows(view):
    view.start()
    view._tick()
    rows = view.table.rowCount()
    view.ctx.update({"language": "en"})
    view.retranslate(view.ctx.t)
    assert view.running
    assert view.table.rowCount() == rows
