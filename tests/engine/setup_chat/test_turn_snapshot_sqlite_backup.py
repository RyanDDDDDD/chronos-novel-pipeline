"""Tests for chronos.sqlite3 backup/restore in turn_snapshot."""
import json
import os

import pytest
from engine.setup_chat import turn_snapshot as ts
from repositories.sqlite_store import SqliteStore


@pytest.fixture()
def novel_dir(tmp_path, monkeypatch):
    """Fake active novel dir with chronos.sqlite3 lore data."""
    import repositories
    from repositories.sqlite_store import SqliteStore

    root = tmp_path / "novel"
    (root / "lore").mkdir(parents=True)
    (root / "plot").mkdir()
    (root / "plot" / "plot_library.json").write_text('{"ch": 1}', encoding="utf-8")
    (root / "setup_chat").mkdir()
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "novel")
    monkeypatch.setattr("utils.paths.active_novel_dir", lambda: str(root))
    monkeypatch.setattr("utils.paths.setup_chat_dir", lambda: str(root / "setup_chat"))

    repositories.get_lore_repo("novel").save_all([{"name": "hero", "gender": "male"}])
    return root


def test_chronos_sqlite_backup_restore_roundtrip(novel_dir):
    import repositories

    repo = repositories.get_lore_repo("novel")
    assert repo.get_character("hero").gender == "male"

    assert ts.take_snapshot(["call_1"], ["patch_chapter"])

    repo.save_all([{"name": "hero", "gender": "female"}])
    assert repo.get_character("hero").gender == "female"

    assert ts.restore_if_matches({"call_1"})

    assert repo.get_character("hero").gender == "male"


def test_chronos_sqlite_excluded_from_file_copy(novel_dir):
    assert ts.is_excluded("chronos.sqlite3")
