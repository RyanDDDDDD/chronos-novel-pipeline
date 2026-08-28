"""Structured storage layer: per-novel SQLite IO + archive memory cache.

DEPRECATED: shim for not-yet-migrated modules (vector store, relationship graph,
character timeline, session record, chapter shift, etc.), removed in batch 3.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from typing import Any

from utils.paths import novel_db_path

from repositories.document_store import (
    get_document,
    get_document_with_version,
    save_document,
    save_document_if_version_matches,
)
from repositories.engine import dispose_engine, reset_archive_cache

_WRITE_LOCK = threading.Lock()


def _character_id(conn: sqlite3.Connection, name: str) -> int | None:
    row = conn.execute("SELECT id FROM lore_characters WHERE name = ?", (name,)).fetchone()
    return int(row[0]) if row else None


def _character_name(conn: sqlite3.Connection, character_id: int) -> str | None:
    row = conn.execute("SELECT name FROM lore_characters WHERE id = ?", (character_id,)).fetchone()
    return str(row[0]) if row else None


def get_connection(path: str, ddl: str = "") -> sqlite3.Connection:
    """DEPRECATED: shim for not-yet-migrated modules, removed in batch 3."""
    del ddl
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if "_registry" in os.path.basename(path) or "registry" in os.path.basename(path):
        from repositories.migrations import ensure_registry_migrated

        ensure_registry_migrated(path)
    else:
        from repositories.migrations import ensure_novel_db_migrated

        ensure_novel_db_migrated(path)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def close_connection(path: str) -> None:
    """Drop connection so the db file can be moved/deleted."""
    del path


class SqliteStore:
    """Thin wrapper delegating documents table primitives for not-yet-migrated callers."""

    def __init__(self, novel_id: str | None = None) -> None:
        self._novel_id = novel_id
        self._db_path = novel_db_path(novel_id) if novel_id else ""

    def scan(self) -> None:
        pass

    def reset(self) -> None:
        if self._novel_id:
            reset_archive_cache(self._novel_id)

    def refresh_plot(self) -> None:
        pass

    def close(self) -> None:
        if self._novel_id:
            dispose_engine(self._novel_id)

    def get_doc(self, key: str, path: str = "") -> Any | None:
        del path
        return get_document(self._novel_id, key)

    def save_doc(self, key: str, path: str = "", data: Any = None) -> None:
        del path
        save_document(self._novel_id, key, data)

    def get_doc_with_version(self, key: str) -> tuple[Any, int] | None:
        return get_document_with_version(self._novel_id, key)

    def save_doc_if_version_matches(
        self, key: str, data: Any, expected_version: int
    ) -> int | None:
        return save_document_if_version_matches(self._novel_id, key, data, expected_version)
