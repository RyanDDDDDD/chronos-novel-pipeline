"""Pins down how version_id_col wires up under this project's SQLModel version:
a module-level Column reused via sa_column= and referenced in __mapper_args__.
If SQLModel changes and breaks this, every versioned model in models.py breaks
the same way -- catch it here first."""
from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm.exc import StaleDataError
from sqlmodel import Field, Session, SQLModel, create_engine, select

_ver = Column("version", Integer, nullable=False)


class _Row(SQLModel, table=True):
    __tablename__ = "verrow"
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(sa_column=Column("name", String, unique=True, nullable=False))
    version: int = Field(default=1, sa_column=_ver)
    __mapper_args__ = {"version_id_col": _ver}


def _engine():
    eng = create_engine("sqlite://")
    SQLModel.metadata.create_all(eng)
    return eng


def test_version_auto_increments_on_update():
    eng = _engine()
    with Session(eng) as s:
        s.add(_Row(name="a"))
        s.commit()
    with Session(eng) as s:
        row = s.exec(select(_Row).where(_Row.name == "a")).one()
        assert row.version == 1
        row.name = "a2"
        s.commit()
        s.refresh(row)
        assert row.version == 2


def test_stale_write_raises_stale_data_error():
    eng = _engine()
    with Session(eng) as s:
        s.add(_Row(name="b"))
        s.commit()
    s1 = Session(eng)
    s2 = Session(eng)
    r1 = s1.exec(select(_Row).where(_Row.name == "b")).one()
    r2 = s2.exec(select(_Row).where(_Row.name == "b")).one()
    r1.name = "b1"
    s1.commit()
    r2.name = "b2"
    with pytest.raises(StaleDataError):
        s2.commit()
    s1.close()
    s2.close()
