# tests/repositories/test_sqlite_repositories.py
from repositories.entities import ChapterOutline, Character
from repositories.sqlite_repositories import (
    SqliteArchiveRepository,
    SqliteLoreRepository,
    SqlitePlotRepository,
)


class _Store:
    def get_lore(self, name): return {"name": "甲", "gender": "female"} if name == "甲" else None
    def list_lore(self): return [{"name": "甲", "gender": "female"}]
    def get_outline(self, ch): return {"title": "T", "stages": [{"description": "d", "stage_num": 1}]} if ch == 1 else None
    def get_archive(self, n, ch): return {"name": n, "chapter": ch, "stages": {}} if ch == 1 else None
    def put_archive(self, n, ch, d): self.saved = (n, ch, d)
    def preload_archives(self, ch): return {"甲": {"name": "甲", "chapter": ch}}
    def evict_archive_from(self, ch): return 3
    def list_archived_chapters(self): return {1: ["甲"]}


def test_lore_repo_returns_entity():
    r = SqliteLoreRepository(_Store())
    c = r.get_character("甲")
    assert isinstance(c, Character) and c.gender == "female"
    assert r.get_character("无") is None


def test_plot_repo_outline_and_segments():
    r = SqlitePlotRepository(_Store())
    assert isinstance(r.get_outline(1), ChapterOutline)
    title, stages = r.chapter_segments(1)
    assert title == "T" and stages[0]["text"] == "d"
    assert r.chapter_segments(2) == (None, [])


def test_archive_repo_put_get_preload_evict():
    s = _Store()
    r = SqliteArchiveRepository(s)
    r.put("甲", 1, {"name": "甲"})
    assert s.saved[0] == "甲"
    assert r.get("甲", 1).name == "甲"
    assert "甲" in r.preload(1)
    assert r.evict_from(1) == 3
    assert r.list_built() == {1: ["甲"]}
