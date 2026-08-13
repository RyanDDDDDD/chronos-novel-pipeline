"""API Gateway application service shared path constant."""
from __future__ import annotations

import sys
from pathlib import Path

from utils.paths import PROJECT_ROOT as _PROJECT_ROOT
from utils.paths import chapters_dir as _chapters_dir
from utils.paths import manifest_path as _manifest_path
from utils.paths import plot_library_path as _plot_library_path

PROJECT_ROOT = Path(_PROJECT_ROOT)

_DEV_DIST_DIR = PROJECT_ROOT / "src" / "frontend" / "dist"
_PYINSTALLER_DIST_DIR = Path(getattr(sys, "_MEIPASS", "")) / "frontend_dist"


def dist_dir() -> Path:
    """
Return the directory that contains the prebuilt frontend (Vite `dist/`).

- Dev: `<repo>/src/frontend/dist`
- PyInstaller: `<_MEIPASS>/frontend_dist` (embedded via PyInstaller datas)
    """
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        return _PYINSTALLER_DIST_DIR
    return _DEV_DIST_DIR


def chapters_dir() -> Path:
    """The chapters directory of the currently active novel (follows the active novel pointer)."""
    return Path(_chapters_dir())


def plot_library_path() -> Path:
    """
The plot_library.json of the currently active novel (follows the active novel pointer)."""
    return Path(_plot_library_path())


def manifest_path() -> str:
    """The manifest path of the current pipeline (modified in utils.paths, following the active pointer)."""
    return _manifest_path()
