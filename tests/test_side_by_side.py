"""Updates beside the running copy (since 26.10.3): a folder per version,
the new one installed in the background, «Перезапустить» = start the
launcher. core/updater's helpers on real folders; the controller and the
card with a stand-in installer (a Python script that writes the progress
file the real one writes)."""
import os
import sys
import time

import pytest
from PyQt6.QtWidgets import QApplication

from app import settings_manager
from core import updater


def _version(root, name, finished=True, exe=True):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    if exe:
        open(os.path.join(d, "ModbusReader.exe"), "wb").close()
    if finished:
        open(os.path.join(d, ".installed"), "w").close()
    return d


def _pump(seconds=0.0):
    end = time.monotonic() + seconds
    while True:
        QApplication.processEvents()
        if time.monotonic() >= end:
            break
        time.sleep(0.01)


def _wait(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return cond()


# ── where the program lives ───────────────────────────────────────────
def test_install_root_sees_the_version_folder(tmp_path):
    root = tmp_path / "ModbusReader"
    v = root / "app-26.10.3"
    v.mkdir(parents=True)
    assert settings_manager.install_root(str(v)) == ""          # no uninstaller yet
    (root / "unins000.exe").write_bytes(b"")
    assert settings_manager.install_root(str(v)) == str(root)
    assert settings_manager.is_installed_dir(str(v))
    assert settings_manager.install_root(str(root)) == str(root)   # ≤ 26.10.2 layout
    other = tmp_path / "ModbusReader" / "backup"
    other.mkdir()
    assert settings_manager.install_root(str(other)) == ""      # only app-* folders


def test_finished_versions_in_order(tmp_path):
    root = str(tmp_path)
    _version(root, "app-26.10.3")
    _version(root, "app-26.10.10")
    _version(root, "app-26.11.0", finished=False)            # being installed
    _version(root, "app-26.9.9", exe=False)                  # broken
    _version(root, "app-notes")
    names = [os.path.basename(d) for _v, d in updater.version_dirs(root)]
    assert names == ["app-26.10.3", "app-26.10.10"]
    assert updater.newest_installed(root) == "26.10.10"
    assert updater.newest_installed(str(tmp_path / "nothing")) == ""


def test_cleanup_removes_only_older_versions(tmp_path):
    root = str(tmp_path)
    old = _version(root, "app-26.10.2")
    cur = _version(root, "app-26.10.3")
    new = _version(root, "app-26.10.4")
    removed = updater.cleanup_old_versions(root, cur)
    assert removed == ["app-26.10.2"]
    assert not os.path.exists(old) and os.path.exists(cur) and os.path.exists(new)


def test_cleanup_leaves_a_folder_in_use(tmp_path, monkeypatch):
    """Windows refuses to rename a folder a running program uses: that
    folder stays (untouched) for the next start."""
    root = str(tmp_path)
    old = _version(root, "app-26.10.2")
    cur = _version(root, "app-26.10.3")
    real = os.rename

    def refuse(src, dst):
        if src == old:
            raise PermissionError(32, "in use")
        return real(src, dst)
    monkeypatch.setattr(updater.os, "rename", refuse)
    assert updater.cleanup_old_versions(root, cur) == []
    assert os.path.isfile(os.path.join(old, "ModbusReader.exe"))


def test_cleanup_finishes_an_interrupted_removal(tmp_path):
    root = str(tmp_path)
    cur = _version(root, "app-26.10.3")
    left = _version(root, "app-26.10.1.removing-1234")
    updater.cleanup_old_versions(root, cur)
    assert not os.path.exists(left)


def test_all_users_or_just_me(tmp_path):
    root = str(tmp_path / "ModbusReader")
    assert updater.installed_for_all_users(root, lambda: root + "\\")is False
    assert updater.installed_for_all_users(root, lambda: r"C:\Other\ModbusReader") is True
    assert updater.installed_for_all_users(root, lambda: "") is True


def test_background_install_arguments():
    args = updater.background_install_args(r"C:\dl\Setup.exe", r"C:\p.txt", r"C:\l.log", False)
    assert args[0] == r"C:\dl\Setup.exe"
    for flag in ("/VERYSILENT", "/NOLAUNCH", "/NOCLOSEAPPLICATIONS", "/NOCANCEL",
                 "/CURRENTUSER", r"/PROGRESS=C:\p.txt", r"/LOG=C:\l.log"):
        assert flag in args
    assert "/ALLUSERS" in updater.background_install_args("s", "p", "l", True)


def test_progress_file(tmp_path):
    f = str(tmp_path / "p.txt")
    assert updater.read_progress(f) == ("", 0.0)
    open(f, "w").write("progress 50 200")
    assert updater.read_progress(f) == ("progress", 0.25)
    open(f, "w").write("done C:\\x")
    assert updater.read_progress(f) == ("done", 1.0)
    open(f, "w").write("progress x y")
    assert updater.read_progress(f) == ("", 0.0)


def test_the_installer_script_keeps_its_promises():
    iss = open(os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "installer", "ModbusReader.iss"), encoding="utf-8-sig").read()
    assert 'DestDir: "{app}\\{#VersionDir}"' in iss                # a folder per version
    post = iss[iss.index("CurStep = ssPostInstall"):]
    assert r"SaveStringToFile(ExpandConstant('{app}\{#VersionDir}\.installed')" in post
    assert 'Name: "{app}\\{#VersionDir}\\.installed"' in iss        # cleared first
    assert "AppUserModelID" in iss and "PROGRESS" in iss
    assert "WizardStyle=modern dynamic" in iss and "hidebevels" in iss
    assert "usPostUninstall" in iss                                 # every version goes


