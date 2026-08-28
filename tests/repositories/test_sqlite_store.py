# tests/repositories/test_sqlite_store.py
import sqlite3

from repositories import get_lore_repo
from repositories.sqlite_store import (
    SqliteStore,
    _character_id,
    _character_name,
    close_connection,
    get_connection,
)


def test_sqlite_store_doc_operations(tmp_path, monkeypatch):
    novel_id = "doc-novel"
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    s = SqliteStore(novel_id)
    try:
        assert s.get_doc("world_bible") is None
        s.save_doc("world_bible", "/unused/world.json", {"tone": "dark"})
        assert s.get_doc("world_bible") == {"tone": "dark"}

        doc_ver = s.get_doc_with_version("world_bible")
        assert doc_ver is not None
        doc, ver = doc_ver
        assert doc == {"tone": "dark"}
        assert ver == 1

        assert s.save_doc_if_version_matches("world_bible", {"tone": "light"}, 1) == 2
        assert s.get_doc("world_bible") == {"tone": "light"}
        assert s.save_doc_if_version_matches("world_bible", {"tone": "epic"}, 1) is None
    finally:
        s.close()


def test_sqlite_store_reset_and_scan(tmp_path, monkeypatch):
    novel_id = "reset-novel"
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    s = SqliteStore(novel_id)
    s.scan()
    s.reset()
    s.close()


def test_get_connection_creates_tables_and_enables_fk(tmp_path):
    db_path = str(tmp_path / "test.sqlite3")
    conn = get_connection(db_path)
    try:
        assert isinstance(conn, sqlite3.Connection)
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1

        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "lore_characters" in tables
        assert "plot_chapters" in tables
        assert "character_archives" in tables
        assert "documents" in tables
        assert "vector_chunks" in tables
    finally:
        conn.close()
        close_connection(db_path)


def test_character_id_and_name_helpers(tmp_path, monkeypatch):
    novel_id = "char-novel"
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    lore_repo = get_lore_repo(novel_id)
    lore_repo.save_all([{"name": "甲", "gender": "female"}])

    db_path = str(tmp_path / novel_id / "chronos.sqlite3")
    conn = get_connection(db_path)
    try:
        cid = _character_id(conn, "甲")
        assert cid is not None and isinstance(cid, int)
        assert _character_id(conn, "查无此人") is None

        name = _character_name(conn, cid)
        assert name == "甲"
        assert _character_name(conn, 99999) is None
    finally:
        conn.close()
