# tests/repositories/test_sqlite_store.py
import json
import os

import pytest
from repositories.sqlite_store import SqliteStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    novel_id = "test-novel"
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    s = SqliteStore(novel_id)
    s.save_lore([
        {"name": "甲", "gender": "female", "role": "lead"},
        {"gender": "unknown"},  # name-missing item preserved in raw
    ])
    s.save_plot([{"chapter": 1, "title": "T", "stages": []}])
    yield s
    s.close()


def test_get_lore(store):
    assert store.get_lore("甲")["gender"] == "female"
    assert store.get_lore("无") is None


def test_list_lore_raw_preserves_order_and_unnamed(store):
    raw = store.list_lore_raw()
    assert len(raw) == 2
    assert raw[0]["name"] == "甲"
    assert "name" not in raw[1]


def test_save_lore_duplicate_name_does_not_abort_whole_write(store):
    """A duplicate name in the incoming roster must not IntegrityError the whole transaction
    and drop every other character with it -- last occurrence wins, matching JsonStore's
    dict-backed _lore semantics for get_lore/list_lore."""
    store.save_lore([
        {"name": "甲", "role": "old"},
        {"name": "乙", "role": "lead"},
        {"name": "甲", "role": "new"},
    ])
    assert store.get_lore("甲")["role"] == "new"
    assert store.get_lore("乙")["role"] == "lead"


def test_get_outline(store):
    assert store.get_outline(1)["title"] == "T"


def test_save_lore_replaces_whole_db(store):
    store.save_lore([{"name": "乙", "gender": "male"}])
    assert store.get_lore("甲") is None
    assert store.get_lore("乙")["gender"] == "male"
    assert len(store.list_lore_raw()) == 1


def test_save_plot_replaces_whole_db(store):
    store.save_plot([
        {"chapter": 2, "title": "B", "stages": []},
        {"chapter": 3, "title": "C", "stages": []},
    ])
    assert store.get_outline(1) is None
    assert store.get_outline(2)["title"] == "B"
    raw = store.list_plot_raw()
    assert [p["chapter"] for p in raw] == [2, 3]


def test_list_plot_raw_order(store):
    store.save_plot([
        {"chapter": 3, "title": "C", "stages": []},
        {"chapter": 1, "title": "A", "stages": []},
    ])
    raw = store.list_plot_raw()
    assert [p["chapter"] for p in raw] == [3, 1]


def test_archive_cache_put_get_evict(store):
    store.put_archive("甲", 2, {"name": "甲", "chapter": 2})
    assert store.get_archive("甲", 2)["chapter"] == 2
    store.evict_archive_from(2)
    assert store.get_archive("甲", 2) is None


def test_evict_archive_from_deletes_persisted_rows_not_just_cache(store):
    """Regression (2026-08-09): evict_archive_from used to only clear the in-memory
    read-through cache, never issuing a SQL DELETE -- a "deleted" chapter's archive would
    silently reappear on the next cache-miss read. Must actually remove the row."""
    store.save_archive("甲", 2, {"name": "甲", "chapter": 2})
    store.save_archive("乙", 1, {"name": "乙", "chapter": 1})
    assert store.evict_archive_from(2) == 1
    row = store._conn.execute(
        "SELECT 1 FROM character_archives WHERE name = '甲' AND chapter = 2",
    ).fetchone()
    assert row is None
    # chapter 1 untouched
    assert store.get_archive("乙", 1) is not None


def test_save_and_preload_archives(store):
    store.save_archive("甲", 1, {"name": "甲", "chapter": 1, "stages": {}})
    store.save_archive("乙", 1, {"name": "乙", "chapter": 1})
    preloaded = store.preload_archives(1)
    assert set(preloaded) == {"甲", "乙"}


def test_evict_archive_for(store):
    store.put_archive("甲", 1, {"name": "甲", "chapter": 1})
    store.put_archive("甲", 2, {"name": "甲", "chapter": 2})
    store.put_archive("乙", 1, {"name": "乙", "chapter": 1})
    store.evict_archive_for("甲")
    assert store.get_archive("乙", 1) is not None


def test_evict_archive_for_deletes_persisted_rows_not_just_cache(store):
    store.save_archive("甲", 1, {"name": "甲", "chapter": 1})
    store.save_archive("甲", 2, {"name": "甲", "chapter": 2})
    store.save_archive("乙", 1, {"name": "乙", "chapter": 1})
    assert store.evict_archive_for("甲") == 2
    row = store._conn.execute(
        "SELECT 1 FROM character_archives WHERE name = '甲'",
    ).fetchone()
    assert row is None
    assert store.get_archive("乙", 1) is not None


