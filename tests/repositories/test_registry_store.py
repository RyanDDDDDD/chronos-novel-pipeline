"""Tests for cross-novel registry store."""
from repositories.registry_store import get_registry_connection, registry_path


def test_registry_path_under_novels_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    assert registry_path().endswith("_registry.sqlite3")
    assert str(tmp_path) in registry_path()


def test_registry_connection_creates_table(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    conn = get_registry_connection()
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='novels'",
    ).fetchone()
    assert row is not None


def test_registry_insert_and_query(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    conn = get_registry_connection()
    conn.execute(
        "INSERT INTO novels (id, name, created_at, is_active) VALUES (?, ?, ?, ?)",
        ("n1", "Test Novel", "2026-01-01T00:00:00+00:00", 1),
    )
    conn.commit()
    row = conn.execute("SELECT name FROM novels WHERE id = 'n1'").fetchone()
    assert row[0] == "Test Novel"
