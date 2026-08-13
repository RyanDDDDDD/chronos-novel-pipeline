from rag.vector_store import SqliteVectorStore


def test_upsert_then_query_returns_hit(tmp_path):
    store = SqliteVectorStore("test_col", str(tmp_path / "novel.sqlite3"))
    store.upsert(
        ids=["a"], documents=["赛博都市由七大企业统治"],
        metadatas=[{"topic": "世界观", "source": "http://x"}],
    )
    out = store.query("谁统治这座城市", top_k=3)
    assert out and out[0]["id"] == "a"
    assert "企业" in out[0]["document"]
    assert out[0]["metadata"]["source"] == "http://x"
    assert out[0]["distance"] is not None


def test_upsert_empty_ids_returns_current_count_without_erroring(tmp_path):
    store = SqliteVectorStore("test_col", str(tmp_path / "novel.sqlite3"))
    assert store.upsert(ids=[], documents=[], metadatas=[]) == 0


def test_upsert_idempotent_same_id(tmp_path):
    store = SqliteVectorStore("test_col", str(tmp_path / "novel.sqlite3"))
    store.upsert(ids=["a"], documents=["同一条"], metadatas=[{}])
    total = store.upsert(ids=["a"], documents=["同一条·改写"], metadatas=[{}])
    assert total == 1


def test_query_empty_collection_returns_empty(tmp_path):
    store = SqliteVectorStore("test_col", str(tmp_path / "novel.sqlite3"))
    assert store.query("随便什么", top_k=3) == []


def test_count_reflects_upserts(tmp_path):
    store = SqliteVectorStore("test_col", str(tmp_path / "novel.sqlite3"))
    assert store.count() == 0
    store.upsert(ids=["a", "b"], documents=["一", "二"], metadatas=[{}, {}])
    assert store.count() == 2


def test_delete_removes_matching_where(tmp_path):
    store = SqliteVectorStore("test_col", str(tmp_path / "novel.sqlite3"))
    store.upsert(
        ids=["a", "b"], documents=["一", "二"],
        metadatas=[{"chapter": 1}, {"chapter": 2}],
    )
    store.delete(where={"chapter": 1})
    remaining = store.query("一", top_k=10)
    assert [h["id"] for h in remaining] == ["b"]


def test_delete_removes_matching_ids_only(tmp_path):
    store = SqliteVectorStore("test_col", str(tmp_path / "novel.sqlite3"))
    store.upsert(
        ids=["a", "b"], documents=["一", "二"],
        metadatas=[{"source": "x"}, {"source": "x"}],
    )
    store.delete(ids=["a"])
    remaining = store.query("一", top_k=10)
    assert [h["id"] for h in remaining] == ["b"]


def test_delete_with_no_args_is_a_no_op(tmp_path):
    store = SqliteVectorStore("test_col", str(tmp_path / "novel.sqlite3"))
    store.upsert(ids=["a"], documents=["一"], metadatas=[{}])
    store.delete()
    assert store.count() == 1


def test_get_ids_returns_ids_matching_where(tmp_path):
    store = SqliteVectorStore("test_col", str(tmp_path / "novel.sqlite3"))
    store.upsert(
        ids=["a", "b"], documents=["一", "二"],
        metadatas=[{"source": "novel.txt"}, {"source": "other.txt"}],
    )
    assert store.get_ids(where={"source": "novel.txt"}) == ["a"]


def test_get_ids_no_match_returns_empty(tmp_path):
    store = SqliteVectorStore("test_col", str(tmp_path / "novel.sqlite3"))
    store.upsert(ids=["a"], documents=["一"], metadatas=[{"source": "x"}])
    assert store.get_ids(where={"source": "does-not-exist"}) == []


def test_get_returns_full_rows_matching_where(tmp_path):
    store = SqliteVectorStore("test_col", str(tmp_path / "novel.sqlite3"))
    store.upsert(
        ids=["a", "b"], documents=["一", "二"],
        metadatas=[{"category": "character", "topic": "jia"}, {"category": "world", "topic": "shijieguan"}],
    )
    rows = store.get(where={"category": "character"})
    assert [r["id"] for r in rows] == ["a"]
    assert rows[0]["document"] == "一"
    assert rows[0]["metadata"]["topic"] == "jia"


def test_get_supports_and_multi_condition_where(tmp_path):
    store = SqliteVectorStore("test_col", str(tmp_path / "novel.sqlite3"))
    store.upsert(
        ids=["a", "b"], documents=["一", "二"],
        metadatas=[{"category": "character", "topic": "jia"}, {"category": "character", "topic": "yi"}],
    )
    rows = store.get(where={"$and": [{"category": "character"}, {"topic": "jia"}]})
    assert [r["id"] for r in rows] == ["a"]


def test_get_no_match_returns_empty(tmp_path):
    store = SqliteVectorStore("test_col", str(tmp_path / "novel.sqlite3"))
    store.upsert(ids=["a"], documents=["一"], metadatas=[{"category": "world"}])
    assert store.get(where={"category": "character"}) == []


def test_two_collections_in_same_db_are_isolated(tmp_path):
    db_path = str(tmp_path / "novel.sqlite3")
    a = SqliteVectorStore("col_a", db_path)
    b = SqliteVectorStore("col_b", db_path)
    a.upsert(ids=["x"], documents=["属于 a"], metadatas=[{}])
    assert a.count() == 1
    assert b.count() == 0


def test_vector_chunks_table_exists_even_when_sqlite_store_opens_db_first(tmp_path):
    """Regression: get_connection() only runs its DDL the first time a db path is opened.
    If SqliteVectorStore shipped its own partial DDL, vector_chunks would silently never be
    created when SqliteStore (the real-world first opener, via init_repositories()) opens
    the same path first. Both must share sqlite_store.py's single _DDL."""
    from repositories.sqlite_store import SqliteStore

    db_path = str(tmp_path / "shared.sqlite3")
    import os
    os.makedirs(tmp_path, exist_ok=True)

    # SqliteStore constructs its own path internally; point CHRONOS_NOVELS_DIR at tmp_path
    # so novel_id "n1" resolves to the same db file this test then hands to SqliteVectorStore.
    import repositories.sqlite_store as sqlite_store_module

    store = SqliteStore.__new__(SqliteStore)
    store._novel_id = "n1"
    store._db_path = db_path
    store._conn = sqlite_store_module.get_connection(db_path)
    store._archive_cache = {}

    vs = SqliteVectorStore("test_col", db_path)
    vs.upsert(ids=["a"], documents=["一"], metadatas=[{}])
    assert vs.count() == 1
