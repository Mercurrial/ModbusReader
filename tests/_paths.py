"""Where the program's sources are, for the tests that read them (i18n and
icon guards, no-native-dialog checks)."""
import glob
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGES = ("app", "core", "gui")


def source_files() -> list:
    """main.py and every module of the app/ core/ gui/ packages."""
    files = [os.path.join(ROOT, "main.py")]
    for pkg in PACKAGES:
        files += sorted(glob.glob(os.path.join(ROOT, pkg, "*.py")))
    return files
