"""Long-run CSV logging.

The failure modes that matter here are the boring ones: a column shifting by
one when a register fails to read, Excel refusing to open a Cyrillic file, and
a full disk taking the whole application down at 3 a.m.
"""
import os
import time

import pytest

import datalog


COLUMNS = [(0x10, "0x0010 Температура, °C"), (0x12, "0x0012 Давление, бар")]


def _read(path, encoding="utf-8-sig"):
    with open(path, "r", encoding=encoding, newline="") as f:
        return f.read()


def _rows(path):
    text = _read(path)
    return [line.split(";") for line in text.splitlines() if line]


# ═══════════════ header + basic writing ═══════════════
def test_header_names_every_column(tmp_path):
    w = datalog.LogWriter(str(tmp_path / "log.csv"), COLUMNS)
    w.close()
    header = _rows(str(tmp_path / "log.csv"))[0]
    assert header == ["timestamp", "0x0010 Температура, °C", "0x0012 Давление, бар"]


def test_rows_are_written_in_column_order(tmp_path):
    p = str(tmp_path / "log.csv")
    w = datalog.LogWriter(p, COLUMNS)
    assert w.write_row({0x10: "25.4", 0x12: "3"})
    assert w.write_row({0x12: "4", 0x10: "25.5"})   # dict order must not matter
    w.close()
    rows = _rows(p)
    assert rows[1][1:] == ["25,4", "3"]
    assert rows[2][1:] == ["25,5", "4"]
    assert w.rows_written == 2


def test_a_missing_value_leaves_an_empty_cell_not_a_shifted_row(tmp_path):
    """A register that failed to read this cycle must not move every later
    column by one — that silently corrupts the whole file."""
    p = str(tmp_path / "log.csv")
    w = datalog.LogWriter(p, COLUMNS)
    w.write_row({0x12: "3"})                # 0x10 missing
    w.close()
    row = _rows(p)[1]
    assert len(row) == 3 and row[1] == "" and row[2] == "3"


def test_every_row_has_the_same_width(tmp_path):
    p = str(tmp_path / "log.csv")
    w = datalog.LogWriter(p, COLUMNS)
    for values in ({0x10: "1", 0x12: "2"}, {}, {0x10: None, 0x12: "x"},
                   {0x99: "stranger"}):
        w.write_row(values)
    w.close()
    widths = {len(r) for r in _rows(p)}
    assert widths == {3}


def test_a_value_for_an_unknown_register_is_ignored(tmp_path):
    """Columns are fixed at open time; a late register cannot appear."""
    p = str(tmp_path / "log.csv")
    w = datalog.LogWriter(p, COLUMNS)
    w.write_row({0x10: "1", 0x12: "2", 0xFF: "не в шапке"})
    w.close()
    assert "не в шапке" not in _read(p)


# ═══════════════ Excel-facing details ═══════════════
def test_file_starts_with_a_bom_so_excel_reads_cyrillic(tmp_path):
    """Without it Excel on Windows decodes as cp1251 and every name is
    mojibake — which defeats the point of using CSV at all."""
    p = str(tmp_path / "log.csv")
    datalog.LogWriter(p, COLUMNS).close()
    with open(p, "rb") as f:
        assert f.read(3) == b"\xef\xbb\xbf"


def test_decimal_separator_is_applied_to_numbers_only(tmp_path):
    p = str(tmp_path / "log.csv")
    w = datalog.LogWriter(p, [(1, "num"), (2, "text")])
    w.write_row({1: "25.4", 2: "Ch.1"})     # a name with a dot must survive
    w.close()
    row = _rows(p)[1]
    assert row[1] == "25,4" and row[2] == "Ch.1"


def test_decimal_point_mode_leaves_values_alone(tmp_path):
    p = str(tmp_path / "log.csv")
    w = datalog.LogWriter(p, [(1, "v")], decimal=".", delimiter=",")
    w.write_row({1: "25.4"})
    w.close()
    assert "25.4" in _read(p)


def test_a_value_containing_the_delimiter_is_quoted(tmp_path):
    p = str(tmp_path / "log.csv")
    w = datalog.LogWriter(p, [(1, "v")])
    w.write_row({1: "a;b"})
    w.close()
    assert '"a;b"' in _read(p)


