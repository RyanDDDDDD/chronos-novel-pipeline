from __future__ import annotations

from repositories.db_types import JSONText
from sqlalchemy import Column, Integer, MetaData, Table, create_engine


def test_roundtrip_dict():
    md = MetaData()
    t = Table("t", md, Column("id", Integer, primary_key=True), Column("body", JSONText))
    eng = create_engine("sqlite://")
    md.create_all(eng)
    with eng.begin() as c:
        c.execute(t.insert().values(id=1, body={"名字": "张三", "n": 2}))
    with eng.connect() as c:
        assert c.execute(t.select()).one().body == {"名字": "张三", "n": 2}


def test_stored_text_is_not_ascii_escaped():
    md = MetaData()
    t = Table("t", md, Column("id", Integer, primary_key=True), Column("body", JSONText))
    eng = create_engine("sqlite://")
    md.create_all(eng)
    with eng.begin() as c:
        c.execute(t.insert().values(id=1, body={"k": "中文"}))
    with eng.connect() as c:
        raw = c.exec_driver_sql("SELECT body FROM t WHERE id=1").scalar()
    assert "中文" in raw
    assert "\\u" not in raw


def test_none_passthrough():
    md = MetaData()
    t = Table("t", md, Column("id", Integer, primary_key=True), Column("body", JSONText))
    eng = create_engine("sqlite://")
    md.create_all(eng)
    with eng.begin() as c:
        c.execute(t.insert().values(id=1, body=None))
    with eng.connect() as c:
        assert c.execute(t.select()).one().body is None