# ── the app: background update → «Обновить до …» → restart ───────────
FAKE_INSTALLER = r'''
import sys, time
progress = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("/PROGRESS="))
for done in (10, 60, 100):
    open(progress, "w").write(f"progress {done} 100")
    time.sleep(0.05)
open(progress, "w").write("done C:\\x")
sys.exit(int(sys.argv[1]))
'''


@pytest.fixture
def win(tmp_path, monkeypatch):
    from gui import main_window as gui_main
    monkeypatch.setattr(settings_manager, "SETTINGS_FILE", str(tmp_path / "settings.json"),
                        raising=False)
    w = gui_main.ModernScadaApp()
    yield w
    w.update_ctl.shutdown()
    w.deleteLater()


def _side(ctl, tmp_path, monkeypatch, exit_code=0, all_users=False):
    """Make the controller believe it runs from a version folder, with a
    stand-in installer and no network."""
    root = tmp_path / "ModbusReader"
    root.mkdir(exist_ok=True)
    ctl.side = {"root": str(root), "all_users": all_users}
    script = tmp_path / "fake_setup.py"
    script.write_text(FAKE_INSTALLER, encoding="utf-8")
    monkeypatch.setattr(updater, "downloads_dir", lambda: str(tmp_path / "dl"))
    monkeypatch.setattr(updater, "background_install_args",
                        lambda setup, progress, log, all_users:
                        [sys.executable, str(script), str(exit_code), f"/PROGRESS={progress}"])
    monkeypatch.setattr(updater, "download", lambda rel, **kw: str(tmp_path / "Setup.exe"))
    return root


def test_a_background_update_ends_with_the_rail_button(win, tmp_path, monkeypatch):
    ctl = win.update_ctl
    _side(ctl, tmp_path, monkeypatch)
    offered = []
    monkeypatch.setattr(ctl, "offer", lambda rel, mode="offer", path="": offered.append(mode))
    rel = updater.Release("26.99.1", "notes", "https://github.com/x")
    ctl._background(rel)
    assert _wait(lambda: ctl._ready is not None, 15)
    assert offered == ["ready"]
    rail = win.nav_rail
    assert rail.btn_update.isVisibleTo(rail)
    assert "26.99.1" in rail.btn_update.text()
    assert not ctl.busy


