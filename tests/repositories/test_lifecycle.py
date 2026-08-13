# tests/repositories/test_lifecycle.py
import shutil

import repositories as repo


def test_accessor_before_init_lazily_initializes():
    repo._STORES.clear()
    assert repo.get_lore_repo() is not None


def test_init_then_accessors(monkeypatch, tmp_path):
    novel_id = "test-novel"
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    repo.init_repositories(novel_id)
    repo._STORES[novel_id].save_lore([{"name": "甲", "gender": "female"}])
    assert repo.get_lore_repo(novel_id).get_character("甲").gender == "female"
    assert repo.get_research_repo() is not None


def test_store_access_updates_last_touched(monkeypatch):
    repo._STORES.clear()
    repo._last_touched.clear()
    monkeypatch.setattr(repo.time, "monotonic", lambda: 42.0)
    repo._store("novel-x")
    assert repo.last_touched_at("novel-x") == 42.0


def test_init_repositories_updates_last_touched(monkeypatch, tmp_path):
    novel_id = "novel-y"
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr(repo.time, "monotonic", lambda: 7.0)
    repo.init_repositories(novel_id)
    assert repo.last_touched_at(novel_id) == 7.0


def test_loaded_novel_ids_reflects_stores():
    repo._STORES.clear()
    repo._last_touched.clear()
    repo._store("novel-a")
    repo._store("novel-b")
    assert set(repo.loaded_novel_ids()) == {"novel-a", "novel-b"}


def test_drop_repositories_clears_last_touched():
    repo._STORES.clear()
    repo._last_touched.clear()
    repo._store("novel-z")
    repo.drop_repositories("novel-z")
    assert repo.last_touched_at("novel-z") is None
    assert "novel-z" not in repo.loaded_novel_ids()


def test_last_touched_at_missing_novel_returns_none():
    repo._last_touched.clear()
    assert repo.last_touched_at("nonexistent") is None


def test_drop_sqlite_novel_closes_connection_and_allows_move(tmp_path, monkeypatch):
    """Windows file-handle leak guard: drop must close sqlite so the novel dir can move."""
    novel_id = "sqlite-novel"
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    from repositories.sqlite_store import SqliteStore

    store = SqliteStore(novel_id)
    store.save_lore([{"name": "甲", "gender": "female"}])
    repo._STORES[novel_id] = store
    repo._last_touched[novel_id] = 0.0

    novel_path = tmp_path / novel_id
    trash_path = tmp_path / "trash" / novel_id

    repo.drop_repositories(novel_id)
    assert novel_id not in repo.loaded_novel_ids()

    trash_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(novel_path), str(trash_path))
    assert not novel_path.exists()
    assert (trash_path / "chronos.sqlite3").exists()
