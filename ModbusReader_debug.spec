# -*- mode: python ; coding: utf-8 -*-
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
    datas=[('assets/app.png', 'assets'), ('assets/app.ico', 'assets')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
# Start-up splash: a one-file exe unpacks for seconds before Python runs;
# this image is on screen from the first instant (main.py closes it).
splash = Splash('assets/splash.png', binaries=a.binaries, datas=a.datas,
                text_pos=None, minify_script=True, always_on_top=False)

exe = EXE(
    pyz,
    a.scripts,
    splash,
    splash.binaries,
    a.binaries,
    a.datas,
    [],
    name='ModbusReader_debug',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app.ico',
    version=version_info('ModbusReader_debug.exe'),
)
