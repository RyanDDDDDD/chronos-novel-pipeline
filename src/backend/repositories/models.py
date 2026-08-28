"""SQLModel table models for the per-novel SQLite db (data/novels/<id>/chronos.sqlite3).

Field set and constraints mirror the old sqlite_store._DDL exactly -- this is a
storage-access rewrite, not a schema change. The business payload stays in one
`data_json` column (JSONText); only the stable skeleton fields are typed, matching
repositories/entities.py's envelope design. Three tables (lore_characters,
plot_chapters, documents) carry an optimistic-concurrency `version` column driven
by SQLAlchemy's version_id_col."""
from __future__ import annotations

from typing import Any

from sqlalchemy import Column, Integer, LargeBinary, String
from sqlmodel import Field, SQLModel

from repositories.db_types import JSONText

NOVEL_METADATA = SQLModel.metadata

_lore_version = Column("version", Integer, nullable=False, server_default="1")
_plot_version = Column("version", Integer, nullable=False, server_default="1")
_doc_version = Column("version", Integer, nullable=False, server_default="1")


class LoreCharacter(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "lore_characters"
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(sa_column=Column("name", String, unique=True, nullable=False))
    data_json: dict[str, Any] = Field(sa_column=Column("data_json", JSONText, nullable=False))
    seq: int = Field(sa_column=Column("seq", Integer, nullable=False))
    version: int = Field(default=1, sa_column=_lore_version)
    __mapper_args__ = {"version_id_col": _lore_version}


class PlotChapter(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "plot_chapters"
    chapter: int = Field(sa_column=Column("chapter", Integer, primary_key=True, autoincrement=False))
    data_json: dict[str, Any] = Field(sa_column=Column("data_json", JSONText, nullable=False))
    seq: int = Field(sa_column=Column("seq", Integer, nullable=False))
    version: int = Field(default=1, sa_column=_plot_version)
    __mapper_args__ = {"version_id_col": _plot_version}


class CharacterArchive(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "character_archives"
    character_id: int = Field(foreign_key="lore_characters.id", primary_key=True)
    chapter: int = Field(foreign_key="plot_chapters.chapter", primary_key=True)
    data_json: dict[str, Any] = Field(sa_column=Column("data_json", JSONText, nullable=False))


class Document(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "documents"
    doc_key: str = Field(sa_column=Column("doc_key", String, primary_key=True))
    data_json: Any = Field(sa_column=Column("data_json", JSONText, nullable=False))
    version: int = Field(default=1, sa_column=_doc_version)
    __mapper_args__ = {"version_id_col": _doc_version}


class TimelineSnapshot(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "timeline_snapshots"
    character_id: int = Field(foreign_key="lore_characters.id", primary_key=True)
    chapter: int = Field(foreign_key="plot_chapters.chapter", primary_key=True)
    stage: int = Field(primary_key=True)
    delta_json: dict[str, Any] = Field(sa_column=Column("delta_json", JSONText, nullable=False))


class RelationshipEdge(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "relationship_edges"
    id: int | None = Field(default=None, primary_key=True)
    from_character_id: int = Field(foreign_key="lore_characters.id")
    to_character_id: int = Field(foreign_key="lore_characters.id")
    nature: str = Field(default="", sa_column=Column("nature", String, nullable=False, server_default="''"))
    relationship_anchor: str = Field(
        default="", sa_column=Column("relationship_anchor", String, nullable=False, server_default="''")
    )
    from_ref_terms_json: list[Any] = Field(
        default_factory=list,
        sa_column=Column("from_ref_terms_json", JSONText, nullable=False, server_default="'[]'"),
    )
    to_ref_terms_json: list[Any] = Field(
        default_factory=list,
        sa_column=Column("to_ref_terms_json", JSONText, nullable=False, server_default="'[]'"),
    )
    deleted: int = Field(default=0, sa_column=Column("deleted", Integer, nullable=False, server_default="0"))


class SessionMessage(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "session_messages"
    id: str = Field(primary_key=True)
    role: str = Field(sa_column=Column("role", String, nullable=False))
    content: str = Field(sa_column=Column("content", String, nullable=False))
    seq: int = Field(sa_column=Column("seq", Integer, nullable=False))
    ts: int = Field(sa_column=Column("ts", Integer, nullable=False))


class SandboxEvent(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "sandbox_events"
    id: str = Field(primary_key=True)
    chapter: int = Field(sa_column=Column("chapter", Integer, nullable=False))
    turn_index: int = Field(sa_column=Column("turn_index", Integer, nullable=False))
    entry_json: dict[str, Any] = Field(sa_column=Column("entry_json", JSONText, nullable=False))


class VectorChunk(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "vector_chunks"
    collection: str = Field(primary_key=True)
    id: str = Field(primary_key=True)
    document: str = Field(sa_column=Column("document", String, nullable=False))
    metadata_json: dict[str, Any] = Field(sa_column=Column("metadata_json", JSONText, nullable=False))
    embedding: bytes = Field(sa_column=Column("embedding", LargeBinary, nullable=False))
