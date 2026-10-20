# tools/build_installer.py
"""Build the release files.

    python tools/build_installer.py              installer only
    python tools/build_installer.py --portable   + the one-file exes

1. PyInstaller, ModbusReader_setup.spec → dist/ModbusReader/ (one folder)
2. Inno Setup (ISCC), installer/ModbusReader.iss with /DAppVersion from
   version.py → dist/ModbusReader-Setup.exe
3. (--portable) ModbusReader.spec + ModbusReader_debug.spec → dist/*.exe
4. Prints each file with its size and SHA-256.

The release itself (tag vX.Y.Z, not a pre-release) must carry exactly these
asset names — updater.py picks the build by name, and the installer's name
never changes, so one link always downloads the latest:
    ModbusReader-Setup.exe         installed copies
    ModbusReader.exe               portable copies
    ModbusReader_debug.exe         the console build
GitHub stores a SHA-256 per asset at upload; the app refuses a download that
does not match it.
"""
import hashlib
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.version import APP_VERSION  # noqa: E402


def find_iscc() -> str:
    found = shutil.which("ISCC") or shutil.which("iscc")
    if found:
        return found
    import glob
    roots = [os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
             os.environ.get("ProgramFiles", r"C:\Program Files"),
             os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")]
    # Inno Setup 6 or 7 — newest first.
    for root in roots:
        for c in sorted(glob.glob(os.path.join(root, "Inno Setup *", "ISCC.exe")),
                        reverse=True):
            return c
    return ""


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(args: list[str]):
    print(">", " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


def main():
    portable = "--portable" in sys.argv
    iscc = find_iscc()
    if not iscc:
        sys.exit("Inno Setup (ISCC.exe) not found — install it first: "
                 "winget install JRSoftware.InnoSetup")
    py = sys.executable
    run([py, "-m", "PyInstaller", "--noconfirm", "ModbusReader_setup.spec"])
    run([iscc, f"/DAppVersion={APP_VERSION}", os.path.join("installer", "ModbusReader.iss")])
    outputs = [os.path.join(ROOT, "dist", "ModbusReader-Setup.exe")]
    if portable:
        for spec in ("ModbusReader.spec", "ModbusReader_debug.spec"):
            run([py, "-m", "PyInstaller", "--noconfirm", spec])
        outputs += [os.path.join(ROOT, "dist", n)
                    for n in ("ModbusReader.exe", "ModbusReader_debug.exe")]
    print()
    for p in outputs:
        print(f"{os.path.basename(p):34} {os.path.getsize(p) / 1_048_576:7.1f} MB  {sha256(p)}")


if __name__ == "__main__":
    main()
