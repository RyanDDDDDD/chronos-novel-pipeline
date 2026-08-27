# tests/repositories/test_lifecycle.py
import shutil
import time

import repositories as repo
from repositories import engine


def test_accessor_before_init_lazily_initializes():
    engine._engines.clear()
    assert repo.get_lore_repo() is not None


def test_init_then_accessors(monkeypatch, tmp_path):
    novel_id = "test-novel"
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    repo.init_repositories(novel_id)
    repo.get_lore_repo(novel_id).save_all([{"name": "甲", "gender": "female"}])
    char = repo.get_lore_repo(novel_id).get_character("甲")
    assert char is not None and char.gender == "female"
    assert repo.get_research_repo() is not None


def test_engine_access_updates_last_touched(monkeypatch, tmp_path):
    novel_id = "novel-x"
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    engine._engines.clear()
    engine._last_touched.clear()
    monkeypatch.setattr(time, "monotonic", lambda: 42.0)
    engine.engine_for_novel(novel_id)
    assert repo.last_touched_at(novel_id) == 42.0


def test_init_repositories_updates_last_touched(monkeypatch, tmp_path):
    novel_id = "novel-y"
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr(time, "monotonic", lambda: 7.0)
    repo.init_repositories(novel_id)
    assert repo.last_touched_at(novel_id) == 7.0


def test_loaded_novel_ids_reflects_engines(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    engine._engines.clear()
    engine._last_touched.clear()
    engine.engine_for_novel("novel-a")
    engine.engine_for_novel("novel-b")
    assert set(repo.loaded_novel_ids()) == {"novel-a", "novel-b"}


def test_drop_repositories_clears_last_touched(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    engine._engines.clear()
    engine._last_touched.clear()
    engine.engine_for_novel("novel-z")
    repo.drop_repositories("novel-z")
    assert repo.last_touched_at("novel-z") is None
    assert "novel-z" not in repo.loaded_novel_ids()


def test_last_touched_at_missing_novel_returns_none():
    engine._last_touched.clear()
    assert repo.last_touched_at("nonexistent") is None


def test_drop_sqlite_novel_closes_connection_and_allows_move(tmp_path, monkeypatch):
    """Windows file-handle leak guard: drop must close sqlite so the novel dir can move."""
    novel_id = "sqlite-novel"
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))

    repo.init_repositories(novel_id)
    repo.get_lore_repo(novel_id).save_all([{"name": "甲", "gender": "female"}])

    novel_path = tmp_path / novel_id
    trash_path = tmp_path / "trash" / novel_id

    repo.drop_repositories(novel_id)
    assert novel_id not in repo.loaded_novel_ids()

    trash_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(novel_path), str(trash_path))
    assert not novel_path.exists()
    assert (trash_path / "chronos.sqlite3").exists()
