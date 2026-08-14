import pytest
from utils.paths import use_novel


def _stage(desc: str) -> dict:
    return {"stage_num": 1, "description": desc, "text": ""}


def _novel(tmp_path, monkeypatch, novel_id: str) -> None:
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    from repositories import drop_repositories
    drop_repositories(novel_id)
    from engine.memory_recall.entity_index import invalidate_entity_vocab_cache
    invalidate_entity_vocab_cache(novel_id)


@pytest.mark.asyncio
async def test_delete_chapter_shifts_later_chapters_down(tmp_path, monkeypatch):
    _novel(tmp_path, monkeypatch, "delete-novel")
    with use_novel("delete-novel"):
        from repositories import get_lore_repo, get_plot_repo
        get_lore_repo().save_all([
            {"name": "甲", "given_name": "甲"},
            {"name": "乙", "given_name": "乙"},
        ])
        get_plot_repo().save_all([
            {"chapter": 1, "title": "T1", "core_xp": ["x"], "stages": [_stage("甲登场。")]},
            {"chapter": 2, "title": "T2", "core_xp": ["x"], "stages": [_stage("乙登场。")]},
            {"chapter": 3, "title": "T3", "core_xp": ["x"], "stages": [_stage("甲登场。")]},
        ])

        from engine.setup_chat.tools import _delete_chapter_core
        ok, msg, detail = await _delete_chapter_core(2)
        assert ok

        chapters = sorted(c["chapter"] for c in get_plot_repo().list_raw())
        assert chapters == [1, 2]
        by_ch = {c["chapter"]: c for c in get_plot_repo().list_raw()}
        assert by_ch[2]["title"] == "T3"  # old chapter 3, shifted down


@pytest.mark.asyncio
async def test_delete_chapter_only_rescopes_its_own_roster(tmp_path, monkeypatch):
    """甲 (also in the surviving chapter 3->2) must NOT be scheduled for re-derivation just
    because a chapter shifted under them; only 乙 (was in the deleted chapter) gets rescoped."""
    _novel(tmp_path, monkeypatch, "delete-novel-2")
    with use_novel("delete-novel-2"):
        from repositories import get_lore_repo, get_plot_repo
        get_lore_repo().save_all([
            {"name": "甲", "given_name": "甲"},
            {"name": "乙", "given_name": "乙"},
        ])
        get_plot_repo().save_all([
            {"chapter": 1, "title": "T1", "core_xp": ["x"], "stages": [_stage("甲登场。")]},
            {"chapter": 2, "title": "T2", "core_xp": ["x"], "stages": [_stage("乙登场。")]},
            {"chapter": 3, "title": "T3", "core_xp": ["x"], "stages": [_stage("甲登场。")]},
        ])

        scheduled: list[tuple[int, list[str]]] = []

        def _fake_schedule(min_chapter, names=None, **kw):
            scheduled.append((min_chapter, list(names or [])))

        import engine.setup_chat.timeline_auto as timeline_auto
        monkeypatch.setattr(timeline_auto, "schedule_timeline_cascade", _fake_schedule)
        import engine.setup_chat.tools as tools_mod
        monkeypatch.setattr(tools_mod, "schedule_timeline_cascade", _fake_schedule, raising=False)

        from engine.setup_chat.tools import _delete_chapter_core
        await _delete_chapter_core(2)

        assert scheduled == [(2, ["乙"])]
