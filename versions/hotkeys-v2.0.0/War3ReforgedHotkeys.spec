# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_dynamic_libs

a = Analysis(
    ['war3_hotkey_tool.py'],
    pathex=[],
    binaries=[('tools/war3_hotkey_native_helper.dll', 'tools'), ('tools/war3_hotkey_bridge.dll', 'tools'), ('tools/war3_hotkey_bridge_301.dll', 'tools'), *collect_dynamic_libs('capstone')],
    datas=[('assets/hotkey_icon.ico', 'assets'), ('assets/hotkey_icon.png', 'assets'), ('hotkey_profiles/*.json', 'hotkey_profiles')],
    hiddenimports=[],
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
    a.binaries,
    a.datas,
    [],
    name='War3ReforgedHotkeys-v2.0.0',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/hotkey_icon.ico',
    version='tools/war3_hotkey_200_version_info.txt',
)