def test_no_blank_line_between_rows(tmp_path):
    """csv on Windows inserts one unless the file is opened with newline=""."""
    p = str(tmp_path / "log.csv")
    w = datalog.LogWriter(p, [(1, "v")])
    w.write_row({1: "1"})
    w.write_row({1: "2"})
    w.close()
    assert "\r\n\r\n" not in _read(p)


def test_timestamps_carry_milliseconds(tmp_path):
    p = str(tmp_path / "log.csv")
    w = datalog.LogWriter(p, [(1, "v")])
    w.write_row({1: "1"}, when=1700000000.123)
    w.close()
    stamp = _rows(p)[1][0]
    assert stamp.endswith(".123"), stamp


# ═══════════════ rotation ═══════════════
def test_part_naming_is_sortable():
    assert datalog.part_path("C:/logs/run.csv", 1) == "C:/logs/run.csv"
    assert datalog.part_path("C:/logs/run.csv", 2) == "C:/logs/run_002.csv"
    assert datalog.part_path("C:/logs/run.csv", 12) == "C:/logs/run_012.csv"


def test_rotation_starts_a_new_part_with_its_own_header(tmp_path):
    p = str(tmp_path / "run.csv")
    w = datalog.LogWriter(p, COLUMNS, rotate_mb=1)
    # ~1 MB of rows; each row is well under 100 bytes.
    payload = "9" * 60
    for _ in range(20000):
        w.write_row({0x10: payload, 0x12: payload})
        if w.part > 1:
            break
    w.close()
    assert w.part > 1, "never rotated"
    second = datalog.part_path(p, 2)
    assert os.path.exists(second)
    assert _rows(second)[0][0] == "timestamp", "the new part needs a header too"
    assert len(w.paths) == w.part


def test_rotation_size_is_clamped_to_something_sane(tmp_path):
    tiny = datalog.LogWriter(str(tmp_path / "a.csv"), COLUMNS, rotate_mb=0)
    huge = datalog.LogWriter(str(tmp_path / "b.csv"), COLUMNS, rotate_mb=999999)
    assert tiny.rotate_bytes >= datalog.MIN_ROTATE_MB * 1024 * 1024
    assert huge.rotate_bytes <= datalog.MAX_ROTATE_MB * 1024 * 1024
    tiny.close()
    huge.close()


# ═══════════════ failure handling ═══════════════
def test_an_unwritable_path_is_reported_not_raised(tmp_path):
    """The writer is driven from the poll path; it must never take the app
    down, whatever the filesystem says."""
    w = datalog.LogWriter(str(tmp_path / "nope" / "x" / "\0bad.csv"), COLUMNS)
    assert not w.active and w.last_error
    assert w.write_row({0x10: "1"}) is False     # still no exception


def test_a_write_failure_stops_logging_and_records_why(tmp_path):
    p = str(tmp_path / "log.csv")
    w = datalog.LogWriter(p, COLUMNS)
    w.write_row({0x10: "1"})

    class _Broken:
        def writerow(self, _row):
            raise OSError("disk full")
    w._writer = _Broken()
    assert w.write_row({0x10: "2"}) is False
    assert "disk full" in (w.last_error or "")
    assert not w.active


def test_close_is_idempotent(tmp_path):
    w = datalog.LogWriter(str(tmp_path / "log.csv"), COLUMNS)
    w.close()
    w.close()                                    # must not raise


def test_data_survives_a_crash_up_to_the_flush_budget(tmp_path):
    """Rows are buffered for speed, but a reader must see them soon after."""
    p = str(tmp_path / "log.csv")
    w = datalog.LogWriter(p, COLUMNS)
    for i in range(datalog.FLUSH_ROWS + 1):
        w.write_row({0x10: str(i), 0x12: "0"})
    # No close(): simulate reading the file while logging continues.
    assert len(_rows(p)) >= datalog.FLUSH_ROWS
    w.close()


def test_close_flushes_everything(tmp_path):
    p = str(tmp_path / "log.csv")
    w = datalog.LogWriter(p, COLUMNS)
    w.write_row({0x10: "1", 0x12: "2"})          # below the flush budget
    w.close()
    assert len(_rows(p)) == 2


