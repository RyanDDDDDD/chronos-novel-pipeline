from __future__ import annotations

import repositories.engine as eng
from repositories.models import LoreCharacter
from sqlalchemy import text
from sqlmodel import select


def test_engine_is_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(eng, "_novel_db_path", lambda nid: str(tmp_path / f"{nid}.sqlite3"))
    e1 = eng.engine_for_novel("n1")
    e2 = eng.engine_for_novel("n1")
    assert e1 is e2


def test_session_for_yields_working_session(tmp_path, monkeypatch):
    monkeypatch.setattr(eng, "_novel_db_path", lambda nid: str(tmp_path / f"{nid}.sqlite3"))
    with eng.session_for("n2") as s:
        s.add(LoreCharacter(name="a", data_json={"name": "a"}, seq=0))
        s.commit()
    with eng.session_for("n2") as s:
        assert s.exec(select(LoreCharacter)).one().name == "a"


def test_foreign_keys_pragma_on(tmp_path, monkeypatch):
    monkeypatch.setattr(eng, "_novel_db_path", lambda nid: str(tmp_path / f"{nid}.sqlite3"))
    with eng.session_for("n3") as s:
        val = s.exec(text("PRAGMA foreign_keys")).one()
    assert val[0] == 1


def test_dispose_engine_drops_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(eng, "_novel_db_path", lambda nid: str(tmp_path / f"{nid}.sqlite3"))
    e1 = eng.engine_for_novel("n4")
    eng.dispose_engine("n4")
    assert eng.engine_for_novel("n4") is not e1


def test_archive_cache_is_per_novel(tmp_path, monkeypatch):
    monkeypatch.setattr(eng, "_novel_db_path", lambda nid: str(tmp_path / f"{nid}.sqlite3"))
    eng.archive_cache_for("a")["k"] = {"x": 1}
    assert eng.archive_cache_for("b") == {}
    eng.reset_archive_cache("a")
    assert eng.archive_cache_for("a") == {}


def test_engine_for_path_is_cached(tmp_path):
    p = str(tmp_path / "x.sqlite3")
    assert eng.engine_for_path(p) is eng.engine_for_path(p)


def test_engine_for_path_builds_schema(tmp_path):
    from sqlalchemy import inspect

    e = eng.engine_for_path(str(tmp_path / "y.sqlite3"))
    assert "vector_chunks" in inspect(e).get_table_names()


def test_engine_for_novel_delegates_to_path_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(eng, "_novel_db_path", lambda nid: str(tmp_path / f"{nid}.sqlite3"))
    by_id = eng.engine_for_novel("n5")
    by_path = eng.engine_for_path(str(tmp_path / "n5.sqlite3"))
    assert by_id is by_path
