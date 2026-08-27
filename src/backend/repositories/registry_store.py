"""Cross-novel registry: data/novels/_registry.sqlite3, one row per novel (id/name/created_at/
is_active/deleted_at). Independent of any single novel's chronos.sqlite3 -- lives outside
active_novel_dir() so the main process can list/switch novels without opening a novel's full
per-novel store."""
from __future__ import annotations

import os
import sqlite3

_REGISTRY_DDL = """
CREATE TABLE IF NOT EXISTS novels (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 0,
    deleted_at TEXT,
    pinned_at TEXT
);
"""


def registry_path() -> str:
    from utils.paths import novels_dir

    return os.path.join(novels_dir(), "_registry.sqlite3")


def get_registry_connection() -> sqlite3.Connection:
    from repositories.migrations import ensure_registry_migrated
    from repositories.sqlite_store import get_connection

    path = registry_path()
    ensure_registry_migrated(path)
    return get_connection(path)
