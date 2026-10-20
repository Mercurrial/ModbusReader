"""Self-update: the feed, the download, the hand-over, the one question.

Nothing here goes online: urlopen is replaced by fakes. The hand-over is
exercised for real — a stand-in "old app" process holds the target file, the
swap must wait for it and then put the new bytes in place.
"""
import hashlib
import io
import json
import os
import subprocess
import sys
import time
import urllib.error

import pytest
from PyQt6.QtWidgets import QApplication

from app import settings_manager
from core import updater
from app.version import APP_VERSION

EXE_BYTES = b"MZ" + b"\x90" * 5000


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _release_json(ver="99.1.0", **over):
    data = {
        "tag_name": f"v{ver}", "draft": False, "prerelease": False,
        "html_url": f"https://github.com/o/r/releases/tag/v{ver}",
        "body": "## Новое\n- **Чтение блоками**\n- [ссылка](https://x)\n",
        "assets": [
            {"name": "ModbusReader.exe", "size": len(EXE_BYTES),
             "digest": "sha256:" + _sha(EXE_BYTES),
             "browser_download_url": f"https://github.com/o/r/releases/download/v{ver}/ModbusReader.exe"},
            {"name": "ModbusReader_debug.exe", "size": 10, "digest": "sha256:" + "a" * 64,
             "browser_download_url": f"https://github.com/o/r/releases/download/v{ver}/ModbusReader_debug.exe"},
            {"name": "ModbusReader-Setup.exe", "size": 20, "digest": "sha256:" + "b" * 64,
             "browser_download_url": f"https://github.com/o/r/releases/download/v{ver}/ModbusReader-Setup.exe"},
        ],
    }
    data.update(over)
    return data


class _Resp(io.BytesIO):
    def __init__(self, data: bytes, url="https://objects.githubusercontent.com/x"):
        super().__init__(data)
        self._url = url
        self.headers = {"Content-Length": str(len(data))}

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


# ── versions / feed ────────────────────────────────────────────────
def test_versions_compare_as_numbers():
    assert updater.parse_version("v2.10.0") == (2, 10, 0)
    assert updater.parse_version("2.3") == (2, 3, 0)
    assert updater.parse_version("ModbusReader-Setup-2.4.1.exe") == (2, 4, 1)
    assert updater.parse_version("is-7_1_0") == (7, 1, 0)
    assert updater.parse_version("latest") is None
    assert updater.is_newer("2.10.0", "2.9.9")
    assert not updater.is_newer("2.3.0", "2.3.0")
    assert not updater.is_newer("garbage", "2.3.0")


@pytest.mark.parametrize("kind,exe,want", [
    ("portable", "ModbusReader.exe", "ModbusReader.exe"),
    ("portable", "ModbusReader_debug.exe", "ModbusReader_debug.exe"),
    ("portable", "ModbusReader (1).exe", "ModbusReader.exe"),
    ("installed", "ModbusReader.exe", "ModbusReader-Setup.exe"),
])
def test_each_kind_of_copy_gets_its_own_build(kind, exe, want):
    rel = updater.parse_release(_release_json(), kind, exe)
    assert rel.version == "99.1.0" and rel.asset_name == want
    assert len(rel.sha256) == 64


def test_the_installer_keeps_its_name_but_a_download_is_versioned():
    """One permanent link: every release carries ModbusReader-Setup.exe.
    The local copy still gets the version in its name — that is what lets
    cleanup_downloads() tell an old download from a pending one."""
    rel = updater.parse_release(_release_json("99.1.0"), "installed", "ModbusReader.exe")
    assert rel.asset_name == "ModbusReader-Setup.exe"
    assert updater._download_name(rel) == "ModbusReader-Setup-99.1.0.exe"
    old = updater.parse_release(_release_json("99.1.0", assets=[
        {"name": "ModbusReader-Setup-99.1.0.exe", "size": 20, "digest": "sha256:" + "b" * 64,
         "browser_download_url": "https://github.com/o/r/releases/download/v99.1.0/x.exe"}]),
        "installed", "ModbusReader.exe")
    assert old.asset_name == "ModbusReader-Setup-99.1.0.exe"     # the old style still works


