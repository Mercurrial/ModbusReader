"""The Projects folder (app/projects.py): in the program folder where that
can be written, Documents/ModbusReader elsewhere; the demo's copy goes there
once; the project dialogs open there."""
import os
import sys

import pytest
from PyQt6.QtWidgets import QApplication

from app import projects, settings_manager


@pytest.fixture()
def fresh(monkeypatch, tmp_path):
    """An empty cache and a fake Documents for this test only."""
    monkeypatch.setattr(projects, "_cache", {})
    docs = tmp_path / "Documents" / "ModbusReader"
    monkeypatch.setattr(projects, "documents_dir", lambda: str(docs))
    return docs


def _frozen_windows(monkeypatch, app_dir):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(settings_manager, "APP_DIR", str(app_dir))


def test_from_the_sources_projects_stay_in_documents(fresh, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert projects.projects_dir() == str(fresh)
    assert os.path.isdir(fresh)


def test_an_installed_copy_keeps_them_beside_its_version_folders(fresh, monkeypatch, tmp_path):
    root = tmp_path / "ModbusReader"
    version = root / "app-26.10.4"
    version.mkdir(parents=True)
    (root / "unins000.exe").write_bytes(b"")
    _frozen_windows(monkeypatch, version)
    assert projects.projects_dir() == str(root / "Projects")   # not inside app-26.10.4
    assert os.path.isdir(root / "Projects")


def test_a_portable_copy_keeps_them_beside_the_exe(fresh, monkeypatch, tmp_path):
    exe_dir = tmp_path / "usb"
    exe_dir.mkdir()
    _frozen_windows(monkeypatch, exe_dir)
    assert projects.projects_dir() == str(exe_dir / "Projects")


def test_a_read_only_program_folder_falls_back_to_documents(fresh, monkeypatch, tmp_path):
    _frozen_windows(monkeypatch, tmp_path / "ro")
    real = projects._writable
    monkeypatch.setattr(projects, "_writable",
                        lambda d: False if "ro" in d.split(os.sep) else real(d))
    assert projects.projects_dir() == str(fresh)


def test_linux_and_macos_builds_use_documents(fresh, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(settings_manager, "APP_DIR", str(tmp_path / "squashfs"))
    assert projects.projects_dir() == str(fresh)


def test_the_demo_copy_is_made_once_and_edits_are_kept(fresh, monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "frozen", raising=False)
    src = tmp_path / "demo.mbproj"
    src.write_text("bundled", encoding="utf-8")
    dst = projects.demo_copy(str(src), "Демо")
    assert dst == os.path.join(str(fresh), "Демо.mbproj")
    with open(dst, "w", encoding="utf-8") as f:
        f.write("edited")
    assert projects.demo_copy(str(src), "Демо") == dst
    assert open(dst, encoding="utf-8").read() == "edited"
    assert projects.demo_copy("", "Демо") == ""


def test_the_window_puts_the_demo_there_and_the_dialogs_open_there(monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QFileDialog
    from gui import main_window as gui_main
    folder = tmp_path / "Projects"
    monkeypatch.setattr(projects, "_cache", {"dir": str(folder)})
    w = gui_main.ModernScadaApp()
    try:
        demo = folder / (w.t("demoFileName") + ".mbproj")
        assert demo.exists() and w.settings["projects_seeded"] is True
        demo.unlink()                       # deleted by the user: not brought back
        w._seed_projects()
        assert not demo.exists()

        asked = []
        monkeypatch.setattr(QFileDialog, "getOpenFileName",
                            lambda *a, **k: (asked.append(a[2]), ("", ""))[1])
        monkeypatch.setattr(QFileDialog, "getSaveFileName",
                            lambda *a, **k: (asked.append(a[2]), ("", ""))[1])
        monkeypatch.setattr(gui_main, "themed_input", lambda *a, **k: ("plant", True))
        w._open_project()
        w._open_profile()
        w._save_project_as()
        assert asked[:2] == [str(folder), str(folder)]
        # A new project is offered a folder of its own; cancelled, the
        # folder made for the offer is not left behind.
        assert asked[2] == os.path.join(str(folder), "plant", "plant.mbproj")
        assert not (folder / "plant").exists()
    finally:
        w.close()
        w.deleteLater()
        QApplication.processEvents()


def test_a_project_has_a_home_in_the_root(fresh, monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "frozen", raising=False)
    root = projects.projects_dir()
    # in a folder of its own name: that folder
    own = os.path.join(root, "pump", "pump.mbproj")
    assert projects.project_home(own) == os.path.join(root, "pump")
    # loose in the root, or anywhere else: a folder by its name in the root
    assert projects.project_home(os.path.join(root, "pump.mbproj")) == os.path.join(root, "pump")
    assert projects.project_home(str(tmp_path / "work" / "boiler.mbproj"))         == os.path.join(root, "boiler")
    # no project: the root
    assert projects.project_home("") == root
    m = projects.subfolder(own, projects.MACROS)
    assert m == os.path.join(root, "pump", "macros") and os.path.isdir(m)
    assert projects.new_project_path('a/b:c') == os.path.join(root, "abc", "abc.mbproj")


def test_opening_a_project_makes_its_folders_and_the_macros_use_them(monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QFileDialog
    from gui import main_window as gui_main
    folder = tmp_path / "Projects"
    monkeypatch.setattr(projects, "_cache", {"dir": str(folder)})
    w = gui_main.ModernScadaApp()
    try:
        elsewhere = tmp_path / "work" / "boiler.mbproj"
        elsewhere.parent.mkdir()
        w._set_project(str(elsewhere), "boiler")
        home = folder / "boiler"
        assert (home / "macros").is_dir() and (home / "results").is_dir()
        assert not (elsewhere.parent / "macros").exists()     # the project stays put

        mv = w.macro_view
        assert mv.macros_dir() == str(home / "macros")
        assert os.path.dirname(mv._result_path("csv")) == str(home / "results")
        asked = []
        monkeypatch.setattr(QFileDialog, "getOpenFileName",
                            lambda *a, **k: (asked.append(a[2]), ("", ""))[1])
        monkeypatch.setattr(QFileDialog, "getSaveFileName",
                            lambda *a, **k: (asked.append(a[2]), ("", ""))[1])
        mv._open_script()
        mv._save_script()
        assert asked == [str(home / "macros"), str(home / "macros" / "macro.py")]
    finally:
        w.close()
        w.deleteLater()
        QApplication.processEvents()
