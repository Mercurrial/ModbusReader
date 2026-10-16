"""The project is the primary object; the register map is part of one.

These cover the promises the head-bar menu now makes: a project can be
created, saved once and re-saved without re-asking, reopened from the recent
list, and it is always visible WHICH project is open.
"""
import json
import os

import pytest
from PyQt6.QtWidgets import QMenu

from core import formats
from app import settings_manager
from gui.main_window import ModernScadaApp

REGS = [{"addr": 0x10, "name": "Ток", "type": "SHORT", "rw": "RO"}]


@pytest.fixture(autouse=True)
def no_blocking_modals(monkeypatch):
    """Any modal reached by a test hangs the suite forever under offscreen Qt.

    Rather than discover that as a mystery timeout, every dialog fails loudly
    by default; a test that expects one replaces it explicitly.
    """
    def boom(name):
        def _f(*a, **k):
            raise AssertionError(f"unexpected modal dialog: {name}")
        return _f
    monkeypatch.setattr("gui.main_window.themed_message", boom("themed_message"))
    monkeypatch.setattr("gui.main_window.themed_info", boom("themed_info"))
    monkeypatch.setattr("PyQt6.QtWidgets.QFileDialog.getOpenFileName",
                        boom("getOpenFileName"))
    monkeypatch.setattr("PyQt6.QtWidgets.QFileDialog.getSaveFileName",
                        boom("getSaveFileName"))
    monkeypatch.setattr("gui.main_window.themed_input", boom("themed_input"))


@pytest.fixture()
def win(qt_app, tmp_path, monkeypatch):
    monkeypatch.setattr(settings_manager, "SETTINGS_FILE",
                        str(tmp_path / "settings.json"), raising=False)
    w = ModernScadaApp()
    w.resize(1000, 700)
    yield w
    w.logger_view.stop_if_running()
    w.deleteLater()


def _project_file(tmp_path, name="plant"):
    path = str(tmp_path / f"{name}.mbproj")
    formats.dump_project(path, name, dict(settings_manager.DEFAULT_SETTINGS),
                         REGS, [])
    return path


# ═══════════════ identity ═══════════════
def test_the_open_project_is_named_in_the_window(win, tmp_path):
    """Before this the window looked identical inside and outside a project."""
    path = _project_file(tmp_path)
    win._open_project(path)
    assert "plant" in win.btn_profile.text()
    assert win.btn_profile.toolTip() == path


def test_with_no_project_the_button_says_so(win):
    assert win.project_path == ""
    assert win.t("projectNone") in win.btn_profile.text()


def test_the_label_survives_a_language_switch(win, tmp_path):
    win._open_project(_project_file(tmp_path))
    win.ctx.update({"language": "en"})
    win._retranslate_ui()
    assert "plant" in win.btn_profile.text()


# ═══════════════ new project ═══════════════
def test_new_project_clears_the_map_and_the_dashboards(win, tmp_path,
                                                       monkeypatch):
    win._open_project(_project_file(tmp_path))
    assert win.profile_data
    win.dash_view._make_card({"uid": "w", "kind": "value", "reg_id": "0x0010",
                              "x": 0, "y": 0})
    monkeypatch.setattr("gui.main_window.themed_message", lambda *a, **k: 0)  # confirm
    win._new_project()
    assert win.profile_data == []
    assert win.register_table.rowCount() == 0
    assert win.dash_view.cards == {}


def test_new_project_keeps_the_connection_settings(win, tmp_path):
    """They describe the bench, not the project — wiping them is hostile."""
    win.ctx.update({"port": "COM7", "baudrate": 38400})
    win._new_project()               # empty workspace -> no confirmation
    assert win.settings["port"] == "COM7"
    assert win.settings["baudrate"] == 38400


def test_new_project_asks_before_throwing_work_away(win, tmp_path, monkeypatch):
    win._open_project(_project_file(tmp_path))
    asked = []
    monkeypatch.setattr("gui.main_window.themed_message",
                        lambda *a, **k: (asked.append(a), 1)[1])   # 1 = cancel
    win._new_project()
    assert asked, "must confirm when there is a map to lose"
    assert win.profile_data, "cancelling must keep the work"


def test_new_project_on_an_empty_workspace_does_not_nag(win):
    """The autouse fixture makes any dialog here an outright failure."""
    win._new_project()
    assert win.profile_data == []


# ═══════════════ save / save as ═══════════════
def test_saving_a_named_project_overwrites_without_asking(win, tmp_path,
                                                          monkeypatch):
    """Re-prompting for a name on every save is what made a project feel like
    an export step instead of the thing you work in."""
    path = _project_file(tmp_path)
    win._open_project(path)
    monkeypatch.setattr("PyQt6.QtWidgets.QFileDialog.getSaveFileName",
                        lambda *a, **k: pytest.fail("should not ask"))
    win.profile_data = REGS + [{"addr": 0x11, "name": "U", "type": "SHORT"}]
    win._save_project()
    doc = json.loads(open(path, encoding="utf-8").read())
    assert len(doc["profile"]["registers"]) == 2


def test_an_unnamed_project_falls_back_to_save_as(win, tmp_path, monkeypatch):
    target = str(tmp_path / "fresh.mbproj")
    monkeypatch.setattr("gui.main_window.themed_input",
                        lambda *a, **k: ("fresh", True))
    monkeypatch.setattr("PyQt6.QtWidgets.QFileDialog.getSaveFileName",
                        lambda *a, **k: (target, ""))
    win.profile_data = REGS
    win._save_project()
    assert os.path.exists(target)
    assert win.project_path == target


