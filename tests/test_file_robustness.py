"""Hostile / broken files must produce a readable message, never a crash.

A profile arrives from a colleague, a backup, or a half-finished write. Every
case below was run against the real loader; the ones that produced an unhelpful
exception (`KeyError: -1`, `OverflowError`, `UnicodeDecodeError`) are now
explicit ValueErrors, because the UI shows `str(e)` to the operator verbatim.
"""
import json

import pytest

from core import formats
from core import profile_manager
from app import settings_manager as sm


def _write(tmp_path, raw: str, name="p.json"):
    p = tmp_path / name
    p.write_text(raw, encoding="utf-8")
    return str(p)


# ── the loader must never raise anything but ValueError ─────────────────
BROKEN = [
    pytest.param("", id="empty-file"),
    pytest.param("{{{{", id="not-json"),
    pytest.param("null", id="json-null"),
    pytest.param("42", id="bare-number"),
    pytest.param('"text"', id="bare-string"),
    pytest.param("{}", id="empty-object"),
    pytest.param('{"registers": "nope"}', id="registers-is-string"),
    pytest.param('{"registers": 5}', id="registers-is-number"),
    pytest.param('{"format":"profile","version":-1,"registers":[]}', id="version-negative"),
    pytest.param('{"format":"profile","version":9999,"registers":[]}', id="version-future"),
    pytest.param('{"format":"profile","version":true,"registers":[]}', id="version-bool"),
]


@pytest.mark.parametrize("raw", BROKEN)
def test_broken_profile_raises_a_readable_value_error(tmp_path, raw):
    with pytest.raises(ValueError) as err:
        profile_manager.load_profile_data(_write(tmp_path, raw))
    assert str(err.value).strip(), "the message is shown to the user — it must say something"


def test_non_utf8_file_is_explained_not_dumped(tmp_path):
    p = tmp_path / "cp1251.json"
    p.write_bytes('{"registers": [{"addr": 1, "name": "Тест"}]}'.encode("cp1251"))
    with pytest.raises(ValueError) as err:
        profile_manager.load_profile_data(str(p))
    assert "UTF-8" in str(err.value)


def test_missing_file_still_raises_oserror(tmp_path):
    """A path that isn't there is an OS condition, not a format problem — the
    caller distinguishes them."""
    with pytest.raises(OSError):
        profile_manager.load_profile_data(str(tmp_path / "nope.json"))


# ── junk inside an otherwise valid profile degrades, it does not abort ──
SURVIVABLE = [
    pytest.param('{"registers": [{}]}', id="register-with-nothing"),
    pytest.param('{"registers": [{"addr": {}, "type": "SHORT"}]}', id="addr-is-object"),
    pytest.param('{"registers": [{"addr": -5, "type": "SHORT"}]}', id="addr-negative"),
    pytest.param('{"registers": [{"addr": 99999999, "type": "SHORT"}]}', id="addr-too-big"),
    pytest.param('{"registers": [{"addr": 1e400, "type": "SHORT"}]}', id="addr-infinity"),
    pytest.param('{"registers": [{"addr": 1, "type": "PWNED"}]}', id="unknown-type"),
    pytest.param('{"registers": [{"addr": 1, "type": "ARR", "length": -3}]}', id="length-negative"),
    pytest.param('{"registers": [{"addr": 1, "type": "ARR", "length": 1000000000}]}',
                 id="length-absurd"),
    pytest.param('{"registers": [{"addr": 1, "type": "SHORT", "scale": "x"}]}', id="scale-string"),
    pytest.param('{"registers": [{"addr": 1, "type": "SHORT", "enum": [1, 2]}]}', id="enum-list"),
    pytest.param('{"registers": [1, 2, 3]}', id="rows-are-numbers"),
]


@pytest.mark.parametrize("raw", SURVIVABLE)
def test_junk_rows_degrade_to_something_usable(tmp_path, raw):
    regs = profile_manager.load_profile_data(_write(tmp_path, raw))
    assert isinstance(regs, list)
    for r in regs:
        assert isinstance(r, dict)
        # Whatever the file said, the result must be safe to poll.
        assert 0 <= int(r["addr"]) <= 0xFFFF, r
        assert 1 <= int(r["length"]) <= 0xFFFF, r


def test_an_absurd_length_cannot_make_the_poll_loop_ask_for_gigabytes(tmp_path):
    regs = profile_manager.load_profile_data(_write(
        tmp_path, '{"registers": [{"addr": 1, "type": "ARR", "length": 999999999}]}'))
    assert regs[0]["length"] <= 0xFFFF


def test_a_name_of_a_hundred_thousand_characters_is_not_fatal(tmp_path):
    raw = json.dumps({"registers": [{"addr": 1, "type": "SHORT", "name": "A" * 100000}]})
    regs = profile_manager.load_profile_data(_write(tmp_path, raw))
    assert len(regs) == 1