def test_release_notes_are_plain_text():
    rel = updater.parse_release(_release_json(), "portable")
    assert rel.notes == "Новое\n• Чтение блоками\n• ссылка"


def test_drafts_and_prereleases_are_not_offered():
    assert updater.parse_release(_release_json(draft=True), "portable") is None
    assert updater.parse_release(_release_json(prerelease=True), "portable") is None


def test_release_without_a_matching_build_still_points_to_its_page():
    data = _release_json(assets=[])
    rel = updater.parse_release(data, "installed")
    assert rel.asset_url == "" and rel.page_url.endswith("v99.1.0")


def test_fetch_offers_only_a_newer_version(monkeypatch):
    seen = {}

    def fake(req, timeout):
        seen["url"] = req.full_url
        return _Resp(json.dumps(_release_json(APP_VERSION)).encode())
    monkeypatch.setattr(updater.urllib.request, "urlopen", fake)
    assert updater.fetch_latest("o/r", "portable", "ModbusReader.exe") is None
    assert seen["url"] == "https://api.github.com/repos/o/r/releases/latest"
    monkeypatch.setattr(updater.urllib.request, "urlopen",
                        lambda req, timeout: _Resp(json.dumps(_release_json()).encode()))
    assert updater.fetch_latest("o/r", "portable", "ModbusReader.exe").version == "99.1.0"


@pytest.mark.parametrize("exc,code", [
    (urllib.error.HTTPError("u", 404, "nf", {}, None), "not_found"),
    (urllib.error.HTTPError("u", 403, "rl", {}, None), "rate_limit"),
    (urllib.error.HTTPError("u", 500, "x", {}, None), "http"),
    (urllib.error.URLError("no route"), "offline"),
    (TimeoutError("slow"), "offline"),
])
def test_fetch_failures_say_why(monkeypatch, exc, code):
    def boom(req, timeout):
        raise exc
    monkeypatch.setattr(updater.urllib.request, "urlopen", boom)
    with pytest.raises(updater.UpdateError) as e:
        updater.fetch_latest("o/r", "portable")
    assert e.value.code == code


def test_garbage_reply_is_a_readable_error(monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlopen",
                        lambda req, timeout: _Resp(b"<html>"))
    with pytest.raises(updater.UpdateError) as e:
        updater.fetch_latest("o/r", "portable")
    assert e.value.code == "bad_reply"


# ── download ───────────────────────────────────────────────────────
def _rel(**over):
    rel = updater.parse_release(_release_json(), "portable", "ModbusReader.exe")
    for k, v in over.items():
        setattr(rel, k, v)
    return rel


def test_download_verifies_and_reports_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlopen",
                        lambda req, timeout: _Resp(EXE_BYTES))
    steps = []
    path = updater.download(_rel(), str(tmp_path), progress=lambda d, t: steps.append((d, t)))
    assert open(path, "rb").read() == EXE_BYTES
    assert os.path.basename(path) == "ModbusReader-99.1.0.exe"
    assert steps[-1] == (len(EXE_BYTES), len(EXE_BYTES))
    assert not [n for n in os.listdir(tmp_path) if n.endswith(".part")]


def test_a_verified_earlier_download_is_reused(tmp_path, monkeypatch):
    (tmp_path / "ModbusReader-99.1.0.exe").write_bytes(EXE_BYTES)

    def never(req, timeout):
        raise AssertionError("downloaded again")
    monkeypatch.setattr(updater.urllib.request, "urlopen", never)
    assert updater.download(_rel(), str(tmp_path)).endswith("ModbusReader-99.1.0.exe")


