"""Tests for chronos.sqlite3 backup/restore in turn_snapshot."""
import json
import os

import pytest
from engine.setup_chat import turn_snapshot as ts
from repositories.sqlite_store import SqliteStore


@pytest.fixture()
def novel_dir(tmp_path, monkeypatch):
    """Fake active novel dir with chronos.sqlite3 lore data."""
    root = tmp_path / "novel"
    (root / "lore").mkdir(parents=True)
    (root / "plot").mkdir()
    (root / "plot" / "plot_library.json").write_text('{"ch": 1}', encoding="utf-8")
    (root / "setup_chat").mkdir()
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "novel")
    monkeypatch.setattr("utils.paths.active_novel_dir", lambda: str(root))
    monkeypatch.setattr("utils.paths.setup_chat_dir", lambda: str(root / "setup_chat"))

    store = SqliteStore("novel")
    store.save_lore([{"name": "hero", "gender": "male"}])
    store.close()
    return root


def test_chronos_sqlite_backup_restore_roundtrip(novel_dir):
    store = SqliteStore("novel")
    assert store.get_lore("hero")["gender"] == "male"
    store.close()

    assert ts.take_snapshot(["call_1"], ["patch_chapter"])

    store = SqliteStore("novel")
    store.save_lore([{"name": "hero", "gender": "female"}])
    store.close()
    store2 = SqliteStore("novel")
    assert store2.get_lore("hero")["gender"] == "female"
    store2.close()

    assert ts.restore_if_matches({"call_1"})

    store3 = SqliteStore("novel")
    assert store3.get_lore("hero")["gender"] == "male"
    store3.close()


def test_chronos_sqlite_excluded_from_file_copy(novel_dir):
    assert ts.is_excluded("chronos.sqlite3")