def test_a_failed_background_install_says_so(win, tmp_path, monkeypatch):
    ctl = win.update_ctl
    _side(ctl, tmp_path, monkeypatch, exit_code=5)
    monkeypatch.setattr(ctl, "offer", lambda *a, **k: pytest.fail("no offer"))
    ctl._background(updater.Release("26.99.1", "", ""))
    assert _wait(lambda: ctl._runner is None and ctl._bg is None, 15)
    _pump(0.3)
    assert ctl._ready is None and "5" in ctl.status_text
    assert not win.nav_rail.btn_update.isVisibleTo(win.nav_rail)


def test_all_users_asks_once_before_installing(win, tmp_path, monkeypatch):
    ctl = win.update_ctl
    _side(ctl, tmp_path, monkeypatch, all_users=True)
    offered = []
    monkeypatch.setattr(ctl, "offer",
                        lambda rel, mode="offer", path="": offered.append((mode, path)))
    ctl._background(updater.Release("26.99.1", "", ""))
    assert _wait(lambda: offered, 10)
    assert offered[0][0] == "install" and offered[0][1].endswith("Setup.exe")
    assert ctl._runner is None                        # nothing ran without asking


def test_an_already_installed_version_is_not_installed_again(win, tmp_path, monkeypatch):
    ctl = win.update_ctl
    root = _side(ctl, tmp_path, monkeypatch)
    _version(str(root), "app-26.99.1")
    monkeypatch.setattr(ctl, "offer", lambda *a, **k: None)
    ctl._background(updater.Release("26.99.1", "", ""))
    assert ctl._ready is not None and ctl._bg is None and ctl._runner is None


def test_restart_starts_the_launcher(win, tmp_path, monkeypatch):
    ctl = win.update_ctl
    root = _side(ctl, tmp_path, monkeypatch)
    started = []
    monkeypatch.setattr(win, "quit_for_update", lambda args: started.append(args) or True)
    assert ctl.restart()
    assert started == [[os.path.join(str(root), "ModbusReader.exe")]]
    ctl.side = None
    assert ctl.restart() is False


def test_the_card_installs_and_turns_into_restart(win, tmp_path, monkeypatch):
    from gui.update import UpdateDialog
    ctl = win.update_ctl
    _side(ctl, tmp_path, monkeypatch)
    rel = updater.Release("26.99.1", "Что нового", "https://github.com/x",
                          "ModbusReader-Setup.exe", "https://github.com/x/Setup.exe",
                          10, "0" * 64)
    dlg = UpdateDialog(win.ctx, rel, "installed", win, mode="install",
                       side=ctl.side, path=str(tmp_path / "Setup.exe"))
    assert dlg.btn_go.text() == win.t("updInstallGo")
    dlg.show()
    dlg._go()
    assert dlg._runner is not None and not dlg.btn_later.isEnabled()
    dlg.reject()                                      # Esc cannot stop it
    assert dlg.isVisible()
    assert _wait(lambda: dlg.installed, 15)
    assert dlg.mode == "ready" and dlg.btn_go.text() == win.t("updRestart")
    assert dlg.lbl_title.text() == win.t("updReadyTitle").format(ver="26.99.1")
    dlg._go()
    assert dlg.outcome == "restart"


def test_the_ready_card_from_the_rail(win, tmp_path, monkeypatch):
    ctl = win.update_ctl
    _side(ctl, tmp_path, monkeypatch)
    ctl._set_ready(updater.Release("26.99.1", "", ""))
    shown = []
    monkeypatch.setattr(ctl, "offer", lambda rel, mode="offer", path="": shown.append(mode))
    win.nav_rail.btn_update.click()
    assert shown == ["ready"]
