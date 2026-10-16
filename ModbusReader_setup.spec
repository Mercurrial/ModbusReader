# -*- mode: python ; coding: utf-8 -*-
# One-FOLDER build for the installer (installer/ModbusReader.iss):
# dist/ModbusReader/ModbusReader.exe + _internal/. Starts at once — nothing to
# unpack, so no splash — and the installer copies the folder as it is.
# Build both with: python tools/build_installer.py
import os
import sys
from PyInstaller.utils.hooks import collect_submodules

sys.path.insert(0, os.path.abspath(SPECPATH))
from tools.version_resource import version_info  # Explorer → Properties → Details

hiddenimports = ['openpyxl', 'PyQt6.QtSvg']
hiddenimports += collect_submodules('pymodbus')
hiddenimports += collect_submodules('pyqtgraph')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/app.png', 'assets'), ('assets/app.ico', 'assets'),
           ('LICENSE', '.'), ('THIRD_PARTY_LICENSES.md', '.'),   # GPL: the licence travels with the program
           ('examples/demo.mbproj', 'examples')],               # «Демо-проект» on the empty map
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ModbusReader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app.ico',
    version=version_info('ModbusReader.exe'),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ModbusReader',
)
