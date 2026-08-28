"""SQLModel model for the cross-novel registry (data/novels/_registry.sqlite3).

Deliberately on its own MetaData, not repositories.models.NOVEL_METADATA -- the
registry db and per-novel dbs never share a schema, and create_all() over one must
never touch the other."""
from __future__ import annotations

from sqlalchemy import Column, Integer, MetaData, String
from sqlmodel import Field, SQLModel

REGISTRY_METADATA = MetaData()


class Novel(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "novels"
    metadata = REGISTRY_METADATA
    id: str = Field(primary_key=True)
    name: str = Field(sa_column=Column("name", String, nullable=False))
    created_at: str = Field(sa_column=Column("created_at", String, nullable=False))
    is_active: int = Field(default=0, sa_column=Column("is_active", Integer, nullable=False, server_default="0"))
    deleted_at: str | None = None
    pinned_at: str | None = None
