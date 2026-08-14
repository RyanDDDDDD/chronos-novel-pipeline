"""write_character_archive must reject names that were never added via add_character --
this is the single production path with a free-text `name` param, so it's the one place
that needs to gate against the roster before the FK constraint (added later) would otherwise
turn a typo into a raw sqlite IntegrityError instead of an actionable message."""
import pytest
from utils.paths import use_novel


@pytest.mark.asyncio
async def test_write_character_archive_rejects_unknown_name(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    from engine.setup_chat.tools import write_character_archive
    from repositories import get_plot_repo, init_repositories

    with use_novel("test-novel"):
        init_repositories("test-novel")
        get_plot_repo().save_all([{"chapter": 1, "title": "T", "stages": []}])
        msg = await write_character_archive.ainvoke({
            "chapter": 1, "name": "查无此人",
            "profile": {"personality": "开朗"},
        })
        assert "花名册" in msg or "add_character" in msg


@pytest.mark.asyncio
async def test_write_character_archive_accepts_known_name(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    from engine.setup_chat.tools import write_character_archive
    from repositories import get_lore_repo, get_plot_repo, init_repositories

    with use_novel("test-novel"):
        init_repositories("test-novel")
        get_plot_repo().save_all([{"chapter": 1, "title": "T", "stages": []}])
        get_lore_repo().save_all([{"name": "甲", "role": "lead"}])
        msg = await write_character_archive.ainvoke({
            "chapter": 1, "name": "甲",
            "profile": {"personality": "开朗"},
        })
        assert "花名册" not in msg