# ═══════════════ columns_for ═══════════════
def test_columns_include_the_address_because_names_repeat():
    cols = datalog.columns_for([
        {"addr": 0x10, "name": "Температура", "unit": "°C"},
        {"addr": 0x12, "name": "Температура"},          # same name, different reg
    ])
    assert [c[0] for c in cols] == [0x10, 0x12]
    assert cols[0][1] == "0x0010 Температура, °C"
    assert cols[0][1] != cols[1][1], "columns must be distinguishable"


def test_columns_skip_junk_rows():
    cols = datalog.columns_for([{"addr": 1}, "мусор", {"no": "addr"},
                                {"addr": "abc"}, None])
    assert [c[0] for c in cols] == [1]


def test_columns_of_an_empty_profile():
    assert datalog.columns_for([]) == []
    assert datalog.columns_for(None) == []


def test_generated_name_sorts_chronologically():
    a = datalog.timestamp_name()
    time.sleep(1.05)
    b = datalog.timestamp_name()
    assert a < b and a.endswith(".csv")


# ═══════════════ the view, driven for real ═══════════════
@pytest.fixture()
def view(tmp_path):
    from app_context import AppContext
    from settings_manager import DEFAULT_SETTINGS
    from gui_logger import LoggerView
    regs = [{"addr": 0x10, "name": "Температура", "unit": "°C"},
            {"addr": 0x12, "name": "Давление", "unit": "бар"}]
    values = {0x10: "25.4", 0x12: "3"}
    v = LoggerView(AppContext(dict(DEFAULT_SETTINGS)),
                   lambda: regs, lambda: dict(values))
    v.ed_path.setText(str(tmp_path / "run.csv"))
    v.spin_period.setValue(100)
    v._regs, v._values = regs, values
    yield v
    v.stop_if_running()


def test_view_writes_the_first_row_immediately(view, tmp_path):
    """Waiting a whole period before the first row makes a 1-minute interval
    look broken."""
    view.start()
    assert view.running and view.writer.rows_written == 1
    view.stop()
    assert len(_rows(str(tmp_path / "run.csv"))) == 2      # header + 1


def test_view_locks_the_settings_while_logging(view):
    """The column set is fixed once the file is open; letting the path or the
    profile change mid-run would silently corrupt the file."""
    view.start()
    assert not view.ed_path.isEnabled() and not view.spin_period.isEnabled()
    view.stop()
    assert view.ed_path.isEnabled()


def test_view_reports_the_result_after_stopping(view):
    """"Not logging" throws away the one fact worth knowing after a long run."""
    view.start()
    for _ in range(3):
        view._tick()
    view.stop()
    text = view.lbl_status.text()
    assert "4" in text and "run.csv" in text
    assert "идёт" not in text, "still claims to be running"


def test_stopped_result_survives_a_language_switch(view):
    view.start()
    view._tick()
    view.stop()
    ru = view.lbl_status.text()
    view.ctx.set_lang("en")
    view.retranslate(view.ctx.t)
    assert view.lbl_status.text() != ru and "run.csv" in view.lbl_status.text()


def test_view_refuses_to_start_without_a_profile(monkeypatch, tmp_path):
    from app_context import AppContext
    from settings_manager import DEFAULT_SETTINGS
    from gui_logger import LoggerView
    import gui_logger
    seen = []
    monkeypatch.setattr(gui_logger, "themed_info",
                        lambda *a, **k: seen.append(a[3]))
    v = LoggerView(AppContext(dict(DEFAULT_SETTINGS)), lambda: [], lambda: {})
    v.ed_path.setText(str(tmp_path / "x.csv"))
    v.start()
    assert seen and not v.running


def test_a_write_failure_stops_the_timer_and_shows_why(view):
    view.start()

    class _Broken:
        def writerow(self, _row):
            raise OSError("disk full")
    view.writer._writer = _Broken()
    view._tick()
    assert not view.running and not view._timer.isActive()
    assert "disk full" in view.lbl_status.text()


def test_values_are_sampled_at_tick_time_not_at_start(view):
    """Each row must be a fresh snapshot, or the file records the same reading
    for hours."""
    view.start()
    view._values[0x12] = "9"
    view._tick()
    view.stop()
    rows = _rows(view.writer.base_path if view.writer else
                 view.ed_path.text())
    assert rows[-1][2] == "9"


def test_closing_the_view_flushes_the_file(view, tmp_path):
    view.start()
    view._tick()
    view.stop_if_running()                       # what the window calls on exit
    assert len(_rows(str(tmp_path / "run.csv"))) >= 2
