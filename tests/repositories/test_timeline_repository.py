"""TimelineRepository Thin package testing."""
from repositories.timeline_repository import TimelineRepository


def test_timeline_repo_delegates(monkeypatch):
    import repositories.timeline_repository as m
    calls = {}
    monkeypatch.setattr(
        m.character_timeline, "append_stage",
        lambda name, chapter, stage, delta: calls.update(append=(name, chapter, stage, delta)),
    )
    monkeypatch.setattr(
        m.character_timeline, "deltas_upto",
        lambda name, chapter, stage: [{"chapter": chapter, "stage": stage}],
    )
    r = TimelineRepository()
    r.append_stage("甲", 1, 2, {"x": 1})
    assert calls["append"] == ("甲", 1, 2, {"x": 1})
    assert r.deltas_upto("甲", 1, 2) == [{"chapter": 1, "stage": 2}]


def test_timeline_repo_truncate_from(monkeypatch):
    import repositories.timeline_repository as m
    monkeypatch.setattr(m.character_timeline, "truncate_from", lambda name, from_ch: 3)
    r = TimelineRepository()
    assert r.truncate_from("甲", 2) == 3


def test_timeline_repo_list_names(monkeypatch):
    import repositories.timeline_repository as m
    monkeypatch.setattr(m.character_timeline, "list_timeline_names", lambda: ["甲", "乙"])
    r = TimelineRepository()
    assert r.list_names() == ["甲", "乙"]
