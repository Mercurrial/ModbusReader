"""Snapshot / compare — "what did that knob actually change?".

The subtle part is not taking the snapshot, it is comparing: a register that
exists on only one side is added/removed, not changed; "5" and "5.0" are the
same reading; and float noise must not bury the real differences.
"""
import json

import pytest

from core import snapshots as sn

REGS = [
    {"addr": 0x10, "name": "Температура", "type": "FLOAT", "unit": "°C"},
    {"addr": 0x12, "name": "Давление", "type": "SHORT", "unit": "бар"},
    {"addr": 0x14, "name": "Режим", "type": "SHORT"},
]


# ═══════════════ value comparison ═══════════════
@pytest.mark.parametrize("a,b", [
    ("5", "5.0"), (5, 5.0), ("5", 5), (" 5 ", "5"),
    ("12,5", "12.5"),                       # decimal comma from the UI
    ("0.30000000000000004", "0.3"),         # float arithmetic noise
    ("Работа", "Работа"), ("—", "—"), (None, None),
])
def test_values_that_mean_the_same_thing(a, b):
    assert sn.values_equal(a, b)


@pytest.mark.parametrize("a,b", [
    ("5", "6"), (5, 5.1), ("Работа", "Стоп"), ("", "0"),
    (None, "0"), ("0", None), ("5", "пять"),
])
def test_values_that_differ(a, b):
    assert not sn.values_equal(a, b)


def test_large_numbers_use_a_relative_tolerance():
    """An absolute epsilon alone would call 1e9 and 1e9+1 equal or 0.0 and
    1e-12 different, depending which one you pick."""
    assert sn.values_equal(1e9, 1e9 + 1e-6)     # round-trip noise
    assert not sn.values_equal(1e9, 1e9 + 1)    # a whole unit IS a change


def test_booleans_are_not_treated_as_numbers():
    assert not sn.values_equal(True, "1")


# ═══════════════ making a snapshot ═══════════════
def test_snapshot_captures_names_types_and_units():
    snap = sn.make(REGS, {0x10: "25.4", 0x12: "3", 0x14: "Работа"}, name="До")
    assert snap["format"] == sn.FORMAT and snap["version"] == sn.VERSION
    assert snap["name"] == "До" and snap["taken_at"] > 0
    rows = {r["addr"]: r for r in snap["registers"]}
    assert rows[0x10]["value"] == "25.4" and rows[0x10]["unit"] == "°C"
    assert rows[0x14]["name"] == "Режим"


def test_unread_registers_are_kept_as_none_not_dropped():
    """"Never read" and "gone from the map" are different situations, and the
    comparison has to be able to tell them apart."""
    snap = sn.make(REGS, {0x10: "1"})
    rows = {r["addr"]: r for r in snap["registers"]}
    assert set(rows) == {0x10, 0x12, 0x14}
    assert rows[0x12]["value"] is None


def test_string_addresses_from_the_value_map_are_found():
    snap = sn.make(REGS, {"16": "7"})
    assert snap["registers"][0]["value"] == "7"


def test_junk_rows_in_the_profile_are_skipped_not_fatal():
    snap = sn.make([{"addr": 1, "name": "ok"}, "не словарь", {"no": "addr"},
                    {"addr": "нечисло"}], {1: "5"})
    assert [r["addr"] for r in snap["registers"]] == [1]


def test_a_snapshot_round_trips_through_json():
    snap = sn.make(REGS, {0x10: "25.4"})
    again = sn.load(json.loads(sn.dumps(snap)))
    assert again["registers"] == snap["registers"]


# ═══════════════ loading ═══════════════
@pytest.mark.parametrize("doc", [
    None, 0, "", [], {},
    {"format": "profile", "version": 1, "registers": []},
    {"format": sn.FORMAT, "version": 0, "registers": []},
    {"format": sn.FORMAT, "version": -1, "registers": []},
    {"format": sn.FORMAT, "version": True, "registers": []},
    {"format": sn.FORMAT, "version": 999, "registers": []},
    {"format": sn.FORMAT, "version": 1, "registers": "нет"},
])
def test_bad_snapshot_documents_are_refused_readably(doc):
    with pytest.raises(ValueError) as err:
        sn.load(doc)
    assert str(err.value).strip()


def test_load_drops_unusable_rows_but_keeps_the_rest():
    doc = {"format": sn.FORMAT, "version": 1, "registers": [
        {"addr": 1, "value": "5"}, "мусор", {"value": "нет адреса"},
        {"addr": "abc"}, {"addr": 2, "value": None}]}
    out = sn.load(doc)
    assert [r["addr"] for r in out["registers"]] == [1, 2]


