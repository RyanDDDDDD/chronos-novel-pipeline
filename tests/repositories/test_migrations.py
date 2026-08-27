from __future__ import annotations

from repositories.migrations import ensure_novel_db_migrated, ensure_registry_migrated
from sqlalchemy import create_engine, inspect, text


def test_fresh_novel_db_gets_full_schema(tmp_path):
    db = str(tmp_path / "chronos.sqlite3")
    ensure_novel_db_migrated(db)
    insp = inspect(create_engine(f"sqlite:///{db}"))
    assert "lore_characters" in insp.get_table_names()
    assert "alembic_version" in insp.get_table_names()


def test_existing_novel_db_is_stamped_not_rebuilt(tmp_path):
    db = str(tmp_path / "chronos.sqlite3")
    eng = create_engine(f"sqlite:///{db}")
    # simulate a legacy db: tables exist, seeded row, no alembic_version
    with eng.begin() as c:
        c.execute(
            text(
                "CREATE TABLE lore_characters (id INTEGER PRIMARY KEY, name TEXT, data_json TEXT, seq INTEGER, version INTEGER DEFAULT 1)"
            )
        )
        c.execute(text("INSERT INTO lore_characters (name, data_json, seq) VALUES ('x', '{}', 0)"))
    ensure_novel_db_migrated(db)
    with eng.connect() as c:
        assert c.execute(text("SELECT name FROM lore_characters")).scalar() == "x"
        assert (
            c.execute(text("SELECT version_num FROM alembic_version")).scalar()
            == "0001_initial_novel_schema"
        )


def test_idempotent(tmp_path):
    db = str(tmp_path / "chronos.sqlite3")
    ensure_novel_db_migrated(db)
    ensure_novel_db_migrated(db)  # no error


def test_registry_fresh(tmp_path):
    db = str(tmp_path / "_registry.sqlite3")
    ensure_registry_migrated(db)
    assert "novels" in inspect(create_engine(f"sqlite:///{db}")).get_table_names()