def test_saving_records_the_project_as_recent(win, tmp_path, monkeypatch):
    target = str(tmp_path / "r.mbproj")
    monkeypatch.setattr("gui.main_window.themed_input",
                        lambda *a, **k: ("r", True))
    monkeypatch.setattr("PyQt6.QtWidgets.QFileDialog.getSaveFileName",
                        lambda *a, **k: (target, ""))
    win._save_project_as()
    assert target in win.settings["recent_projects"]


def test_a_failed_save_does_not_claim_the_project_is_saved(win, tmp_path,
                                                           monkeypatch):
    bad = str(tmp_path / "nope" / "deep" / "x.mbproj")
    monkeypatch.setattr("gui.main_window.themed_input",
                        lambda *a, **k: ("x", True))
    monkeypatch.setattr("PyQt6.QtWidgets.QFileDialog.getSaveFileName",
                        lambda *a, **k: (bad, ""))
    monkeypatch.setattr("gui.main_window.themed_info", lambda *a, **k: None)
    win._save_project_as()
    assert win.project_path == "", "an unwritten file must not become the project"


# ═══════════════ recent / reopen ═══════════════
def test_recent_projects_are_deduped_and_newest_first(win, tmp_path):
    a, b = _project_file(tmp_path, "a"), _project_file(tmp_path, "b")
    win._open_project(a)
    win._open_project(b)
    win._open_project(a)
    assert win.settings["recent_projects"][:2] == [a, b]


def test_a_deleted_recent_project_is_reported_and_forgotten(win, tmp_path,
                                                            monkeypatch):
    path = _project_file(tmp_path, "gone")
    win._open_project(path)
    os.remove(path)
    warned = []
    monkeypatch.setattr("gui.main_window.themed_info",
                        lambda *a, **k: warned.append(a))
    win._open_project(path)
    assert warned, "a dead path must say so, not fail silently"
    assert path not in win.settings["recent_projects"]


def test_a_corrupt_project_reports_instead_of_crashing(win, tmp_path,
                                                       monkeypatch):
    path = str(tmp_path / "broken.mbproj")
    open(path, "w", encoding="utf-8").write("{not json at all")
    errors = []
    monkeypatch.setattr("gui.main_window.themed_info",
                        lambda *a, **k: errors.append(a))
    win._open_project(path)
    assert errors
    assert win.project_path == ""


def test_opening_a_project_restores_the_map(win, tmp_path):
    win._open_project(_project_file(tmp_path))
    assert [r["addr"] for r in win.profile_data] == [0x10]
    assert win.register_table.rowCount() == 1


# ═══════════════ the menu itself ═══════════════
def _menu_labels(win, monkeypatch):
    """Capture the menu instead of showing it.

    Labels carry Qt's shortcut column after a tab ("Новый проект\\tCtrl+N"),
    so comparisons use the part before the tab.
    """
    captured = {}

    def fake_exec(self, *a, **k):
        captured["actions"] = list(self.actions())
        captured["labels"] = [act.text().split("\t")[0] for act in self.actions()]
        captured["shortcuts"] = {act.text().split("\t")[0]: act.text().split("\t")[-1]
                                 for act in self.actions() if "\t" in act.text()}
        captured["menus"] = [act.text() for act in self.actions()
                             if act.menu() is not None]
        return None
    monkeypatch.setattr(QMenu, "exec", fake_exec)
    win._open_profile_menu()
    return captured


def test_project_actions_come_before_map_actions(win, monkeypatch):
    """A newcomer should reach for the project first — so it is on top."""
    labels = _menu_labels(win, monkeypatch)["labels"]
    assert labels.index(win.t("projectNew")) < labels.index(win.t("createNew"))
    assert labels.index(win.t("projectOpen")) < labels.index(win.t("openExisting"))


def test_section_captions_are_short_labels_not_sentences(win, monkeypatch):
    """A caption is a signpost. A full sentence set in capitals reads as a
    warning banner; the explanation belongs in the tooltip."""
    labels = _menu_labels(win, monkeypatch)["labels"]
    for key in ("projectSection", "mapSection"):
        caption = win.t(key)
        assert caption in labels
        assert len(caption) <= 20, caption
        assert caption != caption.upper() or len(caption) < 10


def test_the_captions_are_disabled_so_they_read_as_headings(win, monkeypatch):
    acts = _menu_labels(win, monkeypatch)["actions"]
    caption = next(a for a in acts if a.text() == win.t("projectSection"))
    assert not caption.isEnabled()


def test_the_explanation_is_available_as_a_tooltip(win, monkeypatch):
    acts = _menu_labels(win, monkeypatch)["actions"]
    tips = " ".join(a.toolTip() for a in acts)
    assert ".mbproj" in tips and ".json" in tips


def test_the_document_keys_belong_to_the_project(win, monkeypatch):
    """Ctrl+N/O/S act on the thing you are working in — everywhere else in
    desktop software that is the document, and here that is the project."""
    caps = _menu_labels(win, monkeypatch)
    sc = caps["shortcuts"]
    assert sc[win.t("projectNew")] == "Ctrl+N"
    assert sc[win.t("projectOpen")] == "Ctrl+O"
    assert sc[win.t("projectSave")] == "Ctrl+S"
    assert sc[win.t("createNew")] == "Ctrl+Shift+N"


def test_the_bare_register_map_is_still_reachable(win, monkeypatch):
    """The expert path stays — it just stops being the first thing you meet."""
    labels = _menu_labels(win, monkeypatch)["labels"]
    assert win.t("createNew") in labels and win.t("openExisting") in labels


def test_recent_projects_appear_once_there_are_any(win, tmp_path, monkeypatch):
    a = _project_file(tmp_path, "a")
    b = _project_file(tmp_path, "b")
    win._open_project(a)
    win._open_project(b)                      # b is current, a is history
    caps = _menu_labels(win, monkeypatch)
    assert win.t("projectRecent") in caps["menus"]
