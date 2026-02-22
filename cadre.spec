# -*- mode: python ; coding: utf-8 -*-
import sys
import os

block_cipher = None

# Ensure we can find the package
sys.path.insert(0, os.path.abspath('.'))

# 1. Collect all Python source files in the root directory.
# The app's bootstrap logic (in main.py) requires these files to exist 
# physically to create the "cadre_player" package at runtime.
py_files = [
    (f, '.') for f in os.listdir('.') 
    if f.endswith('.py') and f not in ['main.py', 'main.pyw', 'cadre.spec']
]

a = Analysis(
    ['main.pyw'],
    pathex=[],
    binaries=[
        # Include MPV DLL. Adjust name if you use libmpv-2.dll
        ('mpv-1.dll', '.'), 
    ],
    datas=[
        ('ui', 'ui'),
        ('locales', 'locales'),
    ] + py_files,  # Add the python source files here
    hiddenimports=['mpv'],  # 2. Force include mpv (it's hidden behind the dynamic import)
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
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
    icon='icons\\icon-64.png',  # <--- CHANGE THIS to your actual .ico file path
)
