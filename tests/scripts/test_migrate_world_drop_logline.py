"""scripts/migrate_world_drop_logline.py: one-off migration dropping the legacy world_bible
`logline` scalar now that it's merged into `background`. See
docs/superpowers/specs/2026-07-31-world-logline-background-merge-design.md."""
import contextlib

from scripts.migrate_world_drop_logline import migrate_all


class _FakeWorldRepo:
    def __init__(self, bible):
        self.bible = bible

    def get(self):
        return self.bible

    def save(self, data):
        self.bible = data


def _patch_novel(monkeypatch, nid, bible):
    repo = _FakeWorldRepo(bible)
    monkeypatch.setattr(
        "api.services.novels.list_novels", lambda: [{"id": nid, "name": nid, "active": True}],
    )
    monkeypatch.setattr("utils.paths.use_novel", lambda _nid: contextlib.nullcontext())
    monkeypatch.setattr("repositories.reset_repositories", lambda: None)
    monkeypatch.setattr("repositories.get_world_repo", lambda: repo)
    return repo


def test_drops_logline_and_keeps_background(monkeypatch):
    repo = _patch_novel(monkeypatch, "nov1", {"logline": "旧立意", "background": "乱世", "tone": "暗黑"})

    result = migrate_all()

    assert result["migrated"] == ["nov1"]
    assert "logline" not in repo.bible
    assert repo.bible["background"] == "乱世"
    assert repo.bible["tone"] == "暗黑"


def test_skips_novel_without_logline(monkeypatch):
    repo = _patch_novel(monkeypatch, "nov1", {"background": "乱世", "tone": "暗黑"})

    result = migrate_all()

    assert result["migrated"] == []
    assert repo.bible == {"background": "乱世", "tone": "暗黑"}
