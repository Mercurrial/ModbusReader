# -*- mode: python ; coding: utf-8 -*-
# Linux and macOS builds: the program as one folder; on macOS wrapped into
# ModbusReader.app. PyInstaller does not cross-compile, so each is built on
# its own system — by tools/build_unix.py, which CI runs on Linux and macOS
# runners (.github/workflows/build.yml). Windows: the other three .spec files.
import os
import sys
from PyInstaller.utils.hooks import collect_submodules

sys.path.insert(0, os.path.abspath(SPECPATH))
from app.version import APP_VERSION  # noqa: E402

hiddenimports = ['openpyxl', 'PyQt6.QtSvg']
# Not pyqtgraph.examples: unused, and importing them (which this collection
# does) opens Qt windows — on a Linux build machine without a screen that
# aborts the whole build.
hiddenimports += collect_submodules(
    'pyqtgraph', filter=lambda name: not name.startswith('pyqtgraph.examples'))


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/app.png', 'assets'),
           ('LICENSE', '.'), ('THIRD_PARTY_LICENSES.md', '.'),   # GPL: the licence travels with the program
           ('examples/demo.mbproj', 'examples'),                # «Демо-проект» on the empty map
           ('examples/demo_en.mbproj', 'examples')],            # …and its English twin
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
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,          # ad-hoc: no paid Apple certificate
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='ModbusReader',
)

if sys.platform == 'darwin':
    icns = os.path.join(SPECPATH, 'build', 'ModbusReader.icns')   # tools/build_unix.py
    app = BUNDLE(
        coll,
        name='ModbusReader.app',
        icon=icns if os.path.exists(icns) else None,
        bundle_identifier='io.github.mercurrial.modbusreader',
        version=APP_VERSION,
        info_plist={
            'CFBundleDisplayName': 'ModbusReader',
            'CFBundleShortVersionString': APP_VERSION,
            'CFBundleVersion': APP_VERSION,
            'NSHumanReadableCopyright': '© 2026 Mercurrial · GPL-3.0-or-later',
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '12.0',
        },
    )
