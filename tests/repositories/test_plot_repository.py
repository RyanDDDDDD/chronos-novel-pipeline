from __future__ import annotations

from repositories.entities import ChapterOutline
from repositories.models import (
    CharacterArchive,
    LoreCharacter,
    PlotChapter,
    SandboxEvent,
    TimelineSnapshot,
)
from repositories.sqlite_repositories import SqlitePlotRepository
from sqlmodel import Session, select


def test_plot_repo_roundtrip(novel_engine):
    repo = SqlitePlotRepository("n1")
    repo.save_all([
        {"chapter": 1, "title": "第一章", "stages": [{"title": "S1", "stage_num": 1}], "core_xp": ["爽点1"]},
        {"chapter": 2, "title": "第二章", "stages": []},
    ])

    outline = repo.get_outline(1)
    assert isinstance(outline, ChapterOutline)
    assert outline.chapter == 1
    assert outline.title == "第一章"

    segments_ch, segs = repo.chapter_segments(1)
    assert len(segs) == 1
    assert segs[0]["title"] == "S1"

    xp = repo.chapter_core_xp(1)
    assert xp == ["爽点1"]

    raw = repo.list_raw()
    assert len(raw) == 2
    assert raw[0]["chapter"] == 1


def test_save_all_diff_and_cascade(novel_engine):
    repo = SqlitePlotRepository("n1")
    repo.save_all([{"chapter": 1}, {"chapter": 2}])

    with Session(novel_engine) as s:
        char = LoreCharacter(name="甲", data_json={"name": "甲"}, seq=0)
        s.add(char)
        s.commit()
        s.refresh(char)

        s.add(CharacterArchive(character_id=char.id, chapter=1, data_json={"note": "1"}))
        s.add(TimelineSnapshot(character_id=char.id, chapter=1, stage=1, delta_json={"d": 1}))
        s.add(SandboxEvent(id="ev1", chapter=1, turn_index=0, entry_json={"e": 1}))
        s.commit()

    # Save without chapter 1 -> chapter 1 and its dependent archive/timeline/sandbox_event rows removed
    repo.save_all([{"chapter": 2}, {"chapter": 3}])

    with Session(novel_engine) as s:
        assert s.get(PlotChapter, 1) is None
        assert s.exec(select(CharacterArchive)).all() == []
        assert s.exec(select(TimelineSnapshot)).all() == []
        assert s.exec(select(SandboxEvent)).all() == []
        assert len(s.exec(select(PlotChapter)).all()) == 2


def test_upsert_chapter(novel_engine):
    repo = SqlitePlotRepository("n1")
    repo.save_all([{"chapter": 1, "title": "C1"}])
    repo.upsert_chapter({"chapter": 1, "title": "C1_updated"})
    repo.upsert_chapter({"chapter": 2, "title": "C2"})

    assert repo.get_outline(1).title == "C1_updated"
    assert repo.get_outline(2).title == "C2"


def test_version_cas_operations(novel_engine):
    repo = SqlitePlotRepository("n1")
    repo.save_all([{"chapter": 1, "title": "Old"}])

    res = repo.get_outline_with_version(1)
    assert res is not None
    data, ver = res
    assert ver == 1

    # Stale CAS rejected
    assert repo.save_chapter_if_version_matches(1, {"chapter": 1, "title": "New"}, expected_version=99) is None

    # Matching CAS
    assert repo.save_chapter_if_version_matches(1, {"chapter": 1, "title": "New"}, expected_version=1) == 2
    assert repo.get_outline(1).title == "New"

    # Stale delete rejected
    assert not repo.delete_chapter_if_version_matches(1, expected_version=1)
    assert repo.get_outline(1) is not None

    # Matching delete
    assert repo.delete_chapter_if_version_matches(1, expected_version=2)
    assert repo.get_outline(1) is None
