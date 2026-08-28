"""Repo writing interface: save_all / upsert_character / upsert_chapter / archive.save."""
from repositories.sqlite_repositories import (
    SqliteArchiveRepository,
    SqliteLoreRepository,
    SqlitePlotRepository,
)


def test_upsert_character_adds_and_replaces(novel_engine):
    r = SqliteLoreRepository("n1")
    r.save_all([{"name": "甲", "gender": "female"}])
    r.upsert_character({"name": "乙", "gender": "xeno"})
    names = {c["name"] for c in r.list_raw()}
    assert names == {"甲", "乙"}
    r.upsert_character({"name": "甲", "gender": "xeno"})  # replace
    assert r.get_character("甲").gender == "xeno"
    assert len(r.list_raw()) == 2


def test_save_all_lore(novel_engine):
    r = SqliteLoreRepository("n1")
    r.save_all([{"name": "甲", "gender": "female"}])
    r.save_all([{"name": "丙", "gender": "male"}])
    raw = r.list_raw()
    assert len(raw) == 1 and raw[0]["name"] == "丙"


def test_upsert_chapter_replaces_by_number(novel_engine):
    r = SqlitePlotRepository("n1")
    r.save_all([{"chapter": 1, "title": "T", "stages": []}])
    r.upsert_chapter({"chapter": 2, "title": "B", "stages": []})
    assert len(r.list_raw()) == 2
    r.upsert_chapter({"chapter": 1, "title": "New Title", "stages": []})
    assert len(r.list_raw()) == 2
    assert r.get_outline(1).title == "New Title"


def test_save_all_plot(novel_engine):
    r = SqlitePlotRepository("n1")
    r.save_all([{"chapter": 1, "title": "T", "stages": []}])
    r.save_all([{"chapter": 5, "title": "Five", "stages": []}])
    raw = r.list_raw()
    assert len(raw) == 1 and raw[0]["chapter"] == 5


def test_list_raw_passthrough(novel_engine):
    r = SqlitePlotRepository("n1")
    r.save_all([
        {"chapter": 1, "title": "A", "stages": []},
        {"chapter": 2, "title": "B", "stages": [{"characters": {"甲": {}}}]},
    ])
    chapters = r.list_raw()
    assert len(chapters) == 2
    assert chapters[0]["chapter"] == 1


def test_archive_repo_save_delegates(novel_engine):
    lore = SqliteLoreRepository("n1")
    lore.save_all([{"name": "甲", "gender": "female"}])

    r = SqliteArchiveRepository("n1")
    r.save("甲", 1, {"name": "甲", "summary": "s1"})
    arch = r.get("甲", 1)
    assert arch is not None
    assert arch.name == "甲"
    assert arch.summary == "s1"
