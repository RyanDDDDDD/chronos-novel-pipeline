# -*- mode: python ; coding: utf-8 -*-
# PyInstaller onedir build for Windows. Despite the filename, this is no longer
# tied to a standalone "portable zip" distribution (that flow was retired in
# favor of the Tauri desktop shell) -- it's now the build recipe for the
# chronos.exe/_internal payload that the Tauri sidecar bundles (see
# scripts/release/build_backend_exe.ps1 and src-tauri/tauri.conf.json).
# Embeds Vite frontend build under frontend_dist/, plus the hooks/ and skills/ asset
# trees (agent prompts + skill markdown), all resolved at runtime via _MEIPASS
# (see utils/paths.py:_bundle_root / api/services/paths.py:dist_dir).

import os

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Spec lives at release/windows/ → repo root is two levels up.
_SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SPEC_DIR, os.pardir, os.pardir))
_FRONTEND_DIST = os.path.join(_PROJECT_ROOT, "src", "frontend", "dist")
_HOOKS_DIR = os.path.join(_PROJECT_ROOT, "hooks")
_SKILLS_DIR = os.path.join(_PROJECT_ROOT, "skills")
_MAIN = os.path.join(_PROJECT_ROOT, "src", "backend", "main.py")

datas = []
if os.path.isdir(_FRONTEND_DIST):
    datas.append((_FRONTEND_DIST, "frontend_dist"))
if os.path.isdir(_HOOKS_DIR):
    datas.append((_HOOKS_DIR, "hooks"))
if os.path.isdir(_SKILLS_DIR):
    datas.append((_SKILLS_DIR, "skills"))

hiddenimports = (
    collect_submodules("api")
    + collect_submodules("engine")
    + collect_submodules("repositories")
)

a = Analysis(
    [_MAIN],
    pathex=[_PROJECT_ROOT, os.path.join(_PROJECT_ROOT, "src", "backend")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name="chronos",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="chronos",
)