@pytest.mark.parametrize("body,over,code", [
    (b"MZ" + b"\x00" * 5000, {}, "checksum"),              # wrong bytes
    (EXE_BYTES[:100], {}, "size"),                          # cut short
    (b"PK" + b"\x90" * 5000, {"sha256": _sha(b"PK" + b"\x90" * 5000)}, "bad_reply"),
    (EXE_BYTES, {"sha256": ""}, "checksum"),                # no digest → no install
    (EXE_BYTES, {"asset_url": "http://evil/x.exe"}, "no_build"),
])
def test_a_bad_download_is_refused_and_removed(tmp_path, monkeypatch, body, over, code):
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda req, timeout: _Resp(body))
    with pytest.raises(updater.UpdateError) as e:
        updater.download(_rel(**over), str(tmp_path))
    assert e.value.code == code
    assert os.listdir(tmp_path) == []


def test_download_off_https_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlopen",
                        lambda req, timeout: _Resp(EXE_BYTES, url="http://mirror/x"))
    with pytest.raises(updater.UpdateError):
        updater.download(_rel(), str(tmp_path))
    assert os.listdir(tmp_path) == []


def test_download_can_be_cancelled(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda req, timeout: _Resp(EXE_BYTES))
    with pytest.raises(updater.UpdateError) as e:
        updater.download(_rel(), str(tmp_path), cancelled=lambda: True)
    assert e.value.code == "cancelled" and os.listdir(tmp_path) == []


def test_old_downloads_are_cleaned_up(tmp_path):
    for n in ("ModbusReader-1.0.0.exe", f"ModbusReader-Setup-{APP_VERSION}.exe",
              "ModbusReader-99.0.0.exe", "ModbusReader-99.0.0.exe.part"):
        (tmp_path / n).write_bytes(b"x")
    updater.cleanup_downloads(str(tmp_path))
    assert os.listdir(tmp_path) == ["ModbusReader-99.0.0.exe"]


# ── hand-over ──────────────────────────────────────────────────────
def test_handover_arguments():
    a = updater.handover_args("portable", r"C:\u\new.exe", r"D:\Мои\ModbusReader.exe", [11, 22])
    assert a == [r"C:\u\new.exe", "--finish-update", "--wait", "11,22",
                 "--target", r"D:\Мои\ModbusReader.exe"]
    assert updater._parse_finish_args(a) == ([11, 22], r"D:\Мои\ModbusReader.exe")
    b = updater.handover_args("installed", r"C:\u\setup.exe", "x", [33])
    assert b[0] == r"C:\u\setup.exe" and "/SILENT" in b and "/WAITPID=33" in b