def test_get_doc_reads_sql_on_miss(tmp_path, monkeypatch):
    novel_id = "doc-novel"
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    s = SqliteStore(novel_id)
    try:
        assert s.get_doc("w", "/unused/path.json") is None
        s.save_doc("w", "/unused/path.json", {"a": 1})
        assert s.get_doc("w", "/unused/path.json") == {"a": 1}
    finally:
        s.close()


def test_save_doc_insert_or_replace(tmp_path, monkeypatch):
    novel_id = "doc-novel"
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    s = SqliteStore(novel_id)
    try:
        s.save_doc("world_bible", "/unused/world.json", {"tone": "dark"})
        assert s.get_doc("world_bible", "/unused/world.json") == {"tone": "dark"}
        s.save_doc("world_bible", "/unused/world.json", {"tone": "light"})
        assert s.get_doc("world_bible", "/unused/world.json") == {"tone": "light"}
    finally:
        s.close()


def test_reset_clears_archive_cache_only(tmp_path, monkeypatch):
    novel_id = "reset-novel"
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    s = SqliteStore(novel_id)
    try:
        s.save_doc("w", "/unused/w.json", {"v": 1})
        s.put_archive("甲", 1, {"name": "甲"})
        s.reset()
        assert s.get_doc("w", "/unused/w.json") == {"v": 1}
        assert s.get_archive("甲", 1) is None
    finally:
        s.close()


def test_creates_sqlite_file(tmp_path, monkeypatch):
    novel_id = "new-novel"
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    s = SqliteStore(novel_id)
    try:
        db_path = os.path.join(tmp_path, novel_id, "chronos.sqlite3")
        assert os.path.exists(db_path)
    finally:
        s.close()


def test_ddl_creates_vector_chunks_table(store):
    row = store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='vector_chunks'",
    ).fetchone()
    assert row is not None


def test_list_archived_chapters_groups_by_chapter(store):
    store.save_archive("甲", 1, {"name": "甲", "chapter": 1})
    store.save_archive("乙", 1, {"name": "乙", "chapter": 1})
    store.save_archive("甲", 2, {"name": "甲", "chapter": 2})
    assert store.list_archived_chapters() == {1: ["乙", "甲"], 2: ["甲"]}


def test_list_archived_chapters_empty_when_nothing_saved(store):
    assert store.list_archived_chapters() == {}


def test_get_connection_reuses_cached_connection_for_same_path(tmp_path):
    from repositories.sqlite_store import get_connection

    db_path = str(tmp_path / "shared.sqlite3")
    conn1 = get_connection(db_path)
    conn2 = get_connection(db_path)

    assert conn1 is conn2


def test_get_connection_does_not_rerun_ddl_on_cache_hit(tmp_path):
    from repositories.sqlite_store import get_connection

    db_path = str(tmp_path / "shared.sqlite3")
    get_connection(db_path, ddl="CREATE TABLE IF NOT EXISTS first (id INTEGER PRIMARY KEY);")
    # Second call passes a DIFFERENT ddl -- must be ignored because the connection is
    # already cached (matches the pre-migration "ddl only runs the first time" contract).
    conn = get_connection(db_path, ddl="INVALID SQL THAT WOULD RAISE IF EXECUTED (((")

    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    assert ("first",) in tables


def test_close_connection_removes_from_cache_and_closes(tmp_path):
    import sqlite3

    from repositories.sqlite_store import close_connection, get_connection

    db_path = str(tmp_path / "shared.sqlite3")
    conn = get_connection(db_path)
    close_connection(db_path)

    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")

    # a fresh get_connection() after close must build a brand new connection
    new_conn = get_connection(db_path)
    assert new_conn is not conn


def test_sqlite_store_close_removes_itself_when_still_the_cached_connection(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    from repositories.sqlite_store import get_connection

    store = SqliteStore("novel-a")
    cached_before = get_connection(store._db_path)
    assert cached_before is store._conn

    store.close()

    # a fresh get_connection() after close must build a brand new connection
    # (proves the cache entry was actually removed, not just this instance's own close)
    new_conn = get_connection(store._db_path)
    assert new_conn is not store._conn


def test_sqlite_store_close_does_not_touch_cache_when_superseded(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    from repositories.sqlite_store import close_connection, get_connection

    store = SqliteStore("novel-b")
    # Simulate someone else having already replaced the cached connection for this path
    # (e.g. via close_connection + a fresh get_connection) before this instance closes.
    close_connection(store._db_path)
    replacement = get_connection(store._db_path)

    store.close()  # must NOT remove `replacement` from the cache

    assert get_connection(store._db_path) is replacement