def test_markup_in_a_register_name_survives_as_text(tmp_path):
    """The log escapes HTML; the name must arrive intact rather than mangled."""
    raw = json.dumps({"registers": [
        {"addr": 1, "type": "SHORT", "name": "<b>x</b> & <script>"}]})
    regs = profile_manager.load_profile_data(_write(tmp_path, raw))
    assert regs[0]["name"] == "<b>x</b> & <script>"


# ── settings: a broken file must never stop the app from starting ───────
@pytest.mark.parametrize("raw", [
    pytest.param('{"port": "COM', id="truncated"),
    pytest.param("[]", id="array-not-object"),
    pytest.param("null", id="null"),
    pytest.param("not json at all", id="garbage"),
    pytest.param('{"font_size": "big", "poll_rate": [], "slave_id": {}}', id="wrong-types"),
])
def test_broken_settings_still_yield_a_usable_dict(tmp_path, raw, monkeypatch):
    monkeypatch.setattr(sm, "SETTINGS_FILE", str(tmp_path / "s.json"))
    (tmp_path / "s.json").write_text(raw, encoding="utf-8")
    s = sm.load_settings()
    assert isinstance(s, dict)
    for key in ("port", "baudrate", "theme"):
        assert key in s, f"{key} missing — startup would fail"


def test_backup_follows_the_settings_file_it_belongs_to(monkeypatch, tmp_path):
    """Regression: the backup path was a module constant computed at IMPORT, so
    anything that later repointed SETTINGS_FILE (a test, a second install, the
    %APPDATA% fallback) kept reading — and overwriting — the backup of the
    ORIGINAL path. A run aimed at a scratch file could clobber the real one."""
    target = tmp_path / "sub" / "s.json"
    target.parent.mkdir()
    monkeypatch.setattr(sm, "SETTINGS_FILE", str(target))
    assert sm._backup_file() == str(target) + ".bak"

    # conftest disables saving for every test; opt in deliberately here.
    save = getattr(sm, "real_save_settings", sm.save_settings)
    save(dict(sm.DEFAULT_SETTINGS, port="COM7"))
    save(dict(sm.DEFAULT_SETTINGS, port="COM8"))      # second save makes a .bak

    written = {p.name for p in tmp_path.rglob("*") if p.is_file()}
    assert written, "nothing was written at all"
    assert all(n.startswith("s.json") for n in written), written
    assert json.loads(target.read_text(encoding="utf-8"))["port"] == "COM8"
    assert json.loads((tmp_path / "sub" / "s.json.bak").read_text(
        encoding="utf-8"))["port"] == "COM7"


# ── the migrators are pure: same contract for junk ──────────────────────
JUNK = [None, 0, "", [], {}, "text", 3.14, True, {"registers": None}]


@pytest.mark.parametrize("junk", JUNK)
def test_normalize_dashboard_accepts_anything(junk):
    """Dashboards come from settings written by older builds — this one is
    deliberately total, since a bad board must not lose the whole project."""
    out = formats.normalize_dashboard(junk)
    assert isinstance(out, dict)
    assert isinstance(out.get("widgets"), list)
    assert isinstance(out.get("links"), list)


# A bare JSON array is the OLDEST profile format, so `[]` is a legitimate
# empty profile rather than junk — it must keep loading forever.
NOT_A_DOCUMENT = [None, 0, "", "text", 3.14, True, {}]


@pytest.mark.parametrize("junk", NOT_A_DOCUMENT)
def test_profile_migrator_rejects_junk_loudly(junk):
    """Not total on purpose: silently returning an empty profile looks exactly
    like data loss to whoever opened the file."""
    with pytest.raises((ValueError, TypeError)):
        formats.migrate_profile(junk)


@pytest.mark.parametrize("junk", NOT_A_DOCUMENT)
def test_project_migrator_rejects_anything_that_is_not_a_project(junk):
    """Regression: `{}` used to migrate into a valid-looking EMPTY project."""
    with pytest.raises((ValueError, TypeError)):
        formats.migrate_project(junk)


def test_empty_array_is_still_a_valid_legacy_profile():
    doc = formats.migrate_profile([])
    assert doc["registers"] == [] and doc["version"] == formats.PROFILE_VERSION


def test_a_project_needs_at_least_one_project_key():
    with pytest.raises(ValueError):
        formats.migrate_project({"unrelated": 1})
    # …but a project carrying only a connection block is fine.
    out = formats.migrate_project({"connection": {"port": "COM3"}})
    assert out["connection"]["port"] == "COM3"
    assert isinstance(out["dashboards"], list) and out["dashboards"]
