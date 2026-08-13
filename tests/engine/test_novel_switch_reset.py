"""Reset in-process cache after switching active novel: reset_repositories (replaces reset_indexers).

Bug fix: After cutting the novel, the main author/file still reads the previous one (indexers are cached according to the old path, and reload does not restart the backend)."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _restore_globals():
    """This test changes the global repositories cache to point to temporary data → restore it after use to avoid contaminating other tests."""
    import repositories as repo

    saved_stores = dict(repo._STORES)
    yield
    repo._STORES.clear()
    repo._STORES.update(saved_stores)


def test_reset_repositories_clears_archive_cache(tmp_path, monkeypatch):
    import repositories
    from repositories.sqlite_store import SqliteStore

    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    store = SqliteStore("novel-A")
    store.put_archive("甲", 1, {"name": "甲", "chapter": 1, "cached": True})
    repositories._STORES["novel-A"] = store

    arch = repositories.get_archive_repo("novel-A").get("甲", 1)
    assert arch is not None and arch.name == "甲"
    repositories.reset_repositories("novel-A")
    assert repositories.get_archive_repo("novel-A").get("甲", 1) is None


def test_store_is_sharded_per_novel(tmp_path, monkeypatch):
    """Two different novel_ids get independent SqliteStore instances that don't clobber each other."""
    import repositories
    from repositories.sqlite_store import SqliteStore

    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))

    store_a = SqliteStore("novel-A")
    store_a.save_plot([{"chapter": 1, "title": "甲书第一章", "stages": []}])
    repositories._STORES["novel-A"] = store_a

    store_b = SqliteStore("novel-B")
    store_b.save_plot([{"chapter": 1, "title": "乙书第一章", "stages": []}])
    repositories._STORES["novel-B"] = store_b

    title_a, _ = repositories.get_plot_repo("novel-A").chapter_segments(1)
    title_b, _ = repositories.get_plot_repo("novel-B").chapter_segments(1)
    assert title_a == "甲书第一章"
    assert title_b == "乙书第一章"


def test_drop_repositories_evicts_shard(tmp_path, monkeypatch):
    import repositories
    from repositories.sqlite_store import SqliteStore

    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    store = SqliteStore("novel-C")
    repositories._STORES["novel-C"] = store

    assert "novel-C" in repositories._STORES
    repositories.drop_repositories("novel-C")
    assert "novel-C" not in repositories._STORES