def test_child_env_drops_this_bundle(monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", r"C:\Temp\_MEI1234", raising=False)
    monkeypatch.setenv("QT_PLUGIN_PATH", r"C:\Temp\_MEI1234\PyQt6\plugins")
    env = updater.child_env()
    assert "QT_PLUGIN_PATH" not in env and env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def _holder(path: str, hold_s: float) -> subprocess.Popen:
    """A stand-in for the old app: keeps *path* open, then exits."""
    p = subprocess.Popen([sys.executable, "-c",
                          "import sys, time; f = open(sys.argv[1], 'rb'); "
                          "time.sleep(float(sys.argv[2])); f.close()", path, str(hold_s)])
    time.sleep(0.3)
    return p


def test_finish_update_waits_for_the_old_copy_then_takes_its_place(tmp_path):
    folder = tmp_path / "Рабочий стол's"
    folder.mkdir()
    dst, new = folder / "ModbusReader.exe", tmp_path / "ModbusReader-99.1.0.exe"
    dst.write_bytes(b"OLD")
    new.write_bytes(b"NEW")
    old = _holder(str(dst), 1.5)
    args = updater.handover_args("portable", str(new), str(dst), [old.pid])
    t0 = time.monotonic()
    rc = updater.finish_update(args, source=str(new), relaunch=False)
    assert rc == 0 and dst.read_bytes() == b"NEW"
    assert time.monotonic() - t0 >= 1.0             # it did wait
    assert old.poll() is not None
    assert not (folder / "ModbusReader.exe.new").exists()


def test_finish_update_retries_while_the_file_is_still_held(tmp_path):
    """The one-file bootloader keeps the exe open a moment after the app
    process is gone — the rename is retried, not given up."""
    dst, new = tmp_path / "ModbusReader.exe", tmp_path / "n.exe"
    dst.write_bytes(b"OLD")
    new.write_bytes(b"NEW")
    holder = _holder(str(dst), 1.5)                  # NOT in the wait list
    rc = updater.finish_update(["--wait", "", "--target", str(dst)],
                               source=str(new), relaunch=False)
    holder.wait(10)
    assert rc == 0 and dst.read_bytes() == b"NEW"


def test_finish_update_gives_up_cleanly(tmp_path):
    dst, new = tmp_path / "ModbusReader.exe", tmp_path / "n.exe"
    dst.write_bytes(b"OLD")
    new.write_bytes(b"NEW")
    holder = _holder(str(dst), 3)
    rc = updater.finish_update(["--target", str(dst)], source=str(new),
                               relaunch=False, retries=2)
    holder.wait(10)
    assert rc == 1 and dst.read_bytes() == b"OLD"
    assert not (tmp_path / "ModbusReader.exe.new").exists()
    assert updater.finish_update(["--target", str(new)], source=str(new),
                                 relaunch=False) == 2   # never onto itself


# ── where an installed copy keeps its files ────────────────────────
def test_installed_copy_keeps_settings_in_appdata(tmp_path, monkeypatch):
    app = tmp_path / "Programs" / "ModbusReader"
    app.mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setattr(settings_manager, "_APP_DIR", str(app))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert settings_manager._settings_dir() == str(app)             # portable
    (app / "unins000.exe").write_bytes(b"MZ")
    assert settings_manager.is_installed_dir(str(app))
    assert settings_manager._settings_dir() == str(tmp_path / "Roaming" / "ModbusReader")
    monkeypatch.setattr(sys, "executable", str(app / "ModbusReader.exe"))
    assert updater.install_kind() == "installed"


def test_file_argument_opens_a_project(tmp_path):
    import main
    p = tmp_path / "Линия 3.mbproj"
    p.write_text("{}", encoding="utf-8")
    assert main._file_argument(["ModbusReader.exe", str(p)]) == str(p)
    assert main._file_argument(["ModbusReader.exe", "--finish-update"]) == ""
    assert main._file_argument(["x", str(tmp_path / "missing.mbproj")]) == ""


# ── the window side ────────────────────────────────────────────────
@pytest.fixture()
def win(tmp_path, monkeypatch):
    from gui import main_window as gui_main
    monkeypatch.setattr(settings_manager, "SETTINGS_FILE",
                        str(tmp_path / "settings.json"), raising=False)
    w = gui_main.ModernScadaApp()
    yield w
    w._closing_for_update = True          # no prompts at teardown
    w.close()
    QApplication.processEvents()


def _wait(pred, s=5.0):
    end = time.monotonic() + s
    while time.monotonic() < end and not pred():
        QApplication.processEvents()
        time.sleep(0.01)
    return pred()


def test_a_source_checkout_never_checks_by_itself(win):
    ctl = win.update_ctl
    assert ctl.kind == "source"
    assert not ctl._timer.isActive() and ctl._checker is None


def test_manual_check_offers_the_release_and_skip_is_remembered(win, monkeypatch):
    from gui import update as gui_update
    rel = _rel()
    monkeypatch.setattr(updater, "fetch_latest", lambda **kw: rel)
    shown = []

    def fake_exec(dlg):
        shown.append(dlg)
        dlg.outcome = "skip"
        return 0
    monkeypatch.setattr(gui_update.UpdateDialog, "exec", fake_exec)
    win.update_ctl.check(manual=True)
    assert _wait(lambda: shown)
    assert win.settings["update_skip"] == "99.1.0"
    assert "99.1.0" in win.update_ctl.status_text
    # the automatic check now stays quiet about 99.1.0 …
    win.settings["update_auto"] = True
    win.update_ctl.check(manual=False)
    assert _wait(lambda: win.update_ctl._checker is None)
    assert len(shown) == 1
    # … but a manual one still shows it
    win.update_ctl.check(manual=True)
    assert _wait(lambda: len(shown) == 2)


def test_the_first_check_comes_right_after_start_up():
    from gui import update as gui_update
    assert gui_update.FIRST_CHECK_MS <= 2000


def test_an_automatic_offer_waits_for_the_first_launch_guide(win, monkeypatch):
    """A fresh install checks at once — while the first-launch guide is
    still up. The offer waits for it instead of stacking on top of it."""
    from gui import update as gui_update
    rel = _rel()
    monkeypatch.setattr(updater, "fetch_latest", lambda **kw: rel)
    monkeypatch.setattr(gui_update, "OFFER_RETRY_MS", 20)
    shown = []

    def fake_exec(dlg):
        shown.append(dlg)
        dlg.outcome = "later"
        return 0
    monkeypatch.setattr(gui_update.UpdateDialog, "exec", fake_exec)
    win.settings["update_auto"] = True
    win._guide = object()                      # the guide is open
    win.update_ctl.check(manual=False)
    assert _wait(lambda: win.update_ctl._pending is not None)
    for _ in range(10):                        # several retries: still waiting
        QApplication.processEvents()
        time.sleep(0.03)
    assert shown == [] and win.update_ctl.busy
    win._guide = None                          # closed
    assert _wait(lambda: shown)
    assert win.update_ctl._pending is None and not win.update_ctl.busy


def test_manual_check_answers_when_there_is_nothing_new(win, monkeypatch):
    from gui import update as gui_update
    monkeypatch.setattr(updater, "fetch_latest", lambda **kw: None)
    said = []
    monkeypatch.setattr(gui_update, "themed_info", lambda *a, **k: said.append(a))
    win.update_ctl.check(manual=True)
    assert _wait(lambda: said)
    assert said[0][2] == "success" and APP_VERSION in said[0][4]


def test_failed_check_is_explained_only_when_asked(win, monkeypatch):
    from gui import update as gui_update

    def boom(**kw):
        raise updater.UpdateError("offline", "no route")
    monkeypatch.setattr(updater, "fetch_latest", boom)
    said = []
    monkeypatch.setattr(gui_update, "themed_info", lambda *a, **k: said.append(a))
    win.settings["update_auto"] = True
    win.update_ctl.check(manual=False)
    assert _wait(lambda: win.update_ctl._checker is None)
    assert said == []
    win.update_ctl.check(manual=True)
    assert _wait(lambda: said)
    assert "no route" in said[0][4]


def test_dialog_downloads_and_hands_over(win, monkeypatch, tmp_path):
    from gui import update as gui_update
    rel = _rel()
    monkeypatch.setattr(updater, "can_replace", lambda p: True)
    monkeypatch.setattr(updater, "download",
                        lambda r, progress=None, cancelled=None: (progress(5, 10), str(tmp_path / "n.exe"))[1])
    dlg = gui_update.UpdateDialog(win.ctx, rel, "portable", win)
    assert dlg.btn_go.text() == win.t("updGo")
    dlg.show()
    dlg.btn_go.click()
    assert _wait(lambda: dlg.outcome == "install" and not dlg.isVisible())
    assert dlg.path == str(tmp_path / "n.exe")


def test_dialog_from_source_points_to_the_page(win):
    from gui import update as gui_update
    dlg = gui_update.UpdateDialog(win.ctx, _rel(), "source", win)
    assert dlg.btn_go.text() == win.t("updOpenPage")
    dlg.btn_go.click()
    assert dlg.outcome == "page"


def test_dialog_download_failure_offers_the_page(win, monkeypatch):
    from gui import update as gui_update

    def boom(r, progress=None, cancelled=None):
        raise updater.UpdateError("checksum", "SHA-256 mismatch")
    monkeypatch.setattr(updater, "can_replace", lambda p: True)
    monkeypatch.setattr(updater, "download", boom)
    dlg = gui_update.UpdateDialog(win.ctx, _rel(), "portable", win)
    dlg.show()
    dlg.btn_go.click()
    assert _wait(lambda: dlg.outcome == "page")
    assert dlg.isVisible() and dlg.btn_go.text() == win.t("updOpenPage")
    assert "SHA-256" in dlg.lbl_status.text()
    dlg.close()


def test_quit_for_update_starts_the_new_copy_then_closes(win, monkeypatch):
    started = []
    monkeypatch.setattr(updater, "start_detached", lambda args: started.append(args))
    quits = []
    monkeypatch.setattr(QApplication, "quit", staticmethod(lambda: quits.append(1)))
    win.show()
    assert win.quit_for_update(["new.exe", "--finish-update"])
    assert started == [["new.exe", "--finish-update"]] and quits
    assert not win.isVisible()


def test_quit_for_update_keeps_the_window_if_the_start_fails(win, monkeypatch):
    from gui import main_window as gui_main

    def boom(args):
        raise PermissionError(5, "Access is denied")
    monkeypatch.setattr(updater, "start_detached", boom)
    said = []
    monkeypatch.setattr(gui_main, "themed_info", lambda *a, **k: said.append(a))
    win.show()
    assert not win.quit_for_update(["new.exe"])
    assert win.isVisible() and said and not win._closing_for_update


def test_about_page_has_the_check_button(win, monkeypatch):
    win.resize(1300, 860)
    win.show()
    win._open_settings()
    QApplication.processEvents()
    dlg = win._overlay_page
    dlg.nav.setCurrentRow(dlg._page_keys.index("about"))
    QApplication.processEvents()
    calls = []
    monkeypatch.setattr(win.update_ctl, "check", lambda manual=False: calls.append(manual))
    assert dlg.btn_check_updates.text() == win.t("updCheckNow")
    dlg.btn_check_updates.click()
    assert calls == [True]
    win.update_ctl.status_changed.emit("XYZ")
    assert dlg.lbl_update.text() == "XYZ"
    win._close_overlay()


# ── calendar versions (tools/release.py) ───────────────────────────
def test_next_calendar_version():
    import datetime
    import importlib.util
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "tools", "release.py")
    spec = importlib.util.spec_from_file_location("release_tool", path)
    rel = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rel)
    oct16 = datetime.date(2026, 10, 16)
    assert rel.next_version("2.2.0", oct16) == "26.10.0"        # leaving SemVer
    assert rel.next_version("26.10.0", oct16) == "26.10.1"      # same month
    assert rel.next_version("26.10.4", datetime.date(2026, 11, 2)) == "26.11.0"
    assert rel.next_version("26.12.3", datetime.date(2027, 1, 5)) == "27.1.0"
    # the updater sees every step as newer
    chain = ["2.2.0", "26.10.0", "26.10.1", "26.11.0", "27.1.0"]
    assert all(updater.is_newer(b, a) for a, b in zip(chain, chain[1:]))


