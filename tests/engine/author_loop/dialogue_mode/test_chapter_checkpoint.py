"""chapter_checkpoint 同步读/管:异步图写 → 同步读 parts/scan/clear 往返。

退役 AuthorCheckpoint 后 save_author_loop_chapter / clear_author_loop / _scan_resumable
都依赖此路径,故锁一条 async-write / sync-read 的回归(现走 ReAct 回合门控图,逐 stage 推进)。"""
import pytest
from engine.author_loop.dialogue_mode import react_graph as rg
from engine.author_loop.dialogue_mode.chapter_checkpoint import (
    clear_chapter_thread,
    read_chapter_parts,
    scan_resumable_chapters,
)
from engine.author_loop.dialogue_mode.state import BeatInput, StageInput


class _FakeTurns:
    """prose_turn 按 stage 出 [bN]。"""

    async def prose_turn(self, messages, *, step):
        return f"[b{step + 1}]"


async def _fake_llm(s, u, *a, **k):
    return ("x", 1, 1)


def _stages():
    return [
        StageInput(chapter=1, stage=1, characters=["甲"],
                  beats=[BeatInput(beat_intent="b1", characters=["甲"], chapter=1, stage=1)]),
        StageInput(chapter=1, stage=2, characters=["甲"],
                  beats=[BeatInput(beat_intent="b2", characters=["甲"], chapter=1, stage=2)]),
    ]


@pytest.mark.asyncio
async def test_read_scan_clear_roundtrip(tmp_path):
    cp = str(tmp_path / "g.sqlite")
    await rg.run_react_chapter_persisted(_stages(), _FakeTurns(), _fake_llm,
                                         cp_path=cp, thread_id="ch3")

    #同步读:完整 parts + scan 反解章号
    assert read_chapter_parts(cp, "ch3") == ["[b1]", "[b2]"]
    assert scan_resumable_chapters(cp) == [3]

    #清理后读空、scan 空
    clear_chapter_thread(cp, "ch3")
    assert read_chapter_parts(cp, "ch3") == []
    assert scan_resumable_chapters(cp) == []


def test_read_missing_db_returns_empty(tmp_path):
    cp = str(tmp_path / "nope.sqlite")
    assert read_chapter_parts(cp, "ch1") == []
    assert scan_resumable_chapters(cp) == []
    clear_chapter_thread(cp, "ch1")  #不崩
