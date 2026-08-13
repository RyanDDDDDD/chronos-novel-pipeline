"""Structured storage layer: per-novel SQLite IO + archive memory cache.

Mirrors JsonStore's public API so sqlite_repositories can serve all structured data
without changing call sites. Lore/plot are queried directly from SQLite (no in-memory dict
cache); archive keeps the same memory cache as JsonStore."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any, cast

from utils.cache import KeyedCache
from utils.paths import (
    novel_db_path,
    story_character_config_path,
)

_WRITE_LOCK = threading.Lock()
_clients_lock = threading.Lock()
_connections: KeyedCache[str, sqlite3.Connection] = KeyedCache(on_evict=lambda conn: conn.close())

_DDL = """
CREATE TABLE IF NOT EXISTS lore_characters (
    name TEXT PRIMARY KEY,
    data_json TEXT NOT NULL,
    seq INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS plot_chapters (
    chapter INTEGER PRIMARY KEY,
    data_json TEXT NOT NULL,
    seq INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS character_archives (
    name TEXT NOT NULL,
    chapter INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    PRIMARY KEY (name, chapter)
);
CREATE TABLE IF NOT EXISTS documents (
    doc_key TEXT PRIMARY KEY,
    data_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS timeline_snapshots (
    name TEXT NOT NULL,
    chapter INTEGER NOT NULL,
    stage INTEGER NOT NULL,
    delta_json TEXT NOT NULL,
    PRIMARY KEY (name, chapter, stage)
);
CREATE TABLE IF NOT EXISTS relationship_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_name TEXT NOT NULL,
    to_name TEXT NOT NULL,
    nature TEXT NOT NULL DEFAULT '',
    relationship_anchor TEXT NOT NULL DEFAULT '',
    from_ref_terms_json TEXT NOT NULL DEFAULT '[]',
    to_ref_terms_json TEXT NOT NULL DEFAULT '[]',
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS session_messages (
    id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sandbox_events (
    id TEXT PRIMARY KEY,
    chapter INTEGER NOT NULL,
    turn_index INTEGER NOT NULL,
    entry_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vector_chunks (
    collection TEXT NOT NULL,
    id TEXT NOT NULL,
    document TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    embedding BLOB NOT NULL,
    PRIMARY KEY (collection, id)
);
"""


def get_connection(path: str, ddl: str = _DDL) -> sqlite3.Connection:
    """Process-wide sqlite3.Connection cache keyed by db path -- reuse one connection per
    novel db instead of opening a new handle on every cross-module access (timeline,
    relationship graph, SqliteStore)."""
    def _open() -> sqlite3.Connection:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.executescript(ddl)
        return conn

    with _clients_lock:
        return _connections.get(path, _open)


def close_connection(path: str) -> None:
    """Drop a cached connection so the db file can be moved/deleted (Windows file lock)."""
    with _clients_lock:
        _connections.invalidate(path)


class SqliteStore:
    def __init__(self, novel_id: str) -> None:
        self._novel_id = novel_id
        self._db_path = novel_db_path(novel_id)
        self._conn = get_connection(self._db_path)
        self._archive_cache: dict[str, dict] = {}

    # ---- life cycle ----
    def scan(self) -> None:
        """No-op: lore/plot live in SQLite, not an in-memory scan cache."""

    def reset(self) -> None:
        """Cut the novel: clear archive memory cache."""
        self._archive_cache.clear()

    def refresh_plot(self) -> None:
        """No-op: plot is always read from SQLite."""

    def close(self) -> None:
        with _clients_lock:
            _connections.discard_if(self._db_path, self._conn)
        self._conn.close()

    def _story_config(self) -> dict[str, dict]:
        data = self.get_doc("story_character_config", story_character_config_path())
        return data if isinstance(data, dict) else {}

    def _merge_story_extensions(self, char: dict, name: str) -> None:
        ext = self._story_config().get(name)
        if isinstance(ext, dict):
            char.setdefault("extensions", {})
            char["extensions"].update(ext)

    @staticmethod
    def _lore_row_key(cd: dict, seq: int) -> str:
        name = cd.get("name")
        if isinstance(name, str) and name:
            return name
        return f"__idx_{seq}__"

    # ---- universal document write-through (world bible etc.; not lore/plot tables) ----
    def get_doc(self, key: str, path: str) -> Any | None:
        del path
        row = self._conn.execute(
            "SELECT data_json FROM documents WHERE doc_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return None

    def save_doc(self, key: str, path: str, data: Any) -> None:
        del path
        self._conn.execute(
            "INSERT OR REPLACE INTO documents (doc_key, data_json) VALUES (?, ?)",
            (key, json.dumps(data, ensure_ascii=False)),
        )
        self._conn.commit()

    # ---- lore ----
    def get_lore(self, name: str) -> dict | None:
        row = self._conn.execute(
            "SELECT data_json FROM lore_characters WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            return None
        char = dict(json.loads(row[0]))
        char.setdefault("extensions", {})
        self._merge_story_extensions(char, name)
        return char

    def list_lore(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT data_json FROM lore_characters ORDER BY seq",
        ).fetchall()
        result: list[dict] = []
        for row in rows:
            char = json.loads(row[0])
            name = char.get("name")
            if not name:
                continue
            c = dict(char)
            c.setdefault("extensions", {})
            self._merge_story_extensions(c, name)
            result.append(c)
        return result

    def list_lore_raw(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT data_json FROM lore_characters ORDER BY seq",
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def save_lore(self, chars: list[dict], path: str | None = None) -> None:
        del path  # SQLite backend ignores JSON path overrides
        with _WRITE_LOCK:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute("DELETE FROM lore_characters")
                for seq, cd in enumerate(chars):
                    key = self._lore_row_key(cd, seq)
                    # OR REPLACE: a duplicate name in the incoming list must not abort the
                    # whole roster write -- JsonStore's dict-backed _lore silently let later
                    # entries win on a repeated name; sqlite's PK would otherwise raise
                    # IntegrityError and lose every other character in the same transaction.
                    self._conn.execute(
                        "INSERT OR REPLACE INTO lore_characters (name, data_json, seq)"
                        " VALUES (?, ?, ?)",
                        (key, json.dumps(cd, ensure_ascii=False), seq),
                    )
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    # ---- plot ----
    def get_outline(self, chapter: int) -> dict | None:
        row = self._conn.execute(
            "SELECT data_json FROM plot_chapters WHERE chapter = ?",
            (chapter,),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def list_plot(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT data_json FROM plot_chapters ORDER BY chapter",
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def list_plot_raw(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT data_json FROM plot_chapters ORDER BY seq",
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def save_plot(self, chapters: list[dict] | dict, path: str | None = None) -> None:
        del path
        items = list(chapters.values()) if isinstance(chapters, dict) else list(chapters)
        with _WRITE_LOCK:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute("DELETE FROM plot_chapters")
                for seq, ch in enumerate(items):
                    chapter_num = ch.get("chapter")
                    if chapter_num is None:
                        continue
                    self._conn.execute(
                        "INSERT INTO plot_chapters (chapter, data_json, seq) VALUES (?, ?, ?)",
                        (int(chapter_num), json.dumps(ch, ensure_ascii=False), seq),
                    )
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    # ---- archive (cache takes precedence over SQLite read) ----
    def put_archive(self, name: str, chapter: int, data: dict) -> None:
        self._archive_cache[f"{name}::ch{chapter}"] = data

    def save_archive(
        self, name: str, chapter: int, data: dict, path: str | None = None
    ) -> None:
        del path
        with _WRITE_LOCK:
            self._conn.execute(
                "INSERT OR REPLACE INTO character_archives (name, chapter, data_json)"
                " VALUES (?, ?, ?)",
                (name, chapter, json.dumps(data, ensure_ascii=False)),
            )
            self._conn.commit()
        self._archive_cache[f"{name}::ch{chapter}"] = data

    def get_archive(self, name: str, chapter: int) -> dict | None:
        key = f"{name}::ch{chapter}"
        if key in self._archive_cache:
            return self._archive_cache[key]
        row = self._conn.execute(
            "SELECT data_json FROM character_archives WHERE name = ? AND chapter = ?",
            (name, chapter),
        ).fetchone()
        if row is None:
            return None
        data: dict[Any, Any] = cast(dict[Any, Any], json.loads(row[0]))
        self._archive_cache[key] = data
        return data

    def evict_archive_from(self, chapter: int) -> int:
        """Deletes every archive row at or after `chapter` from character_archives, plus the
        matching in-memory cache entries. Returns the count of SQLite rows actually removed --
        previously this only cleared the read-through cache and left persisted rows in place,
        so a "deleted" chapter's archive silently reappeared on the next cache-miss read
        (2026-08-09 fix)."""
        with _WRITE_LOCK:
            cur = self._conn.execute(
                "DELETE FROM character_archives WHERE chapter >= ?", (chapter,),
            )
            self._conn.commit()
            deleted = cur.rowcount
        victims = [k for k in self._archive_cache if int(k.rsplit("::ch", 1)[1]) >= chapter]
        for k in victims:
            del self._archive_cache[k]
        return deleted

    def evict_archive_for(self, name: str) -> int:
        """Same as evict_archive_from, filtered by character name instead of chapter."""
        with _WRITE_LOCK:
            cur = self._conn.execute(
                "DELETE FROM character_archives WHERE name = ?", (name,),
            )
            self._conn.commit()
            deleted = cur.rowcount
        prefix = f"{name}::ch"
        victims = [k for k in self._archive_cache if k.startswith(prefix)]
        for k in victims:
            del self._archive_cache[k]
        return deleted

    def preload_archives(self, chapter: int) -> dict[str, dict]:
        result: dict[str, dict] = {}
        rows = self._conn.execute(
            "SELECT name, data_json FROM character_archives WHERE chapter = ?",
            (chapter,),
        ).fetchall()
        for name, data_json in rows:
            data = json.loads(data_json)
            key = f"{name}::ch{chapter}"
            self._archive_cache[key] = data
            result[name] = data
        return result

    def list_archived_chapters(self) -> dict[int, list[str]]:
        """All chapters that currently have at least one persisted archive row, and which
        characters -- the sole source of truth for "what's built" (2026-08-09 fix: replaces a
        stale filesystem scan of the pre-SQLite archive.json era that archive_view.py's
        _built_chapters() used to do; writes moved to this table long ago, so that scan always
        found nothing)."""
        rows = self._conn.execute(
            "SELECT chapter, name FROM character_archives ORDER BY chapter, name",
        ).fetchall()
        out: dict[int, list[str]] = {}
        for chapter, name in rows:
            out.setdefault(int(chapter), []).append(name)
        return out
