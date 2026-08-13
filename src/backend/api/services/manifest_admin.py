"""Manifest editor verification and Agent directory enumeration."""
from __future__ import annotations

from pathlib import Path

from utils.paths import AGENTS_DIR


def agent_names() -> set[str]:
    return {
        p.name for p in Path(AGENTS_DIR).iterdir()
        if p.is_dir() and not p.name.startswith("_")
    }