def test_update_notes_box_fits_its_text(win):
    """The notes were measured before the label had its width and font —
    the last line sat on the box's bottom edge."""
    from gui import update as gui_update
    rel = _rel(notes="• Чтение блоками: вся карта одним запросом\n"
                     "• Тревоги по порогам прямо в таблице\n"
                     "• Исправлено: Esc в редакторе после Alt+Tab")
    dlg = gui_update.UpdateDialog(win.ctx, rel, "installed", win)
    dlg.show()
    _wait(lambda: False, 0.2)
    sc, lbl = dlg._notes_sc, dlg._notes_lbl
    assert sc.viewport().height() >= lbl.heightForWidth(lbl.width()) + 18
    # …and it is not clipped by its container: the window grew with it
    wrap = dlg._notes_wrap
    assert sc.geometry().bottom() < wrap.height()
    assert dlg.height() >= dlg.sizeHint().height()
    dlg.close()


def test_first_launch_opens_the_demo_but_a_file_wins(tmp_path):
    import main
    p = tmp_path / "plant.mbproj"
    p.write_text("{}", encoding="utf-8")
    assert main.startup_document(["ModbusReader.exe"], first_run=True) == ("demo", "")
    assert main.startup_document(["ModbusReader.exe", str(p)], first_run=True) == ("project", str(p))
    assert main.startup_document(["ModbusReader.exe"], first_run=False) == (None, "")


