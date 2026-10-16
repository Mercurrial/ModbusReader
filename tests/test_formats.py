"""Versioned formats + migrations — the "old files open forever" guarantee.

Golden fixtures for every historical on-disk shape (bare array, dict wrapper,
current envelope) plus the project format. If a migration breaks, a user's
saved profile stops loading — so these are load-bearing."""
import json

import pytest

from core import formats
from core import scaling


# ── profile version detection + migration ──────────────────────────────
def test_detect_versions():
    assert formats.detect_profile_version([{"addr": 1}]) == 0          # bare
    assert formats.detect_profile_version({"registers": []}) == 1      # wrapper
    assert formats.detect_profile_version({"version": 2, "registers": []}) == 2


def test_bare_array_migrates_to_current():
    legacy = [{"addr": 1, "name": "R1", "type": "SHORT"}]
    prof = formats.migrate_profile(legacy)
    assert prof["version"] == formats.PROFILE_VERSION
    assert prof["registers"][0]["name"] == "R1"
    assert prof["registers"][0]["addr"] == 1


def test_dict_wrapper_migrates():
    legacy = {"registers": [{"addr": 5, "name": "X", "type": "FLOAT"}]}
    prof = formats.migrate_profile(legacy)
    assert prof["version"] == formats.PROFILE_VERSION
    assert prof["registers"][0]["addr"] == 5


def test_current_envelope_roundtrip(tmp_path):
    regs = [{"addr": 16, "name": "Ток", "type": "SHORT", "unit": "А",
             "scale": 0.01, "offset": 0.0, "enum": {}}]
    p = tmp_path / "p.json"
    formats.dump_profile(str(p), regs, name="Проба")
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["format"] == formats.PROFILE_KIND
    assert doc["version"] == formats.PROFILE_VERSION
    assert doc["name"] == "Проба"
    prof = formats.load_profile(str(p))
    r = prof["registers"][0]
    assert r["scale"] == 0.01 and r["unit"] == "А"
    assert "offset" not in r                           # identity dropped
    assert "enum" not in r                             # empty dropped


def test_string_hex_address_coerced():
    prof = formats.migrate_profile([{"addr": "0x10", "name": "H", "type": "SHORT"}])
    assert prof["registers"][0]["addr"] == 16


def test_future_version_refused():
    with pytest.raises(ValueError):
        formats.migrate_profile({"version": 999, "registers": []})


def test_enum_keys_normalized_to_strings():
    prof = formats.migrate_profile(
        [{"addr": 1, "name": "S", "type": "SHORT", "enum": {0: "Off", 1: "On"}}])
    enum = prof["registers"][0]["enum"]
    assert enum == {"0": "Off", "1": "On"}             # JSON-safe string keys


# ── project format ───────────────────────────────────────────────────────
def test_project_roundtrip(tmp_path):
    settings = {"port": "COM7", "baudrate": "115200", "slave_id": 10,
                "order_float": "BADC", "pinned_views": ["view_table"],
                "theme": "Dark"}          # theme is NOT a project key
    regs = [{"addr": 1, "name": "R", "type": "SHORT"}]
    boards = [{"name": "Обзор",
               "widgets": [{"uid": "a", "reg_id": "0x0001", "kind": "value"}],
               "links": []},
              {"name": "Наладка", "widgets": [], "links": []}]
    p = tmp_path / "proj.mbproj"
    formats.dump_project(str(p), "Стенд-1", settings, regs, boards)
    proj = formats.load_project(str(p))
    assert proj["format"] == formats.PROJECT_KIND
    assert proj["version"] == formats.PROJECT_VERSION
    assert proj["connection"]["port"] == "COM7"
    assert proj["connection"]["order_float"] == "BADC"
    assert "theme" not in proj["connection"]           # only whitelisted keys
    assert proj["profile"]["registers"][0]["name"] == "R"
    assert [b["name"] for b in proj["dashboards"]] == ["Обзор", "Наладка"]
    assert proj["dashboards"][0]["widgets"][0]["uid"] == "a"
    assert proj["layout"]["pinned_views"] == ["view_table"]


