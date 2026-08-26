"""Cross-novel registry: data/novels/_registry.sqlite3, one row per novel (id/name/created_at/
is_active/deleted_at). Independent of any single novel's chronos.sqlite3 -- lives outside
active_novel_dir() so the main process can list/switch novels without opening a novel's full
per-novel store (see spec's Subprocess Worker prerequisite rationale)."""
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


def _ensure_pinned_column(conn: sqlite3.Connection) -> None:
    """Migration for registries created before pinned_at existed. SQLite has no ADD COLUMN
    IF NOT EXISTS, so check PRAGMA table_info first -- idempotent, safe on every connection open."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(novels)").fetchall()}
    if "pinned_at" not in cols:
        conn.execute("ALTER TABLE novels ADD COLUMN pinned_at TEXT")
        conn.commit()


def get_registry_connection() -> sqlite3.Connection:
    from repositories.sqlite_store import get_connection

    conn = get_connection(registry_path(), _REGISTRY_DDL)
    _ensure_pinned_column(conn)
    return conn
