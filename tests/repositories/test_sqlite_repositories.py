# tests/repositories/test_sqlite_repositories.py
from repositories.entities import ChapterOutline, Character
from repositories.sqlite_repositories import (
    SqliteArchiveRepository,
    SqliteLoreRepository,
    SqlitePlotRepository,
)


def test_lore_repo_returns_entity(novel_engine):
    r = SqliteLoreRepository("n1")
    r.save_all([{"name": "甲", "gender": "female"}])
    c = r.get_character("甲")
    assert isinstance(c, Character) and c.gender == "female"
    assert r.get_character("无") is None


def test_plot_repo_outline_and_segments(novel_engine):
    r = SqlitePlotRepository("n1")
    r.save_all([{"chapter": 1, "title": "T", "stages": [{"description": "d", "stage_num": 1}]}])
    assert isinstance(r.get_outline(1), ChapterOutline)
    title, stages = r.chapter_segments(1)
    assert title == "T" and stages[0]["text"] == "d"
    assert r.chapter_segments(2) == (None, [])


def test_archive_repo_put_get_preload_evict(novel_engine):
    lore = SqliteLoreRepository("n1")
    lore.save_all([{"name": "甲", "gender": "female"}, {"name": "乙", "gender": "male"}])

    r = SqliteArchiveRepository("n1")
    r.put("甲", 1, {"name": "甲", "chapter": 1})
    arch = r.get("甲", 1)
    assert arch is not None
    assert arch.name == "甲"
    assert arch.chapter == 1

    r.save("甲", 1, {"name": "甲", "chapter": 1})
    preloaded = r.preload(1)
    assert "甲" in preloaded

    assert r.evict_from(1) >= 1
    assert r.list_built() == {}


def test_lore_repo_get_with_version_delegates(novel_engine):
    r = SqliteLoreRepository("n1")
    r.save_all([{"name": "甲", "gender": "female"}])
    res = r.get_character_with_version("甲")
    assert res is not None
    data, ver = res
    assert data["name"] == "甲"
    assert data["gender"] == "female"
    assert ver == 1


def test_lore_repo_save_if_version_matches_delegates(novel_engine):
    r = SqliteLoreRepository("n1")
    r.save_all([{"name": "甲", "gender": "female"}])
    assert r.save_character_if_version_matches("甲", {"name": "甲", "role": "new"}, 1) == 2
    assert r.save_character_if_version_matches("甲", {"name": "甲", "role": "stale"}, 1) is None


def test_lore_repo_delete_if_version_matches_delegates(novel_engine):
    r = SqliteLoreRepository("n1")
    r.save_all([{"name": "甲", "gender": "female"}])
    assert r.delete_character_if_version_matches("甲", 1) is True
    assert r.delete_character_if_version_matches("甲", 1) is False


def test_plot_repo_get_with_version_delegates(novel_engine):
    r = SqlitePlotRepository("n1")
    r.save_all([{"chapter": 1, "title": "T", "stages": []}])
    outline, ver = r.get_outline_with_version(1)
    assert outline["title"] == "T"
    assert ver == 1


def test_plot_repo_save_if_version_matches_delegates(novel_engine):
    r = SqlitePlotRepository("n1")
    r.save_all([{"chapter": 1, "title": "T", "stages": []}])
    assert r.save_chapter_if_version_matches(1, {"chapter": 1, "title": "New"}, 1) == 2
    assert r.save_chapter_if_version_matches(1, {"chapter": 1, "title": "Stale"}, 1) is None


def test_plot_repo_delete_if_version_matches_delegates(novel_engine):
    r = SqlitePlotRepository("n1")
    r.save_all([{"chapter": 1, "title": "T", "stages": []}])
    assert r.delete_chapter_if_version_matches(1, 1) is True
    assert r.delete_chapter_if_version_matches(1, 1) is False
