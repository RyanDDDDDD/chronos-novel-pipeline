from __future__ import annotations

from repositories.migrations import ensure_novel_db_migrated, ensure_registry_migrated
from sqlalchemy import create_engine, inspect, text

_HEAD = "0002_add_version_columns"


def _lore_cols(db: str) -> set[str]:
    insp = inspect(create_engine(f"sqlite:///{db}"))
    return {c["name"] for c in insp.get_columns("lore_characters")}


def _alembic_rev(db: str) -> str | None:
    with create_engine(f"sqlite:///{db}").connect() as c:
        row = c.execute(text("SELECT version_num FROM alembic_version")).fetchone()
        return row[0] if row else None


def test_fresh_novel_db_gets_full_schema(tmp_path):
    db = str(tmp_path / "chronos.sqlite3")
    ensure_novel_db_migrated(db)
    insp = inspect(create_engine(f"sqlite:///{db}"))
    names = set(insp.get_table_names())
    assert {"lore_characters", "plot_chapters", "documents", "alembic_version"} <= names
    assert "version" in _lore_cols(db)
    assert _alembic_rev(db) == _HEAD


def test_legacy_db_with_version_column_is_stamped_at_head(tmp_path):
    db = str(tmp_path / "chronos.sqlite3")
    with create_engine(f"sqlite:///{db}").begin() as c:
        c.execute(
            text(
                "CREATE TABLE lore_characters (id INTEGER PRIMARY KEY, name TEXT, "
                "data_json TEXT, seq INTEGER, version INTEGER NOT NULL DEFAULT 1)"
            )
        )
        c.execute(text("INSERT INTO lore_characters (name, data_json, seq) VALUES ('x', '{}', 0)"))
    ensure_novel_db_migrated(db)
    with create_engine(f"sqlite:///{db}").connect() as c:
        assert c.execute(text("SELECT name FROM lore_characters")).scalar() == "x"
    assert _alembic_rev(db) == _HEAD  # stamped, not rebuilt


def test_legacy_scaffold_without_version_column_is_upgraded(tmp_path):
    """The ~5 empty novel dbs that have the tables but never got the runtime
    _ensure_version_columns ALTER: must end up WITH the version column (via 0002),
    not mis-stamped at head with it still missing."""
    db = str(tmp_path / "chronos.sqlite3")
    with create_engine(f"sqlite:///{db}").begin() as c:
        c.execute(
            text(
                "CREATE TABLE lore_characters (id INTEGER PRIMARY KEY, name TEXT, "
                "data_json TEXT, seq INTEGER)"
            )
        )
        c.execute(text("CREATE TABLE plot_chapters (chapter INTEGER PRIMARY KEY, data_json TEXT, seq INTEGER)"))
        c.execute(text("CREATE TABLE documents (doc_key TEXT PRIMARY KEY, data_json TEXT)"))
    ensure_novel_db_migrated(db)
    assert "version" in _lore_cols(db)
    assert _alembic_rev(db) == _HEAD


def test_idempotent(tmp_path):
    db = str(tmp_path / "chronos.sqlite3")
    ensure_novel_db_migrated(db)
    ensure_novel_db_migrated(db)  # no error, no-op


def test_registry_fresh(tmp_path):
    db = str(tmp_path / "_registry.sqlite3")
    ensure_registry_migrated(db)
    insp = inspect(create_engine(f"sqlite:///{db}"))
    cols = {c["name"] for c in insp.get_columns("novels")}
    assert cols == {"id", "name", "created_at", "is_active", "deleted_at", "pinned_at"}
