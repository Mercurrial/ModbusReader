# app/paths.py
"""Where the program's own files are.

ROOT       the source checkout (the folder with main.py) — or, in a build,
           the folder of the exe
resource() a file shipped WITH the program (assets/, examples/, LICENSE):
           next to the sources, or inside the PyInstaller bundle
           (sys._MEIPASS: the one-file temp dir / the _internal folder)

Modules moved into app/ core/ gui/; anything that used to say
"next to this .py file" means the project root and goes through here.
"""
import os
import sys

if getattr(sys, "frozen", False):
    ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RESOURCES = getattr(sys, "_MEIPASS", ROOT)


def resource(*parts: str) -> str:
    return os.path.join(RESOURCES, *parts)
