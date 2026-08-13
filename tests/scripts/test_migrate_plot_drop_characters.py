"""scripts/migrate_plot_drop_characters.py: one-off migration physically deleting the retired
`characters` key from every stage in every novel's plot_library.json. See
docs/superpowers/specs/2026-07-31-plot-characters-field-elimination-design.md."""
import contextlib

from scripts.migrate_plot_drop_characters import migrate_all


class _FakePlotRepo:
    def __init__(self, chapters):
        self.chapters = chapters

    def list_raw(self):
        return self.chapters

    def save_all(self, chapters):
        self.chapters = chapters


def _patch_novel(monkeypatch, nid, chapters):
    repo = _FakePlotRepo(chapters)
    monkeypatch.setattr(
        "api.services.novels.list_novels", lambda: [{"id": nid, "name": nid, "active": True}],
    )
    monkeypatch.setattr("utils.paths.use_novel", lambda _nid: contextlib.nullcontext())
    monkeypatch.setattr("repositories.reset_repositories", lambda: None)
    monkeypatch.setattr("repositories.get_plot_repo", lambda: repo)
    return repo


def test_drops_characters_key_from_every_stage(monkeypatch):
    repo = _patch_novel(monkeypatch, "nov1", [
        {"chapter": 1, "stages": [
            {"stage_num": 1, "description": "d1", "characters": {"甲": {}}},
            {"stage_num": 2, "description": "d2", "characters": {}},
        ]},
    ])

    result = migrate_all()

    assert result == {"nov1": 2}
    stages = repo.chapters[0]["stages"]
    assert "characters" not in stages[0]
    assert "characters" not in stages[1]
    assert stages[0]["description"] == "d1"  # untouched fields survive


def test_skips_novel_without_characters_key(monkeypatch):
    repo = _patch_novel(monkeypatch, "nov1", [
        {"chapter": 1, "stages": [{"stage_num": 1, "description": "d1"}]},
    ])

    result = migrate_all()

    assert result == {}
    assert repo.chapters[0]["stages"][0] == {"stage_num": 1, "description": "d1"}
