# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
sys.path.insert(0, os.path.abspath('.'))

# Optional portable helper binaries (prefer vendor/, fallback to project root)
def _optional_binary(name):
    candidates = [
        os.path.join('vendor', name),
        name,
    ]
    for src in candidates:
        if os.path.exists(src):
            return (src, '.')
    return None

optional_bins = []
for tool_name in ('deno.exe', 'yt-dlp.exe', 'bsdtar.exe', 'tar.exe'):
    item = _optional_binary(tool_name)
    if item:
        optional_bins.append(item)

# Collect only necessary python source files
py_files = [
    (f, '.') for f in os.listdir('.') 
    if f.endswith('.py') and f not in ['main.py', 'main.pyw', 'cadre.spec']
]

a = Analysis(
    ['main.pyw'],
    pathex=[],
    binaries=[('mpv-1.dll', '.')] + optional_bins,
    datas=[
        ('ui', 'ui'),
        ('locales', 'locales'),
        ('icons\\icon.ico', 'icons'),
    ] + py_files,
    hiddenimports=['mpv', 'yt_dlp'] + collect_submodules('send2trash'),
    excludes=[
        'PySide6.QtWebEngine', 
        'PySide6.QtWebEngineCore', 
        'PySide6.QtQuick', 
        'PySide6.QtSql', 
        'PySide6.QtQml',
        'PySide6.QtCharts',
        'PySide6.Qt3D',
        'tkinter', 
        'unittest'
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Strip out large Qt translation files to save ~15MB
a.datas = [p for p in a.datas if not (p[0].endswith('.qm') and 'translations\\qt' in p[0])]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],  # Do not bundle binaries in the EXE (for Directory Mode)
    exclude_binaries=True,
    name='CadrePlayer',
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
    icon='icons\\icon.ico',
)

a_updater = Analysis(
    ['updater.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    excludes=[
        'PySide6',
        'PySide6.QtWebEngine',
        'PySide6.QtWebEngineCore',
        'PySide6.QtQuick',
        'PySide6.QtSql',
        'PySide6.QtQml',
        'PySide6.QtCharts',
        'PySide6.Qt3D',
        'mpv',
        'yt_dlp',
        'tkinter',
        'unittest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz_updater = PYZ(a_updater.pure, a_updater.zipped_data, cipher=block_cipher)

exe_updater = EXE(
    pyz_updater,
    a_updater.scripts,
    [],
    exclude_binaries=True,
    name='CadrePlayerUpdater',
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
    icon='icons\\icon.ico',
)

coll = COLLECT(
    exe,
    exe_updater,
    a.binaries,
    a.zipfiles,
    a.datas,
    a_updater.binaries,
    a_updater.zipfiles,
    a_updater.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CadrePlayer',
    contents_directory='internal',
)