def test_release_tool_writes_version_and_changelog(tmp_path):
    """tools/release.py turns «## [Не выпущено]» into the release heading,
    adds the tag link and moves the compare link — in a scratch copy."""
    import importlib.util
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "tools", "release.py")
    spec = importlib.util.spec_from_file_location("release_tool2", path)
    rel = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rel)
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "version.py").write_text(
        'APP_VERSION = "26.10.0"\nRELEASE_DATE = "2026-10-16"\n', encoding="utf-8")
    (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "# История\n\n## [Не выпущено]\n\nГотовится к выпуску как 26.10.1.\n\n"
        "### Добавлено\n- что-то\n\n"
        "## [2.2.0] — 2026-10-15\n\n## [2.1.0] — 2026-10-13\n\n"
        "[Не выпущено]: https://github.com/Mercurrial/ModbusReader/compare/v2.2.0...HEAD\n"
        "[2.2.0]: https://github.com/Mercurrial/ModbusReader/releases/tag/v2.2.0\n"
        "[2.1.0]: https://github.com/Mercurrial/ModbusReader/releases/tag/v2.1.0\n",
        encoding="utf-8")
    # One release, one tag: the old tags are about to go, so their links are
    # pinned to the commits (v2.1.0 is already gone here: left as it was).
    tags = {"v2.2.0": "a" * 40}
    rel.apply("26.10.1", "2026-10-20", root=str(tmp_path), resolve=tags.get)
    v = (tmp_path / "app" / "version.py").read_text(encoding="utf-8")
    assert 'APP_VERSION = "26.10.1"' in v and 'RELEASE_DATE = "2026-10-20"' in v
    c = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [26.10.1] — 2026-10-20" in c and "## [Не выпущено]" not in c
    assert "Готовится к выпуску" not in c
    assert "## [26.10.1] — 2026-10-20\n\n### Добавлено" in c
    assert "[26.10.1]: https://github.com/Mercurrial/ModbusReader/releases/tag/v26.10.1" in c
    assert "[2.2.0]: https://github.com/Mercurrial/ModbusReader/tree/" + "a" * 40 in c
    assert "[2.1.0]: https://github.com/Mercurrial/ModbusReader/releases/tag/v2.1.0" in c
    assert "compare/v26.10.1...HEAD" in c
    assert c.index("[26.10.1]:") < c.index("[2.2.0]:")
    rel.apply("26.10.1", "2026-10-21", root=str(tmp_path),     # re-run: new date
              resolve=tags.get)
    c = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [26.10.1] — 2026-10-21" in c and c.count("[26.10.1]:") == 1
    assert "releases/tag/v26.10.1" in c          # the current one keeps its tag link


def test_release_tool_finds_a_tags_commit():
    import importlib.util
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location(
        "release_tool3", os.path.join(root, "tools", "release.py"))
    rel = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rel)
    assert rel.git_commit("no-such-tag-anywhere", root) is None
    head = rel.git_commit("HEAD", root)
    assert head is None or len(head) == 40      # None: a source copy without git
