from __future__ import annotations

from repositories.registry_models import REGISTRY_METADATA, Novel
from sqlalchemy import inspect
from sqlmodel import Session, create_engine, select


def _engine():
    eng = create_engine("sqlite://")
    REGISTRY_METADATA.create_all(eng)
    return eng


def test_novels_table_columns():
    cols = {c["name"] for c in inspect(_engine()).get_columns("novels")}
    assert cols == {"id", "name", "created_at", "is_active", "deleted_at", "pinned_at"}


def test_registry_metadata_does_not_include_novel_tables():
    assert set(REGISTRY_METADATA.tables) == {"novels"}


def test_roundtrip():
    eng = _engine()
    with Session(eng) as s:
        s.add(Novel(id="n1", name="书", created_at="2026-01-01T00:00:00Z"))
        s.commit()
    with Session(eng) as s:
        row = s.exec(select(Novel).where(Novel.id == "n1")).one()
        assert row.is_active == 0 and row.pinned_at is None
