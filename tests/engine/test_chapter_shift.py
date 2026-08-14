"""shift_chapters is the single mechanical renumbering entry point -- see its docstring for
the full inventory of stores it must touch. These tests cover the core stores (plot/timeline/
archives/disk/author-loop checkpoint); sandbox-specific stores (vector memory, story_sandbox_
branches, sandbox checkpoint) are covered in test_chapter_shift_sandbox.py (Task 2)."""
import os

import pytest
from utils.paths import get_chapter_dir, use_novel


def _novel(tmp_path, monkeypatch, novel_id="shift-novel"):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    from repositories import drop_repositories
    drop_repositories(novel_id)
    return novel_id


def _seed_chapters(n: int) -> None:
    """Chapters 1..n, each with one stage whose description names one character 甲<idx>, plus
    a lore_characters row for each so the FK constraint (Plan 1) is satisfied."""
    from repositories import get_lore_repo, get_plot_repo

    get_lore_repo().save_all([{"name": f"甲{i}"} for i in range(1, n + 1)])
    get_plot_repo().save_all([
        {
            "chapter": i, "title": f"T{i}", "core_xp": ["x"],
            "stages": [{"stage_num": 1, "description": f"甲{i} 登场。", "text": ""}],
        }
        for i in range(1, n + 1)
    ])


@pytest.mark.asyncio
async def test_shift_insert_moves_plot_chapters_up(tmp_path, monkeypatch):
    novel_id = _novel(tmp_path, monkeypatch)
    with use_novel(novel_id):
        _seed_chapters(3)
        from engine.setup_chat.chapter_shift import shift_chapters
        await shift_chapters(2, 1)

        from repositories import get_plot_repo
        chapters = sorted(c["chapter"] for c in get_plot_repo().list_raw())
        assert chapters == [1, 3, 4]
        by_ch = {c["chapter"]: c for c in get_plot_repo().list_raw()}
        assert by_ch[3]["title"] == "T2"
        assert by_ch[4]["title"] == "T3"


@pytest.mark.asyncio
async def test_shift_insert_leaves_untouched_prefix_alone(tmp_path, monkeypatch):
    novel_id = _novel(tmp_path, monkeypatch)
    with use_novel(novel_id):
        _seed_chapters(3)
        from engine.setup_chat.chapter_shift import shift_chapters
        await shift_chapters(2, 1)

        from repositories import get_plot_repo
        by_ch = {c["chapter"]: c for c in get_plot_repo().list_raw()}
        assert by_ch[1]["title"] == "T1"


@pytest.mark.asyncio
async def test_shift_delete_collapses_gap(tmp_path, monkeypatch):
    novel_id = _novel(tmp_path, monkeypatch)
    with use_novel(novel_id):
        _seed_chapters(4)
        from repositories import get_plot_repo
        get_plot_repo().save_all([
            c for c in get_plot_repo().list_raw() if c["chapter"] != 2
        ])
        from engine.setup_chat.chapter_shift import shift_chapters
        await shift_chapters(3, -1)

        chapters = sorted(c["chapter"] for c in get_plot_repo().list_raw())
        assert chapters == [1, 2, 3]
        by_ch = {c["chapter"]: c for c in get_plot_repo().list_raw()}
        assert by_ch[2]["title"] == "T3"
        assert by_ch[3]["title"] == "T4"


@pytest.mark.asyncio
async def test_shift_moves_timeline_snapshots_for_unaffected_character(tmp_path, monkeypatch):
    """A character not mentioned in the inserted chapter still has their existing delta content
    preserved byte-for-byte -- only the chapter coordinate moves."""
    novel_id = _novel(tmp_path, monkeypatch)
    with use_novel(novel_id):
        _seed_chapters(3)
        import context.character_timeline as tl
        tl.append_stage("甲2", 2, 1, {"personality": "沉稳"})
        tl.append_stage("甲3", 3, 1, {"personality": "热情"})

        from engine.setup_chat.chapter_shift import shift_chapters
        await shift_chapters(2, 1)

        moved = tl.get_stage("甲2", 3, 1)
        assert moved is not None and moved["delta"] == {"personality": "沉稳"}
        assert tl.get_stage("甲2", 2, 1) is None
        still = tl.get_stage("甲3", 4, 1)
        assert still is not None and still["delta"] == {"personality": "热情"}


@pytest.mark.asyncio
async def test_shift_evicts_character_archive_cache_in_range(tmp_path, monkeypatch):
    novel_id = _novel(tmp_path, monkeypatch)
    with use_novel(novel_id):
        _seed_chapters(3)
        from repositories import get_archive_repo
        get_archive_repo().save("甲2", 2, {"name": "甲2", "chapter": 2})

        from engine.setup_chat.chapter_shift import shift_chapters
        await shift_chapters(2, 1)

        # cache entry at the old coordinate must be gone (evicted, not migrated -- it's a
        # pure fold-cache, next read at the new coordinate rebuilds it for free)
        assert get_archive_repo().get("甲2", 2) is None


@pytest.mark.asyncio
async def test_shift_renames_chapter_directory(tmp_path, monkeypatch):
    novel_id = _novel(tmp_path, monkeypatch)
    with use_novel(novel_id):
        _seed_chapters(3)
        os.makedirs(get_chapter_dir(2), exist_ok=True)
        with open(os.path.join(get_chapter_dir(2), "marker.txt"), "w") as f:
            f.write("hello")

        from engine.setup_chat.chapter_shift import shift_chapters
        await shift_chapters(2, 1)

        assert not os.path.isdir(get_chapter_dir(2))
        assert os.path.isfile(os.path.join(get_chapter_dir(3), "marker.txt"))


@pytest.mark.asyncio
async def test_shift_no_op_past_max_chapter(tmp_path, monkeypatch):
    novel_id = _novel(tmp_path, monkeypatch)
    with use_novel(novel_id):
        _seed_chapters(2)
        from engine.setup_chat.chapter_shift import shift_chapters
        await shift_chapters(5, 1)  # nothing at/after chapter 5

        from repositories import get_plot_repo
        assert sorted(c["chapter"] for c in get_plot_repo().list_raw()) == [1, 2]


@pytest.mark.asyncio
async def test_shift_raises_when_a_chapter_in_range_has_a_live_checkpoint(tmp_path, monkeypatch):
    novel_id = _novel(tmp_path, monkeypatch)
    with use_novel(novel_id):
        _seed_chapters(3)
        from engine.author_loop.dialogue_mode.chapter_checkpoint import _open
        from utils.paths import author_loop_graph_checkpoint_path
        cp_path = author_loop_graph_checkpoint_path()
        os.makedirs(os.path.dirname(cp_path), exist_ok=True)
        saver, conn = _open(cp_path)
        saver.put(
            {"configurable": {"thread_id": "ch2", "checkpoint_ns": ""}},
            {"v": 1, "ts": "t", "id": "c1", "channel_values": {}},
            {},
            {},
        )
        conn.close()

        from engine.setup_chat.chapter_shift import ChapterBusyError, shift_chapters
        with pytest.raises(ChapterBusyError):
            await shift_chapters(2, 1)