# ═══════════════ comparing ═══════════════
def _snap(values, regs=None):
    return sn.make(regs if regs is not None else REGS, values)


def test_unchanged_values_are_reported_as_same():
    a = _snap({0x10: "25.4", 0x12: "3", 0x14: "Работа"})
    b = _snap({0x10: "25.40", 0x12: 3, 0x14: "Работа"})
    rows = sn.compare(a, b)
    assert all(r["state"] == sn.SAME for r in rows), rows


def test_a_changed_value_is_found_with_both_sides():
    a = _snap({0x10: "25.4", 0x12: "3", 0x14: "Работа"})
    b = _snap({0x10: "25.4", 0x12: "9", 0x14: "Работа"})
    changed = [r for r in sn.compare(a, b) if r["state"] == sn.CHANGED]
    assert len(changed) == 1
    assert changed[0]["addr"] == 0x12
    assert changed[0]["before"] == "3" and changed[0]["after"] == "9"
    assert changed[0]["name"] == "Давление" and changed[0]["unit"] == "бар"


def test_a_register_only_in_the_new_map_is_added_not_changed():
    """Calling this a change would be a lie — there was nothing to change."""
    a = _snap({0x10: "1"}, regs=REGS[:1])
    b = _snap({0x10: "1", 0x12: "2"}, regs=REGS[:2])
    rows = {r["addr"]: r for r in sn.compare(a, b)}
    assert rows[0x12]["state"] == sn.ADDED
    assert rows[0x12]["before"] is None and rows[0x12]["after"] == "2"


def test_a_register_only_in_the_old_map_is_removed():
    a = _snap({0x10: "1", 0x12: "2"}, regs=REGS[:2])
    b = _snap({0x10: "1"}, regs=REGS[:1])
    rows = {r["addr"]: r for r in sn.compare(a, b)}
    assert rows[0x12]["state"] == sn.REMOVED
    assert rows[0x12]["before"] == "2" and rows[0x12]["after"] is None
    assert rows[0x12]["name"] == "Давление", "the removed row keeps its name"


def test_a_register_that_became_readable_counts_as_changed():
    """None -> a number is a real transition the operator wants to see."""
    a = _snap({0x10: None, 0x12: "3", 0x14: "x"})
    b = _snap({0x10: "25.4", 0x12: "3", 0x14: "x"})
    rows = {r["addr"]: r for r in sn.compare(a, b)}
    assert rows[0x10]["state"] == sn.CHANGED


def test_comparison_is_sorted_by_address():
    a = _snap({0x14: "1", 0x10: "1", 0x12: "1"})
    b = _snap({0x14: "2", 0x10: "2", 0x12: "2"})
    addrs = [r["addr"] for r in sn.compare(a, b)]
    assert addrs == sorted(addrs)


def test_comparing_a_snapshot_with_itself_finds_nothing():
    a = _snap({0x10: "25.4", 0x12: "3", 0x14: "Работа"})
    assert sn.summarize(sn.compare(a, a))[sn.CHANGED] == 0


def test_compare_tolerates_empty_and_missing_sides():
    empty = {"registers": []}
    assert sn.compare(empty, empty) == []
    assert sn.compare({}, {}) == []
    a = _snap({0x10: "1"})
    assert len(sn.compare(empty, a)) == 3      # everything is "added"
    assert all(r["state"] == sn.ADDED for r in sn.compare(empty, a))


def test_summary_counts_every_state():
    a = _snap({0x10: "1", 0x12: "2"}, regs=REGS[:2])
    b = _snap({0x10: "1", 0x14: "9"}, regs=[REGS[0], REGS[2]])
    counts = sn.summarize(sn.compare(a, b))
    assert counts[sn.SAME] == 1 and counts[sn.ADDED] == 1
    assert counts[sn.REMOVED] == 1 and counts[sn.CHANGED] == 0


# ═══════════════ delta ═══════════════
def test_delta_reports_the_numeric_difference():
    assert sn.delta({"before": "10", "after": "12.5"}) == pytest.approx(2.5)
    assert sn.delta({"before": "12.5", "after": "10"}) == pytest.approx(-2.5)


def test_delta_is_none_for_non_numeric_or_missing_sides():
    assert sn.delta({"before": "Стоп", "after": "Работа"}) is None
    assert sn.delta({"before": None, "after": "5"}) is None
    assert sn.delta({"before": "5", "after": None}) is None


def test_delta_handles_the_decimal_comma():
    assert sn.delta({"before": "1,5", "after": "2,5"}) == pytest.approx(1.0)


