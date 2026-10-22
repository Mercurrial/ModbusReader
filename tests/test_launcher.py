"""The launcher (installer/launcher/Launcher.cs) on a real folder layout.

The "program" in each version folder is a stub compiled here that writes
down where it ran and with what arguments — so the test sees exactly which
version the launcher picked and what it passed on. Windows only (the C#
compiler of .NET Framework 4 is part of Windows)."""
import json
import os
import shutil
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import build_launcher  # noqa: E402

STUB = r'''
using System; using System.IO;
static class Stub {
    static string Esc(string s) { return s.Replace("\\", "\\\\").Replace("\"", "\\\""); }
    static void Main(string[] args) {
        var parts = new System.Collections.Generic.List<string>();
        foreach (var a in args) parts.Add("\"" + Esc(a) + "\"");
        File.WriteAllText(Path.Combine(Environment.CurrentDirectory, "..", "ran.json"),
            "{\"dir\": \"" + Esc(Environment.CurrentDirectory) + "\", \"args\": [" +
            string.Join(", ", parts) + "]}");
    }
}
'''


@pytest.fixture(scope="module")
def binaries(tmp_path_factory):
    csc = build_launcher.find_csc()
    if not csc:
        pytest.skip("no C# compiler")
    out = tmp_path_factory.mktemp("bin")
    launcher = build_launcher.build()
    src = out / "Stub.cs"
    src.write_text(STUB, encoding="utf-8")
    stub = out / "stub.exe"
    subprocess.run([csc, "/nologo", "/langversion:5", "/target:winexe", f"/out:{stub}", str(src)],
                   check=True, capture_output=True)
    return launcher, str(stub)


def _layout(tmp_path, binaries, versions):
    launcher, stub = binaries
    root = tmp_path / "ModbusReader"
    root.mkdir()
    shutil.copy(launcher, root / "ModbusReader.exe")
    for name, finished in versions:
        d = root / name
        d.mkdir()
        shutil.copy(stub, d / "ModbusReader.exe")
        if finished:
            (d / ".installed").write_text("")
    return root


def _run(root, *args):
    ran = root / "ran.json"
    if ran.exists():
        ran.unlink()
    code = subprocess.run([str(root / "ModbusReader.exe"), *args], timeout=30).returncode
    deadline = time.monotonic() + 15
    while not ran.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    return code, (json.loads(ran.read_text(encoding="utf-8")) if ran.exists() else None)


def test_the_newest_finished_version_is_started(tmp_path, binaries):
    root = _layout(tmp_path, binaries, [("app-26.10.2", True), ("app-26.10.10", True),
                                        ("app-26.9.30", True)])
    code, ran = _run(root)
    assert code == 0 and os.path.basename(ran["dir"]) == "app-26.10.10"   # numbers, not text


def test_a_version_still_being_installed_is_not_started(tmp_path, binaries):
    root = _layout(tmp_path, binaries, [("app-26.10.2", True), ("app-26.10.3", False)])
    code, ran = _run(root)
    assert os.path.basename(ran["dir"]) == "app-26.10.2"


def test_folders_that_are_not_versions_are_ignored(tmp_path, binaries):
    root = _layout(tmp_path, binaries, [("app-26.10.2", True), ("app-notes", True),
                                        ("backup-26.11.0", True)])
    _code, ran = _run(root)
    assert os.path.basename(ran["dir"]) == "app-26.10.2"


def test_the_command_line_is_passed_on_intact(tmp_path, binaries):
    root = _layout(tmp_path, binaries, [("app-26.10.2", True)])
    args = [r"C:\Мои проекты\стенд 1.mbproj", "--flag", 'say "hi"', "trailing\\", ""]
    _code, ran = _run(root, *args)
    assert ran["args"] == args


def test_no_version_is_an_error_not_a_hang(tmp_path, binaries):
    root = _layout(tmp_path, binaries, [("app-26.10.2", False)])
    env = dict(os.environ, MODBUSREADER_LAUNCHER_QUIET="1")   # no message box
    code = subprocess.run([str(root / "ModbusReader.exe")], env=env, timeout=30).returncode
    assert code == 2 and not (root / "ran.json").exists()
