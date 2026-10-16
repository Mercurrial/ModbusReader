"""Settings must survive crashes and odd launch directories.

Regressions guarded here:
  * atomic save — a failed write never truncates the good file (the old
    open('w')+dump left an empty file that then loaded as defaults: the
    "settings reset themselves" bug);
  * a rolling *.bak is kept and load_settings() recovers from it;
  * a corrupt primary with no backup is preserved as *.corrupt, not silently
    overwritten with defaults.

The real settings_manager.save_settings is monkeypatched to a no-op by the
session-wide conftest guard, so we load a *separate* module instance straight
from the source file to exercise the real read/write without touching the
guard or the app's real app_settings.json.
"""
import os
import json
import importlib.util

import pytest

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "app", "settings_manager.py")


@pytest.fixture()
def sm(tmp_path):
    """A fresh settings_manager pointed at a temp file (real read/write)."""
    spec = importlib.util.spec_from_file_location("settings_manager_real", _SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.SETTINGS_FILE = str(tmp_path / "app_settings.json")
    mod._BACKUP_FILE = mod.SETTINGS_FILE + ".bak"
    return mod


def test_roundtrip(sm):
    sm.save_settings({"theme": "Light", "font_size": 12})
    got = sm.load_settings()
    assert got["theme"] == "Light"
    assert got["font_size"] == 12
    # unspecified keys are filled from defaults
    assert got["lang"] == sm.DEFAULT_SETTINGS["lang"]


def test_backup_created_on_second_save(sm):
    sm.save_settings({"theme": "Dark", "marker": 1})
    sm.save_settings({"theme": "Light", "marker": 2})
    assert os.path.exists(sm._BACKUP_FILE)
    with open(sm._BACKUP_FILE, encoding="utf-8") as f:
        assert json.load(f)["marker"] == 1        # bak holds the PREVIOUS save


def test_recovers_from_backup_when_primary_corrupt(sm):
    sm.save_settings({"theme": "Light", "font_size": 14})   # good primary
    sm.save_settings({"theme": "Light", "font_size": 15})   # -> bak = size 14
    with open(sm.SETTINGS_FILE, "w", encoding="utf-8") as f:
        f.write("{ this is not valid json ]")               # corrupt primary
    got = sm.load_settings()
    assert got["font_size"] == 14                            # recovered from bak


def test_corrupt_without_backup_is_preserved_not_lost(sm):
    with open(sm.SETTINGS_FILE, "w", encoding="utf-8") as f:
        f.write("garbage not json")
    got = sm.load_settings()
    assert got == sm.DEFAULT_SETTINGS                        # safe fallback
    assert os.path.exists(sm.SETTINGS_FILE + ".corrupt")     # bad file kept


def test_failed_write_keeps_old_file_intact(sm):
    sm.save_settings({"theme": "Light", "font_size": 9})
    before = open(sm.SETTINGS_FILE, encoding="utf-8").read()
    # A set isn't JSON-serialisable -> json.dump raises mid-write.
    sm.save_settings({"theme": "Dark", "bad": {1, 2, 3}})
    after = open(sm.SETTINGS_FILE, encoding="utf-8").read()
    assert after == before                                   # untouched
    assert not os.path.exists(sm.SETTINGS_FILE + ".tmp")     # temp cleaned up


def test_empty_file_is_treated_as_corrupt(sm):
    open(sm.SETTINGS_FILE, "w").close()                      # 0-byte file
    got = sm.load_settings()
    assert got == sm.DEFAULT_SETTINGS


def test_settings_path_is_absolute(sm):
    # CWD-independent: the shipped module anchors to an absolute path so
    # launching from any directory hits the same file.
    from app import settings_manager
    assert os.path.isabs(settings_manager.SETTINGS_FILE)
