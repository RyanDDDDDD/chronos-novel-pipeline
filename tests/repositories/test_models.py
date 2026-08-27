from __future__ import annotations

from typing import cast

from repositories.models import (
    LoreCharacter,
    VectorChunk,
)
from sqlalchemy import inspect
from sqlmodel import Session, SQLModel, create_engine, select

_EXPECTED_TABLES = {
    "lore_characters",
    "plot_chapters",
    "character_archives",
    "documents",
    "timeline_snapshots",
    "relationship_edges",
    "session_messages",
    "sandbox_events",
    "vector_chunks",
}


def _engine():
    eng = create_engine("sqlite://")
    SQLModel.metadata.create_all(eng)
    return eng


def test_all_nine_tables_created():
    insp = inspect(_engine())
    assert set(insp.get_table_names()) >= _EXPECTED_TABLES


def test_lore_character_columns_match_ddl():
    cols = {c["name"] for c in inspect(_engine()).get_columns("lore_characters")}
    assert cols == {"id", "name", "data_json", "seq", "version"}


def test_lore_character_roundtrip_json_payload():
    eng = _engine()
    with Session(eng) as s:
        s.add(LoreCharacter(name="张三", data_json={"name": "张三", "gender": "男"}, seq=0))
        s.commit()
    with Session(eng) as s:
        row = s.exec(select(LoreCharacter).where(LoreCharacter.name == "张三")).one()
        assert row.data_json == {"name": "张三", "gender": "男"}
        assert row.version == 1


def test_versioned_tables_have_version_column():
    insp = inspect(_engine())
    for t in ("lore_characters", "plot_chapters", "documents"):
        assert "version" in {c["name"] for c in insp.get_columns(t)}


def test_unversioned_tables_have_no_version_column():
    insp = inspect(_engine())
    for t in (
        "character_archives",
        "timeline_snapshots",
        "relationship_edges",
        "session_messages",
        "sandbox_events",
        "vector_chunks",
    ):
        assert "version" not in {c["name"] for c in insp.get_columns(t)}


def test_foreign_keys_present():
    fks = inspect(_engine()).get_foreign_keys("character_archives")
    referred = {fk["referred_table"] for fk in fks}
    assert referred == {"lore_characters", "plot_chapters"}


def test_composite_pk_character_archives():
    pk = inspect(_engine()).get_pk_constraint("character_archives")
    assert set(pk["constrained_columns"]) == {"character_id", "chapter"}


def test_vector_chunk_roundtrip():
    eng = _engine()
    with Session(eng) as s:
        s.add(
            VectorChunk(
                collection="c",
                id="x",
                document="d",
                metadata_json={"k": "v"},
                embedding=b"\x00\x01",
            )
        )
        s.commit()
    with Session(eng) as s:
        row = cast(VectorChunk, s.get(VectorChunk, ("c", "x")))
        assert row.embedding == b"\x00\x01" and row.metadata_json == {"k": "v"}
