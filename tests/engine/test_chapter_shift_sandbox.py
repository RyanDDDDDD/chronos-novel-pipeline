import pytest
from utils.paths import use_novel


def _novel(tmp_path, monkeypatch, novel_id: str) -> str:
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    from repositories import drop_repositories
    drop_repositories(novel_id)
    return novel_id


@pytest.mark.asyncio
async def test_shift_moves_story_sandbox_branch_chapter_field(tmp_path, monkeypatch):
    _novel(tmp_path, monkeypatch, "shift-sandbox-novel")
    with use_novel("shift-sandbox-novel"):
        from repositories import get_lore_repo, get_plot_repo
        get_lore_repo().save_all([{"name": "甲"}])
        get_plot_repo().save_all([
            {"chapter": 1, "title": "T1", "core_xp": ["x"], "stages": [{"stage_num": 1, "description": "甲登场。"}]},
            {"chapter": 2, "title": "T2", "core_xp": ["x"], "stages": [{"stage_num": 1, "description": "甲登场。"}]},
        ])
        from engine.story_sandbox import branches as sandbox_branches
        record = sandbox_branches.create_branch(2, "故事线1")

        from engine.setup_chat.chapter_shift import shift_chapters
        await shift_chapters(2, 1)

        assert sandbox_branches.list_branches(2) == []
        moved = sandbox_branches.get_branch(3, record["id"])
        assert moved["name"] == "故事线1"


@pytest.mark.asyncio
async def test_shift_moves_vector_memory_fragment(tmp_path, monkeypatch):
    _novel(tmp_path, monkeypatch, "shift-sandbox-novel-2")
    with use_novel("shift-sandbox-novel-2"):
        from repositories import get_lore_repo, get_plot_repo
        get_lore_repo().save_all([{"name": "甲"}])
        get_plot_repo().save_all([
            {"chapter": 1, "title": "T1", "core_xp": ["x"], "stages": [{"stage_num": 1, "description": "甲登场。"}]},
            {"chapter": 2, "title": "T2", "core_xp": ["x"], "stages": [{"stage_num": 1, "description": "甲登场。"}]},
        ])
        from repositories import get_sandbox_vector_memory_repo
        vector_repo = get_sandbox_vector_memory_repo()
        await vector_repo.archive([{
            "id": "e1", "chapter": 2, "turn_index": 0, "summary": "甲登场",
            "characters": ["甲"], "entities": [],
        }])

        from engine.setup_chat.chapter_shift import shift_chapters
        await shift_chapters(2, 1)

        hits = vector_repo.query("甲登场", top_k=5)
        assert hits[0].chapter == 3
