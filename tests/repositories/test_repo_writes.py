"""Repo writing interface: save_all / upsert_character / upsert_chapter / archive.save."""
from repositories.sqlite_repositories import (
    SqliteArchiveRepository,
    SqliteLoreRepository,
    SqlitePlotRepository,
)


class _Store:
    def __init__(self):
        self.lore = [{"name": "甲", "gender": "female"}]
        self.plot = [{"chapter": 1, "title": "T", "stages": []}]
        self.saved_archive = None

    def list_lore(self):
        return list(self.lore)

    def get_lore(self, n):
        return next((c for c in self.lore if c["name"] == n), None)

    def get_outline(self, ch):
        return next((p for p in self.plot if p["chapter"] == ch), None)

    def list_plot(self):
        return sorted(self.plot, key=lambda p: p.get("chapter", 0))

    def list_lore_raw(self):
        return list(self.lore)

    def list_plot_raw(self):
        return list(self.plot)

    def save_lore(self, chars, path=None):
        self.lore = chars

    def save_plot(self, chs, path=None):
        if isinstance(chs, list):
            self.plot = chs
        else:
            self.plot = list(chs.values())

    def save_archive(self, n, ch, d, path=None):
        self.saved_archive = (n, ch, d)


def test_upsert_character_adds_and_replaces():
    s = _Store()
    r = SqliteLoreRepository(s)
    r.upsert_character({"name": "乙", "gender": "xeno"})
    assert {c["name"] for c in s.lore} == {"甲", "乙"}
    r.upsert_character({"name": "甲", "gender": "xeno"})  #replace
    assert s.get_lore("甲")["gender"] == "xeno" and len(s.lore) == 2


def test_save_all_lore():
    s = _Store()
    r = SqliteLoreRepository(s)
    r.save_all([{"name": "丙", "gender": "male"}])
    assert len(s.lore) == 1 and s.lore[0]["name"] == "丙"


def test_upsert_chapter_replaces_by_number():
    s = _Store()
    r = SqlitePlotRepository(s)
    r.upsert_chapter({"chapter": 1, "title": "T2", "stages": []})
    assert s.get_outline(1)["title"] == "T2" and len(s.plot) == 1
    r.upsert_chapter({"chapter": 2, "title": "B", "stages": []})
    assert len(s.plot) == 2


def test_save_all_plot():
    s = _Store()
    r = SqlitePlotRepository(s)
    r.save_all([{"chapter": 3, "title": "C3", "stages": []}])
    assert len(s.plot) == 1 and s.plot[0]["chapter"] == 3


def test_list_raw_passthrough():
    """list_raw returns the original dict (pass-through display, without entities - plot stage characters are in dict form)."""
    s = _Store()
    r = SqlitePlotRepository(s)
    r.upsert_chapter({"chapter": 2, "title": "B", "stages": [{"characters": {"甲": {}}}]})
    chapters = r.list_raw()
    assert len(chapters) == 2
    assert chapters[0]["chapter"] == 1
    assert chapters[1]["stages"][0]["characters"] == {"甲": {}}  #dict shape conformal


def test_archive_repo_save_delegates():
    s = _Store()
    r = SqliteArchiveRepository(s)
    r.save("甲", 1, {"name": "甲"})
    assert s.saved_archive[0] == "甲"