# ═══════════════ the view, driven for real ═══════════════
import pytest as _pytest


@_pytest.fixture()
def view():
    from app.app_context import AppContext
    from app.settings_manager import DEFAULT_SETTINGS
    from gui.snapshot_view import SnapshotView
    profile = list(REGS)
    values = {}
    v = SnapshotView(AppContext(dict(DEFAULT_SETTINGS)),
                     lambda: profile, lambda: dict(values))
    v._profile, v._values = profile, values      # test handles
    return v


def test_view_take_then_compare_finds_the_one_change(view):
    view._values.update({0x10: "25.4", 0x12: "3", 0x14: "Работа"})
    view.take_snapshot()
    assert view.baseline is not None

    view._values[0x12] = "9"                     # operator turns a knob
    view.compare_now()
    assert view._counts[sn.CHANGED] == 1 and view._counts[sn.SAME] == 2
    assert view.table.rowCount() == 3


def test_view_filter_narrows_to_changed_rows(view):
    view._values.update({0x10: "1", 0x12: "2", 0x14: "3"})
    view.take_snapshot()
    view._values[0x12] = "99"
    view.compare_now()
    view.seg_filter.setValue(sn.CHANGED)
    assert view.table.rowCount() == 1
    assert view.table.item(0, 0).text() == "0x0012"


def test_unchanged_rows_show_no_delta(view):
    """A "+0" on every untouched row is noise that hides the real ones."""
    view._values.update({0x10: "5", 0x12: "5", 0x14: "5"})
    view.take_snapshot()
    view._values[0x12] = "7"
    view.compare_now()
    deltas = {view.table.item(r, 0).text(): view.table.item(r, 4).text()
              for r in range(view.table.rowCount())}
    assert deltas["0x0010"] == "" and deltas["0x0012"] == "+2"


def test_switching_language_redraws_the_summary(view):
    """Regression class: a status line rendered once keeps the old language."""
    view._values.update({0x10: "1", 0x12: "2", 0x14: "3"})
    view.take_snapshot()
    view._values[0x12] = "9"
    view.compare_now()
    ru = view.lbl_status.text()
    view.ctx.set_lang("en")
    view.retranslate(view.ctx.t)
    assert view.lbl_status.text() != ru
    assert "Changed" in view.lbl_status.text()
    assert view.table.item(0, 5).text() == "unchanged"


def test_compare_without_a_baseline_is_refused_not_crashed(view, monkeypatch):
    from gui import snapshot_view as gui_snapshot
    seen = []
    monkeypatch.setattr(gui_snapshot, "themed_info",
                        lambda *a, **k: seen.append(a[3]))
    view.compare_now()
    assert seen and view.table.rowCount() == 0


def test_taking_a_snapshot_without_a_profile_is_refused(monkeypatch):
    from app.app_context import AppContext
    from app.settings_manager import DEFAULT_SETTINGS
    from gui.snapshot_view import SnapshotView
    from gui import snapshot_view as gui_snapshot
    seen = []
    monkeypatch.setattr(gui_snapshot, "themed_info",
                        lambda *a, **k: seen.append(a[3]))
    v = SnapshotView(AppContext(dict(DEFAULT_SETTINGS)), lambda: [], lambda: {})
    v.take_snapshot()
    assert seen and v.baseline is None


def test_saving_and_reopening_a_snapshot_round_trips(view, tmp_path,
                                                     monkeypatch):
    from PyQt6.QtWidgets import QFileDialog
    path = str(tmp_path / "s.mbsnap")
    view._values.update({0x10: "25.4", 0x12: "3", 0x14: "Работа"})
    view.take_snapshot()
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (path, "")))
    view.save_snapshot()

    view.baseline = None
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (path, "")))
    view.load_snapshot()
    assert view.baseline is not None
    assert len(view.baseline["registers"]) == 3
    view.compare_now()
    assert view._counts[sn.CHANGED] == 0, "a round trip must compare as equal"


def test_opening_a_file_that_is_not_a_snapshot_is_reported(view, tmp_path,
                                                           monkeypatch):
    from PyQt6.QtWidgets import QFileDialog
    from gui import snapshot_view as gui_snapshot
    bad = tmp_path / "profile.json"
    bad.write_text('{"registers": [{"addr": 1}]}', encoding="utf-8")
    seen = []
    monkeypatch.setattr(gui_snapshot, "themed_info",
                        lambda *a, **k: seen.append(a[4]))
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(bad), "")))
    view.load_snapshot()
    assert seen and view.baseline is None
