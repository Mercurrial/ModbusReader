# app/projects.py
"""Where projects live: a «Projects» folder in the program's own folder.

Looking for their projects, people look where the program is (the user,
2026-10-28) — so that is where the open / save dialogs start and where the
demo project's own copy goes:

* an installed copy on Windows: ``<install root>\\Projects`` — beside the
  version folders (``app-<version>``), so an update never touches it. The
  installer creates it writable for every user (an all-users install sits in
  Program Files) and leaves it behind on uninstall: it holds the user's work;
* a portable copy: ``Projects`` beside the exe;
* where the program folder cannot be written — a Linux AppImage, a macOS
  ``.app`` bundle, a run from the sources, a portable exe dropped somewhere
  read-only — ``Documents/ModbusReader``, as before 26.10.4.

The folder is created on first use; the answer is cached for the session
(``reset()`` forgets it — tests).
"""
import os
import shutil
import sys

FOLDER = "Projects"

_cache: dict = {}


def documents_dir() -> str:
    """Documents/ModbusReader (the user's home if there is no Documents)."""
    from PyQt6.QtCore import QStandardPaths
    docs = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.DocumentsLocation) or os.path.expanduser("~")
    return os.path.join(docs, "ModbusReader")


def _writable(d: str) -> bool:
    """The folder exists (made if need be) and a file can be written in it."""
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".write_probe")
        with open(probe, "w") as f:
            f.write("")
        os.remove(probe)
        return True
    except OSError:
        return False


def _in_program_folder() -> str:
    """The Projects folder of this copy of the program, or "" when projects
    do not belong next to it (not a Windows build)."""
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        return ""
    from app import settings_manager as sm
    base = sm.install_root(sm.APP_DIR) or sm.APP_DIR
    return os.path.join(base, FOLDER)


def projects_dir() -> str:
    """The folder the project dialogs open in (see the module docstring)."""
    if "dir" not in _cache:
        d = _in_program_folder()
        if not d or not _writable(d):
            d = documents_dir()
            _writable(d)                     # made if it can be; used either way
        _cache["dir"] = d
    return _cache["dir"]


def reset():
    _cache.clear()


def demo_copy(src: str, name: str) -> str:
    """The user's own copy of the bundled demo project *src*, as
    ``<projects>/<name>.mbproj``: copied once — an existing (maybe edited)
    copy is kept. The bundled file sits inside the program, where a Save
    would write into the next update's way. Returns the copy, or *src* when
    it cannot be made (nowhere to write); "" without a bundled demo."""
    if not src:
        return ""
    dst = os.path.join(projects_dir(), name + ".mbproj")
    try:
        if not os.path.exists(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
    except OSError:
        return src
    return dst
