from pathlib import Path

import api.services.token_ledger as tl
import pytest


@pytest.fixture
def novel_dir(tmp_path, monkeypatch):
    nid = "default"
    d = tmp_path / nid
    d.mkdir()
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", nid)
    return d


def test_add_accumulates_within_run(novel_dir):
    tl.add_to_cell("author_loop", "6", 100, 40, 30, "m")
    cell = tl.add_to_cell("author_loop", "6", 50, 20, 10, "m")
    assert cell == {"tokens_in": 150, "tokens_out": 60, "tokens_cached": 40, "model": "m"}


def test_reset_then_add_overwrites(novel_dir):
    tl.add_to_cell("author_loop", "6", 100, 40, 30, "m")
    tl.reset_cell("author_loop", "6")
    cell = tl.add_to_cell("author_loop", "6", 5, 2, 1, "m")
    assert cell["tokens_in"] == 5


def test_add_preserves_other_cells(novel_dir):
    tl.add_to_cell("author_loop", "6", 100, 40, 30, "m")
    tl.add_to_cell("archive", "6", 7, 3, 0, "m")
    tl.reset_cell("author_loop", "6")
    tl.add_to_cell("author_loop", "6", 1, 1, 0, "m")
    led = tl.load_ledger()
    assert led["archive"]["6"]["tokens_in"] == 7


def test_load_missing_returns_empty(novel_dir):
    assert tl.load_ledger() == {}


def test_load_corrupt_returns_empty(novel_dir):
    from repositories.sqlite_store import SqliteStore

    store = SqliteStore("default")
    store._conn.execute(
        "INSERT OR REPLACE INTO documents (doc_key, data_json) VALUES (?, ?)",
        ("token_ledger", "not json"),
    )
    store._conn.commit()
    assert tl.load_ledger() == {}
