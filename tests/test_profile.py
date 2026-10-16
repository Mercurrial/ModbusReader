"""Profile domain: loading, normalization tolerance, validation warnings."""
import json

import pytest

from gui.map_editor import normalize_registers, _to_int
from core.profile_manager import load_profile_data, find_overlaps, find_duplicate_names


def test_load_profile_data(tmp_path):
    # load_profile_data now MIGRATES + normalizes (fills defaults) — the
    # register comes back in the canonical schema, not the raw dict.
    p = tmp_path / "p.json"
    p.write_text(json.dumps([{"addr": 1}]), encoding="utf-8")
    reg = load_profile_data(str(p))[0]
    assert reg["addr"] == 1 and reg["type"] == "SHORT" and reg["rw"] == "RW"
    p.write_text("[]", encoding="utf-8")
    assert load_profile_data(str(p)) == []
    p.write_text('{"a": 1}', encoding="utf-8")     # malformed object
    with pytest.raises(ValueError):
        load_profile_data(str(p))


def test_to_int_tolerant():
    assert _to_int(5, 0) == 5
    assert _to_int(5.9, 0) == 5
    assert _to_int("0x10", 0) == 16
    assert _to_int("16", 0) == 16
    assert _to_int("", 7) == 7
    assert _to_int(None, 7) == 7
    assert _to_int("junk", 7) == 7


def test_normalize_tolerant():
    out = normalize_registers([
        {"addr": None}, {"addr": ""}, {"addr": "abc"},
        {"addr": "0x10", "length": "junk"}, {"addr": 5.0}, "not-a-dict",
    ])
    assert [r["addr"] for r in out] == [0, 0, 0, 16, 5]
    assert all(isinstance(r["length"], int) and r["length"] >= 1 for r in out)


def test_find_overlaps():
    clean = [{"addr": 0, "name": "A", "type": "SHORT"},
             {"addr": 1, "name": "B", "type": "FLOAT"},
             {"addr": 3, "name": "C", "type": "LONG"}]
    assert find_overlaps(clean) == []
    bad = [{"addr": 0, "name": "A", "type": "FLOAT"},     # spans 0-1
           {"addr": 1, "name": "B", "type": "SHORT"},     # overlaps A
           {"addr": 10, "name": "M", "type": "MEMORY_AREA", "length": 8},
           {"addr": 12, "name": "X", "type": "SHORT"},    # inside area M
           "junk", {"addr": "0x99", "name": "skip", "type": "SHORT"}]
    ov = find_overlaps(bad)
    assert len(ov) == 2 and "«A»" in ov[0] and "«M»" in ov[1]


def test_find_duplicate_names():
    regs = [{"addr": 0, "name": "Temp"}, {"addr": 1, "name": " temp "},
            {"addr": 2, "name": "Flow"}]
    assert find_duplicate_names(regs) == ["temp"]
    assert find_duplicate_names([]) == []
