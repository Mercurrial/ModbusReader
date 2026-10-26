# tools/build_installer.py
"""Build the release files.

    python tools/build_installer.py              installer only
    python tools/build_installer.py --portable   + the one-file exes
    python tools/build_installer.py --portable --only programs
    python tools/build_installer.py --only installer

1. PyInstaller, ModbusReader_setup.spec → dist/ModbusReader/ (one folder)
2. The launcher, installer/launcher/Launcher.cs → build/launcher/ModbusReader.exe
   (tools/build_launcher.py; the C# compiler of .NET Framework 4, part of
   Windows) — the installed ModbusReader.exe, which starts the newest version
3. Inno Setup (ISCC), installer/ModbusReader.iss with /DAppVersion from
   version.py → dist/ModbusReader-Setup.exe
4. (--portable) ModbusReader.spec + ModbusReader_debug.spec → dist/*.exe
5. Prints each file with its size and SHA-256.

"--only programs" stops before 3, "--only installer" is 3 alone, packing
the program and launcher already in dist/ and build/. Between the two the
release build (.github/workflows/build.yml) has the exes signed, so the
installer carries signed files and is signed itself afterwards.

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
sys.path.insert(0, os.path.join(ROOT, "tools"))

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


def _norm(name: str) -> str:
    return name.strip().lower().replace("_", "-").replace(".", "-")


def pins(path: str) -> dict:
    """{package: version} from a requirements file's "name==version" lines,
    following "-r other.txt"."""
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line.startswith("-r "):
                out.update(pins(os.path.join(os.path.dirname(path), line[3:].strip())))
            elif "==" in line:
                name, ver = line.split("==", 1)
                out[_norm(name)] = ver.strip()
    return out


def environment_drift(wanted: dict) -> list[str]:
    """What this Python has that differs from *wanted* ({name: version})."""
    from importlib import metadata
    drift = []
    for name, ver in sorted(wanted.items()):
        try:
            have = metadata.version(name)
        except metadata.PackageNotFoundError:
            have = None
        if have != ver:
            drift.append(f"{name} {have or 'missing'} (pinned {ver})")
    return drift


def main():
    portable = "--portable" in sys.argv
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv[:-1] else ""
    if only not in ("", "programs", "installer"):
        sys.exit(f"--only {only}: expected programs or installer")
    # Only the tested versions may be shipped: a build from a drifted
    # environment would carry libraries no test has seen.
    drift = environment_drift(pins(os.path.join(ROOT, "requirements-dev.txt")))
    if drift:
        sys.exit("The environment differs from the pinned versions:\n  "
                 + "\n  ".join(drift)
                 + "\nRun:  python -m pip install -r requirements-dev.txt")
    iscc = find_iscc() if only != "programs" else ""
    if only != "programs" and not iscc:
        sys.exit("Inno Setup (ISCC.exe) not found — install it first: "
                 "winget install JRSoftware.InnoSetup")
    py = sys.executable
    outputs = []
    if only != "installer":
        run([py, "-m", "PyInstaller", "--noconfirm", "ModbusReader_setup.spec"])
        import build_launcher
        outputs += [os.path.join(ROOT, "dist", "ModbusReader", "ModbusReader.exe"),
                    build_launcher.build()]
    if only != "programs":
        run([iscc, f"/DAppVersion={APP_VERSION}", os.path.join("installer", "ModbusReader.iss")])
        outputs += [os.path.join(ROOT, "dist", "ModbusReader-Setup.exe")]
    if portable and only != "installer":
        for spec in ("ModbusReader.spec", "ModbusReader_debug.spec"):
            run([py, "-m", "PyInstaller", "--noconfirm", spec])
        outputs += [os.path.join(ROOT, "dist", n)
                    for n in ("ModbusReader.exe", "ModbusReader_debug.exe")]
    print()
    for p in outputs:
        name = os.path.relpath(p, ROOT).replace(os.sep, "/")
        print(f"{name:36} {os.path.getsize(p) / 1_048_576:7.1f} MB  {sha256(p)}")


if __name__ == "__main__":
    main()
