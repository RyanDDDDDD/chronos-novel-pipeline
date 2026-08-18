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

    def get_lore_with_version(self, name):
        return ({"name": "甲", "gender": "female"}, 1) if name == "甲" else None

    def save_lore_if_version_matches(self, name, data, expected_version):
        self.save_call = (name, data, expected_version)
        return 2 if expected_version == 1 else None

    def delete_lore_if_version_matches(self, name, expected_version):
        self.delete_call = (name, expected_version)
        return expected_version == 1

    def get_outline_with_version(self, ch):
        return ({"title": "T", "stages": []}, 1) if ch == 1 else None

    def save_chapter_if_version_matches(self, chapter, data, expected_version):
        self.save_chapter_call = (chapter, data, expected_version)
        return 2 if expected_version == 1 else None

    def delete_chapter_if_version_matches(self, chapter, expected_version):
        self.delete_chapter_call = (chapter, expected_version)
        return expected_version == 1


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


def test_lore_repo_get_with_version_delegates():
    r = SqliteLoreRepository(_Store())
    assert r.get_character_with_version("甲") == ({"name": "甲", "gender": "female"}, 1)
    assert r.get_character_with_version("无") is None


def test_lore_repo_save_if_version_matches_delegates():
    s = _Store()
    r = SqliteLoreRepository(s)
    assert r.save_character_if_version_matches("甲", {"name": "甲", "role": "new"}, 1) == 2
    assert s.save_call == ("甲", {"name": "甲", "role": "new"}, 1)
    assert r.save_character_if_version_matches("甲", {"name": "甲"}, 99) is None


def test_lore_repo_delete_if_version_matches_delegates():
    s = _Store()
    r = SqliteLoreRepository(s)
    assert r.delete_character_if_version_matches("甲", 1) is True
    assert s.delete_call == ("甲", 1)
    assert r.delete_character_if_version_matches("甲", 99) is False


def test_plot_repo_get_with_version_delegates():
    r = SqlitePlotRepository(_Store())
    assert r.get_outline_with_version(1) == ({"title": "T", "stages": []}, 1)
    assert r.get_outline_with_version(2) is None


def test_plot_repo_save_if_version_matches_delegates():
    s = _Store()
    r = SqlitePlotRepository(s)
    assert r.save_chapter_if_version_matches(1, {"chapter": 1}, 1) == 2
    assert s.save_chapter_call == (1, {"chapter": 1}, 1)
    assert r.save_chapter_if_version_matches(1, {"chapter": 1}, 99) is None


def test_plot_repo_delete_if_version_matches_delegates():
    s = _Store()
    r = SqlitePlotRepository(s)
    assert r.delete_chapter_if_version_matches(1, 1) is True
    assert r.delete_chapter_if_version_matches(1, 99) is False
