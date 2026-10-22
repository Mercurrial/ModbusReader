# tools/build_launcher.py
"""Build the launcher (installer/launcher/Launcher.cs) → build/launcher/ModbusReader.exe.

The C# compiler of .NET Framework 4 ships with every Windows 10/11
(C:\\Windows\\Microsoft.NET\\Framework64\\v4.0.30319\\csc.exe) — nothing to
install. The exe gets the app's icon and the version from app/version.py.
Called by tools/build_installer.py; run it alone to rebuild just the launcher.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.version import APP_VERSION, RELEASE_DATE  # noqa: E402

OUT_DIR = os.path.join(ROOT, "build", "launcher")
OUT = os.path.join(OUT_DIR, "ModbusReader.exe")


def find_csc() -> str:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    for fw in ("Framework64", "Framework"):
        path = os.path.join(windir, "Microsoft.NET", fw, "v4.0.30319", "csc.exe")
        if os.path.isfile(path):
            return path
    return ""


def _quad(version: str) -> str:
    parts = [p for p in version.split(".") if p.isdigit()][:4]
    return ".".join(parts + ["0"] * (4 - len(parts)))


def assembly_info() -> str:
    year = RELEASE_DATE[:4]
    q = _quad(APP_VERSION)
    return (
        "using System.Reflection;\n"
        '[assembly: AssemblyTitle("ModbusReader")]\n'
        '[assembly: AssemblyDescription("ModbusReader — starts the installed version")]\n'
        '[assembly: AssemblyCompany("Mercurrial")]\n'
        '[assembly: AssemblyProduct("ModbusReader")]\n'
        f'[assembly: AssemblyCopyright("\\u00a9 {year} Mercurrial")]\n'
        f'[assembly: AssemblyVersion("{q}")]\n'
        f'[assembly: AssemblyFileVersion("{q}")]\n'
        f'[assembly: AssemblyInformationalVersion("{APP_VERSION}")]\n'
    )


def build() -> str:
    csc = find_csc()
    if not csc:
        sys.exit("csc.exe (.NET Framework 4) not found")
    os.makedirs(OUT_DIR, exist_ok=True)
    info = os.path.join(OUT_DIR, "AssemblyInfo.cs")
    with open(info, "w", encoding="utf-8") as f:
        f.write(assembly_info())
    args = [csc, "/nologo", "/target:winexe", "/optimize+", "/platform:anycpu",
            "/r:System.Windows.Forms.dll",
            "/win32icon:" + os.path.join(ROOT, "assets", "app.ico"),
            "/out:" + OUT,
            os.path.join(ROOT, "installer", "launcher", "Launcher.cs"), info]
    print(">", " ".join(args), flush=True)
    subprocess.run(args, check=True)
    return OUT


if __name__ == "__main__":
    print(build())
