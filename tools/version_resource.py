# tools/version_resource.py
"""Windows version resource for the PyInstaller builds.

Without it the exe is anonymous: Explorer → Properties → Details shows no
description, product or version, Task Manager lists the bare file name, and
SmartScreen has nothing to show next to "Unknown publisher". The numbers come
from version.py, so a release can never ship a stale resource.

Used by ModbusReader.spec / ModbusReader_debug.spec:
    from tools.version_resource import version_info
    EXE(..., version=version_info("ModbusReader.exe"))
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.version import APP_VERSION, RELEASE_DATE  # noqa: E402

PRODUCT = "ModbusReader"
DESCRIPTION = "ModbusReader — Modbus RTU commissioning and monitoring"
COMPANY = "Mercurrial"


def _quad(version: str) -> tuple:
    parts = [int(p) for p in version.split(".") if p.isdigit()][:4]
    return tuple(parts + [0] * (4 - len(parts)))


def version_info(filename: str):
    from PyInstaller.utils.win32.versioninfo import (
        VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable,
        StringStruct, VarFileInfo, VarStruct)
    quad = _quad(APP_VERSION)
    year = RELEASE_DATE[:4]
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=quad, prodvers=quad, mask=0x3F, flags=0x0,
                          OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", COMPANY),
                StringStruct("FileDescription", DESCRIPTION),
                StringStruct("FileVersion", APP_VERSION),
                StringStruct("InternalName", PRODUCT),
                StringStruct("LegalCopyright", f"© {year} {COMPANY}"),
                StringStruct("OriginalFilename", filename),
                StringStruct("ProductName", PRODUCT),
                StringStruct("ProductVersion", APP_VERSION),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ])
