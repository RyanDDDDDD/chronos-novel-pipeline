from __future__ import annotations

import pytest
from repositories.entities import CharacterArchive
from repositories.models import LoreCharacter, PlotChapter
from repositories.sqlite_repositories import SqliteArchiveRepository
from sqlmodel import Session


def test_archive_repo_put_get_cache(novel_engine):
    repo = SqliteArchiveRepository("n1")
    repo.put("张三", 1, {"appearance": "清瘦"})
    arch = repo.get("张三", 1)
    assert isinstance(arch, CharacterArchive)
    assert arch.name == "张三"
    assert arch.chapter == 1
    assert arch.appearance == "清瘦"


def test_archive_save_raises_for_unknown_character(novel_engine):
    repo = SqliteArchiveRepository("n1")
    with pytest.raises(ValueError, match="不在花名册中"):
        repo.save("未知角色", 1, {"note": "test"})


def test_archive_save_and_get_db(novel_engine):
    repo = SqliteArchiveRepository("n1")
    with Session(novel_engine) as s:
        s.add(LoreCharacter(name="张三", data_json={"name": "张三"}, seq=0))
        s.add(PlotChapter(chapter=1, data_json={"chapter": 1}, seq=0))
        s.commit()

    repo.save("张三", 1, {"title": "掌门"})
    arch = repo.get("张三", 1)
    assert arch is not None
    assert arch.title == "掌门"


def test_preload_archives(novel_engine):
    repo = SqliteArchiveRepository("n1")
    with Session(novel_engine) as s:
        c1 = LoreCharacter(name="A", data_json={"name": "A"}, seq=0)
        c2 = LoreCharacter(name="B", data_json={"name": "B"}, seq=1)
        s.add(c1)
        s.add(c2)
        s.add(PlotChapter(chapter=1, data_json={"chapter": 1}, seq=0))
        s.commit()

    repo.save("A", 1, {"note": "A1"})
    repo.save("B", 1, {"note": "B1"})

    preloaded = repo.preload(1)
    assert "A" in preloaded and preloaded["A"]["note"] == "A1"
    assert "B" in preloaded and preloaded["B"]["note"] == "B1"


def test_evict_from_deletes_db_and_cache(novel_engine):
    repo = SqliteArchiveRepository("n1")
    with Session(novel_engine) as s:
        c = LoreCharacter(name="A", data_json={"name": "A"}, seq=0)
        s.add(c)
        s.add(PlotChapter(chapter=1, data_json={"chapter": 1}, seq=0))
        s.add(PlotChapter(chapter=2, data_json={"chapter": 2}, seq=1))
        s.commit()

    repo.save("A", 1, {"note": "ch1"})
    repo.save("A", 2, {"note": "ch2"})

    deleted = repo.evict_from(2)
    assert deleted == 1
    assert repo.get("A", 1) is not None
    assert repo.get("A", 2) is None


def test_evict_for_character(novel_engine):
    repo = SqliteArchiveRepository("n1")
    with Session(novel_engine) as s:
        c1 = LoreCharacter(name="A", data_json={"name": "A"}, seq=0)
        c2 = LoreCharacter(name="B", data_json={"name": "B"}, seq=1)
        s.add(c1)
        s.add(c2)
        s.add(PlotChapter(chapter=1, data_json={"chapter": 1}, seq=0))
        s.commit()

    repo.save("A", 1, {"note": "a"})
    repo.save("B", 1, {"note": "b"})

    assert repo.evict_for("A") == 1
    assert repo.get("A", 1) is None
    assert repo.get("B", 1) is not None
    assert repo.evict_for("Unknown") == 0


def test_list_built(novel_engine):
    repo = SqliteArchiveRepository("n1")
    with Session(novel_engine) as s:
        c1 = LoreCharacter(name="A", data_json={"name": "A"}, seq=0)
        c2 = LoreCharacter(name="B", data_json={"name": "B"}, seq=1)
        s.add(c1)
        s.add(c2)
        s.add(PlotChapter(chapter=1, data_json={"chapter": 1}, seq=0))
        s.add(PlotChapter(chapter=2, data_json={"chapter": 2}, seq=1))
        s.commit()

    repo.save("A", 1, {})
    repo.save("B", 1, {})
    repo.save("A", 2, {})

    built = repo.list_built()
    assert built == {1: ["A", "B"], 2: ["A"]}
