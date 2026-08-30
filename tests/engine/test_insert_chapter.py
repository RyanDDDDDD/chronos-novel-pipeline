import pytest
from utils.paths import use_novel


def _stage(desc: str) -> dict:
    return {"title": "S", "location": "L", "description": desc}


def _novel(tmp_path, monkeypatch, novel_id: str) -> None:
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    from repositories import drop_repositories
    drop_repositories(novel_id)
    from engine.memory_recall.entity_index import invalidate_entity_vocab_cache
    invalidate_entity_vocab_cache(novel_id)
    # 1-stage chapters are valid at 350 words; the live default (3000) requires 2 stages.
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"target_words": 350},
    )


@pytest.mark.asyncio
async def test_insert_chapter_shifts_and_writes_new_slot(tmp_path, monkeypatch):
    _novel(tmp_path, monkeypatch, "insert-novel")
    with use_novel("insert-novel"):
        from repositories import get_lore_repo, get_plot_repo
        get_lore_repo().save_all([
            {"name": "甲", "given_name": "甲"},
            {"name": "乙", "given_name": "乙"},
        ])
        get_plot_repo().save_all([
            {"chapter": 1, "title": "T1", "core_xp": ["x"], "stages": [{"stage_num": 1, "description": "甲登场。"}]},
            {"chapter": 2, "title": "T2", "core_xp": ["x"], "stages": [{"stage_num": 1, "description": "甲登场。"}]},
        ])

        from engine.setup_chat.tools import insert_chapter
        msg = await insert_chapter.ainvoke({
            "after_chapter": 1, "title": "新章", "core_xp": ["y"],
            "stages": [_stage("乙登场。")],
        })
        assert "已插入" in msg or "第 2 章" in msg

        # list_raw is chapter-ordered even though the inserted chapter has the highest seq
        chapters = [c["chapter"] for c in get_plot_repo().list_raw()]
        assert chapters == [1, 2, 3]
        by_ch = {c["chapter"]: c for c in get_plot_repo().list_raw()}
        assert by_ch[2]["title"] == "新章"
        assert by_ch[3]["title"] == "T2"  # shifted, content preserved


@pytest.mark.asyncio
async def test_insert_chapter_only_schedules_cascade_for_its_own_roster(tmp_path, monkeypatch):
    """甲 (unaffected -- not mentioned in the inserted chapter) must not get scheduled for
    re-derivation; 乙 (mentioned in the inserted chapter) must."""
    _novel(tmp_path, monkeypatch, "insert-novel-2")
    with use_novel("insert-novel-2"):
        from repositories import get_lore_repo, get_plot_repo
        get_lore_repo().save_all([
            {"name": "甲", "given_name": "甲"},
            {"name": "乙", "given_name": "乙"},
        ])
        get_plot_repo().save_all([
            {"chapter": 1, "title": "T1", "core_xp": ["x"], "stages": [{"stage_num": 1, "description": "甲登场。"}]},
        ])

        scheduled: list[tuple[int, list[str]]] = []

        def _fake_schedule(min_chapter, names=None, **kw):
            scheduled.append((min_chapter, list(names or [])))

        import engine.setup_chat.timeline_auto as timeline_auto
        monkeypatch.setattr(timeline_auto, "schedule_timeline_cascade", _fake_schedule)
        import engine.setup_chat.tools as tools_mod
        monkeypatch.setattr(tools_mod, "schedule_timeline_cascade", _fake_schedule, raising=False)

        from engine.setup_chat.tools import insert_chapter
        await insert_chapter.ainvoke({
            "after_chapter": 1, "title": "新章", "core_xp": ["y"],
            "stages": [_stage("乙登场。")],
        })

        assert scheduled == [(2, ["乙"])]
