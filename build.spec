# -*- mode: python ; coding: utf-8 -*-
# build.spec — PyInstaller spec for Reaper Session Generator
# Place this file in your repo root alongside main.py

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# ── Collect data files that PyInstaller misses by default ─────────────────────

whisper_datas = collect_data_files('whisper')
customtkinter_datas = collect_data_files('customtkinter')

all_datas = whisper_datas + customtkinter_datas

# ── Hidden imports that PyInstaller can't auto-detect ─────────────────────────

hidden = [
    'customtkinter',
    'PIL',
    'PIL._tkinter_finder',
    'tkinter',
    'tkinter.ttk',
    'tkinter.filedialog',
    'tkinter.messagebox',
    'whisper',
    'openai',
    'pandas',
    'openpyxl',
    'soundfile',
    'pygame',
    'pygame.mixer',
    'numpy',
    'scipy',
    'scipy.signal',
    'torch',
    'numba',
    'llvmlite',
    'jaraco',
    'jaraco.text',
    'jaraco.functools',
    'jaraco.context',
    'jaraco.collections',
]

hidden += collect_submodules('whisper')
hidden += collect_submodules('torch')
hidden += collect_submodules('jaraco')

# ── Analysis ──────────────────────────────────────────────────────────────────

# Include the ffmpeg binary copied to assets/ by CI (or a local build script).
# It lands in the bundle root so sys._MEIPASS (prepended to PATH in main.py)
# makes it findable by Whisper's subprocess call.
_ffmpeg_binaries = []
if sys.platform == 'win32' and os.path.exists('assets/ffmpeg.exe'):
    _ffmpeg_binaries = [('assets/ffmpeg.exe', '.')]
elif os.path.exists('assets/ffmpeg'):
    _ffmpeg_binaries = [('assets/ffmpeg', '.')]

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=_ffmpeg_binaries,
    datas=all_datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'IPython',
        'jupyter',
        'notebook',
        'sphinx',
        'pytest',
        'setuptools',
        'pip',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── Per-platform EXE / App settings ──────────────────────────────────────────

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ReaperSessionGenerator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,       # False = no terminal window on Windows
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico' if (sys.platform == 'win32' and os.path.exists('assets/icon.ico')) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ReaperSessionGenerator',
)

# ── Mac .app bundle ───────────────────────────────────────────────────────────

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='ReaperSessionGenerator.app',
        icon='assets/icon.icns' if os.path.exists('assets/icon.icns') else None,
        bundle_identifier='com.yourname.reapersessiongenerator',
        info_plist={
            'NSHighResolutionCapable': True,
            'NSMicrophoneUsageDescription': 'Used for audio playback device selection.',
            'CFBundleShortVersionString': '1.0.0',
        },
    )
