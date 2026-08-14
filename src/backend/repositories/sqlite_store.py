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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    data_json TEXT NOT NULL,
    seq INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS plot_chapters (
    chapter INTEGER PRIMARY KEY,
    data_json TEXT NOT NULL,
    seq INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS character_archives (
    character_id INTEGER NOT NULL,
    chapter INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    PRIMARY KEY (character_id, chapter),
    FOREIGN KEY (character_id) REFERENCES lore_characters(id),
    FOREIGN KEY (chapter) REFERENCES plot_chapters(chapter)
);
CREATE TABLE IF NOT EXISTS documents (
    doc_key TEXT PRIMARY KEY,
    data_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS timeline_snapshots (
    character_id INTEGER NOT NULL,
    chapter INTEGER NOT NULL,
    stage INTEGER NOT NULL,
    delta_json TEXT NOT NULL,
    PRIMARY KEY (character_id, chapter, stage),
    FOREIGN KEY (character_id) REFERENCES lore_characters(id),
    FOREIGN KEY (chapter) REFERENCES plot_chapters(chapter)
);
CREATE TABLE IF NOT EXISTS relationship_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_character_id INTEGER NOT NULL,
    to_character_id INTEGER NOT NULL,
    nature TEXT NOT NULL DEFAULT '',
    relationship_anchor TEXT NOT NULL DEFAULT '',
    from_ref_terms_json TEXT NOT NULL DEFAULT '[]',
    to_ref_terms_json TEXT NOT NULL DEFAULT '[]',
    deleted INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (from_character_id) REFERENCES lore_characters(id),
    FOREIGN KEY (to_character_id) REFERENCES lore_characters(id)
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


def _character_id(conn: sqlite3.Connection, name: str) -> int | None:
    row = conn.execute("SELECT id FROM lore_characters WHERE name = ?", (name,)).fetchone()
    return int(row[0]) if row else None


def _character_name(conn: sqlite3.Connection, character_id: int) -> str | None:
    row = conn.execute("SELECT name FROM lore_characters WHERE id = ?", (character_id,)).fetchone()
    return str(row[0]) if row else None


def get_connection(path: str, ddl: str = _DDL) -> sqlite3.Connection:
    """Process-wide sqlite3.Connection cache keyed by db path -- reuse one connection per
    novel db instead of opening a new handle on every cross-module access (timeline,
    relationship graph, SqliteStore)."""
    def _open() -> sqlite3.Connection:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON")
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
                incoming: list[tuple[str, dict, int]] = [
                    (self._lore_row_key(cd, seq), cd, seq) for seq, cd in enumerate(chars)
                ]
                existing = {
                    str(name): int(cid)
                    for name, cid in self._conn.execute(
                        "SELECT name, id FROM lore_characters",
                    ).fetchall()
                }
                incoming_names = {key for key, _, _ in incoming}
                seen_incoming: set[str] = set()

                # Drop characters leaving the roster -- dependents first so FK RESTRICT allows
                # the lore row delete (delete_character saves the trimmed roster before it
                # calls archive cleanup; without this order the FK would reject the save).
                for name, cid in existing.items():
                    if name in incoming_names:
                        continue
                    self._conn.execute(
                        "DELETE FROM character_archives WHERE character_id = ?", (cid,),
                    )
                    self._conn.execute(
                        "DELETE FROM timeline_snapshots WHERE character_id = ?", (cid,),
                    )
                    self._conn.execute(
                        "DELETE FROM relationship_edges"
                        " WHERE from_character_id = ? OR to_character_id = ?",
                        (cid, cid),
                    )
                    self._conn.execute("DELETE FROM lore_characters WHERE id = ?", (cid,))

                for key, cd, seq in incoming:
                    payload = json.dumps(cd, ensure_ascii=False)
                    if key in existing or key in seen_incoming:
                        # UPDATE keeps the surrogate id stable so existing FK rows stay valid.
                        # Duplicate names in the same save: last occurrence wins (same as the
                        # old INSERT OR REPLACE-on-name-PK behaviour).
                        self._conn.execute(
                            "UPDATE lore_characters SET data_json = ?, seq = ? WHERE name = ?",
                            (payload, seq, key),
                        )
                    else:
                        self._conn.execute(
                            "INSERT INTO lore_characters (name, data_json, seq)"
                            " VALUES (?, ?, ?)",
                            (key, payload, seq),
                        )
                    seen_incoming.add(key)
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
                incoming: list[tuple[int, dict, int]] = []
                for seq, ch in enumerate(items):
                    chapter_num = ch.get("chapter")
                    if chapter_num is None:
                        continue
                    incoming.append((int(chapter_num), ch, seq))
                incoming_chapters = {num for num, _, _ in incoming}
                existing = {
                    int(row[0])
                    for row in self._conn.execute("SELECT chapter FROM plot_chapters").fetchall()
                }

                for chapter_num in existing - incoming_chapters:
                    self._conn.execute(
                        "DELETE FROM character_archives WHERE chapter = ?", (chapter_num,),
                    )
                    self._conn.execute(
                        "DELETE FROM timeline_snapshots WHERE chapter = ?", (chapter_num,),
                    )
                    self._conn.execute(
                        "DELETE FROM sandbox_events WHERE chapter = ?", (chapter_num,),
                    )
                    self._conn.execute(
                        "DELETE FROM plot_chapters WHERE chapter = ?", (chapter_num,),
                    )

                for chapter_num, ch, seq in incoming:
                    payload = json.dumps(ch, ensure_ascii=False)
                    if chapter_num in existing:
                        self._conn.execute(
                            "UPDATE plot_chapters SET data_json = ?, seq = ? WHERE chapter = ?",
                            (payload, seq, chapter_num),
                        )
                    else:
                        self._conn.execute(
                            "INSERT INTO plot_chapters (chapter, data_json, seq)"
                            " VALUES (?, ?, ?)",
                            (chapter_num, payload, seq),
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
        character_id = _character_id(self._conn, name)
        if character_id is None:
            raise ValueError(f"角色「{name}」不在花名册中，无法写入档案。")
        with _WRITE_LOCK:
            self._conn.execute(
                "INSERT OR REPLACE INTO character_archives (character_id, chapter, data_json)"
                " VALUES (?, ?, ?)",
                (character_id, chapter, json.dumps(data, ensure_ascii=False)),
            )
            self._conn.commit()
        self._archive_cache[f"{name}::ch{chapter}"] = data

    def get_archive(self, name: str, chapter: int) -> dict | None:
        key = f"{name}::ch{chapter}"
        if key in self._archive_cache:
            return self._archive_cache[key]
        character_id = _character_id(self._conn, name)
        if character_id is None:
            return None
        row = self._conn.execute(
            "SELECT data_json FROM character_archives WHERE character_id = ? AND chapter = ?",
            (character_id, chapter),
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
        """Same as evict_archive_from, filtered by character name instead of chapter. An
        unknown name (e.g. this character's lore_characters row was already deleted by the
        caller before it gets here -- see tools.py's delete_character flow) has nothing to
        delete, not an error."""
        character_id = _character_id(self._conn, name)
        prefix = f"{name}::ch"
        victims = [k for k in self._archive_cache if k.startswith(prefix)]
        for k in victims:
            del self._archive_cache[k]
        if character_id is None:
            return 0
        with _WRITE_LOCK:
            cur = self._conn.execute(
                "DELETE FROM character_archives WHERE character_id = ?", (character_id,),
            )
            self._conn.commit()
            return cur.rowcount

    def preload_archives(self, chapter: int) -> dict[str, dict]:
        result: dict[str, dict] = {}
        rows = self._conn.execute(
            "SELECT lc.name, ca.data_json FROM character_archives ca"
            " JOIN lore_characters lc ON lc.id = ca.character_id"
            " WHERE ca.chapter = ?",
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
            "SELECT ca.chapter, lc.name FROM character_archives ca"
            " JOIN lore_characters lc ON lc.id = ca.character_id"
            " ORDER BY ca.chapter, lc.name",
        ).fetchall()
        out: dict[int, list[str]] = {}
        for chapter, name in rows:
            out.setdefault(int(chapter), []).append(name)
        return out