def test_project_accepts_legacy_single_dashboard():
    """A project written before multi-dashboard support had a flat
    ``dashboard: [widget…]`` key — it must load as one dashboard."""
    doc = {"format": formats.PROJECT_KIND, "version": 1, "name": "old",
           "connection": {}, "profile": {"registers": []},
           "dashboard": [{"uid": "a", "kind": "value"}]}
    proj = formats.migrate_project(doc)
    assert len(proj["dashboards"]) == 1
    assert proj["dashboards"][0]["widgets"][0]["uid"] == "a"
    assert "dashboard" not in proj                     # legacy key dropped


def test_dashboard_file_roundtrip(tmp_path):
    p = tmp_path / "screen.mbdash"
    widgets = [{"uid": "a", "kind": "timer", "x": 10, "y": 20},
               {"uid": "b", "kind": "button", "reg_id": "0x0010"}]
    links = [{"from": "a", "to": "b"}]
    formats.dump_dashboard(str(p), "Наладка", widgets, links)
    doc = formats.load_dashboard(str(p))
    assert doc["name"] == "Наладка"
    assert doc["widgets"][1]["reg_id"] == "0x0010"
    assert doc["links"] == [{"from": "a", "to": "b"}]


def test_dashboard_normalizes_junk():
    d = formats.normalize_dashboard(None, default_name="X")
    assert d == {"name": "X", "widgets": [], "links": []}
    # a bare widget list (pre-multi-dashboard settings) is accepted
    d2 = formats.normalize_dashboard([{"uid": "a", "kind": "value"}])
    assert d2["widgets"][0]["uid"] == "a" and d2["links"] == []
    # malformed links are dropped, not fatal
    d3 = formats.normalize_dashboard({"widgets": [], "links": [{"from": "a"}]})
    assert d3["links"] == []


def test_project_embedded_profile_migrated():
    # A project written with an OLD bare-array profile still loads.
    doc = {"format": formats.PROJECT_KIND, "version": 1, "name": "old",
           "connection": {}, "profile": [{"addr": 1, "name": "R",
                                          "type": "SHORT"}]}
    proj = formats.migrate_project(doc)
    assert proj["profile"]["version"] == formats.PROFILE_VERSION
    assert proj["profile"]["registers"][0]["name"] == "R"


# ── scaling math ─────────────────────────────────────────────────────────
def test_scaling_engineering_roundtrip():
    reg = {"scale": 0.01, "offset": 0.0}
    assert scaling.to_engineering(reg, 1234) == pytest.approx(12.34)
    assert scaling.to_raw(reg, 12.34) == pytest.approx(1234)


def test_scaling_offset():
    reg = {"scale": 0.1, "offset": -40.0}          # e.g. temperature sensor
    assert scaling.to_engineering(reg, 800) == pytest.approx(40.0)
    assert scaling.to_raw(reg, 40.0) == pytest.approx(800)


def test_scaling_identity_is_noop():
    reg = {}
    assert not scaling.has_scaling(reg)
    assert scaling.to_engineering(reg, 5) == 5
    assert scaling.to_raw(reg, 5) == 5


def test_scaling_zero_scale_guarded():
    assert scaling.to_raw({"scale": 0}, 5) == 5        # no ZeroDivisionError


def test_enum_label_display():
    reg = {"enum": {"0": "Стоп", "1": "Работа"}}
    assert scaling.format_value(reg, 1) == "Работа"
    assert scaling.format_value(reg, 0) == "Стоп"
    assert scaling.format_value(reg, 7) == "7"         # unmapped -> number


def test_format_value_scaled_with_unit():
    reg = {"scale": 0.01, "unit": "В"}
    assert scaling.format_value(reg, 1234, unit=True) == "12.34 В"
    assert scaling.format_value(reg, 1234, unit=False) == "12.34"


def test_scaling_dialog_enum_parse():
    from gui.scaling_dialog import parse_enum, enum_to_text
    txt = "0 = Стоп\n1 = Работа\n\nбред\n2=Авария"
    enum = parse_enum(txt)
    assert enum == {"0": "Стоп", "1": "Работа", "2": "Авария"}
    # round-trips back to text
    assert "1 = Работа" in enum_to_text(enum)
