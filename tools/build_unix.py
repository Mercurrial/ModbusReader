# tools/build_unix.py
"""Build the Linux AppImage or the macOS app — on that system.

    python tools/build_unix.py [--appimagetool PATH]

Linux   PyInstaller (ModbusReader_unix.spec) → an AppDir → appimagetool →
        dist/ModbusReader-x86_64.AppImage: one file, chmod +x and run.
macOS   PyInstaller → dist/ModbusReader.app → dist/ModbusReader-macOS-arm64.zip.
        Not notarized (no paid Apple account): the first start needs
        System Settings → Privacy & Security → «Open Anyway».

PyInstaller does not cross-compile, so CI runs this on a Linux and a macOS
runner (.github/workflows/build.yml). Like tools/build_installer.py it
refuses an environment that differs from the pinned versions.
"""
import os
import platform
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from build_installer import environment_drift, pins, run, sha256  # noqa: E402

SPEC = "ModbusReader_unix.spec"

DESKTOP = """[Desktop Entry]
Type=Application
Name=ModbusReader
GenericName=Modbus RTU tool
Comment=Modbus RTU commissioning and monitoring
Exec=ModbusReader %f
Icon=modbusreader
Categories=Development;
Terminal=false
"""

APPRUN = """#!/bin/sh
# AppImage entry point: the PyInstaller folder lives in usr/bin/ModbusReader.
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/ModbusReader/ModbusReader" "$@"
"""


def _pyinstaller():
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", SPEC])


def build_linux(appimagetool: str) -> str:
    _pyinstaller()
    appdir = os.path.join(ROOT, "build", "AppDir")
    shutil.rmtree(appdir, ignore_errors=True)
    os.makedirs(os.path.join(appdir, "usr", "bin"))
    shutil.copytree(os.path.join(ROOT, "dist", "ModbusReader"),
                    os.path.join(appdir, "usr", "bin", "ModbusReader"), symlinks=True)
    with open(os.path.join(appdir, "AppRun"), "w", newline="\n") as f:
        f.write(APPRUN)
    os.chmod(os.path.join(appdir, "AppRun"), 0o755)
    with open(os.path.join(appdir, "modbusreader.desktop"), "w", newline="\n") as f:
        f.write(DESKTOP)
    for name in ("modbusreader.png", ".DirIcon"):
        shutil.copyfile(os.path.join(ROOT, "assets", "app.png"), os.path.join(appdir, name))
    arch = platform.machine() or "x86_64"
    out = os.path.join(ROOT, "dist", f"ModbusReader-{arch}.AppImage")
    if os.path.exists(out):
        os.remove(out)
    print(">", appimagetool, appdir, out, flush=True)
    subprocess.run([appimagetool, appdir, out], cwd=ROOT, check=True,
                   env=dict(os.environ, ARCH=arch))
    return out


def make_icns(out: str):
    """The macOS icon, drawn by the same painter as the Windows one
    (tools/make_icon.py) at every size an .icns holds."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtGui import QGuiApplication
    _app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    from make_icon import paint
    iconset = os.path.join(ROOT, "build", "ModbusReader.iconset")
    shutil.rmtree(iconset, ignore_errors=True)
    os.makedirs(iconset)
    for size in (16, 32, 128, 256, 512):
        paint(size).save(os.path.join(iconset, f"icon_{size}x{size}.png"))
        paint(size * 2).save(os.path.join(iconset, f"icon_{size}x{size}@2x.png"))
    run(["iconutil", "-c", "icns", iconset, "-o", out])


def build_macos() -> str:
    os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
    make_icns(os.path.join(ROOT, "build", "ModbusReader.icns"))
    _pyinstaller()
    app = os.path.join(ROOT, "dist", "ModbusReader.app")
    out = os.path.join(ROOT, "dist", f"ModbusReader-macOS-{platform.machine() or 'arm64'}.zip")
    if os.path.exists(out):
        os.remove(out)
    # ditto keeps the bundle's symlinks, permissions and signature intact.
    run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", app, out])
    return out


def main():
    drift = environment_drift(pins(os.path.join(ROOT, "requirements-dev.txt")))
    if drift:
        sys.exit("The environment differs from the pinned versions:\n  "
                 + "\n  ".join(drift)
                 + "\nRun:  python -m pip install -r requirements-dev.txt")
    if sys.platform.startswith("linux"):
        tool = ""
        if "--appimagetool" in sys.argv:
            tool = sys.argv[sys.argv.index("--appimagetool") + 1]
        tool = tool or os.environ.get("APPIMAGETOOL") or shutil.which("appimagetool") or ""
        if not tool:
            sys.exit("appimagetool not found: pass --appimagetool PATH "
                     "(https://github.com/AppImage/appimagetool/releases)")
        out = build_linux(tool)
    elif sys.platform == "darwin":
        out = build_macos()
    else:
        sys.exit("On Windows the builds are made by tools/build_installer.py")
    print()
    print(f"{os.path.basename(out):34} {os.path.getsize(out) / 1_048_576:7.1f} MB  {sha256(out)}")


if __name__ == "__main__":
    main()
