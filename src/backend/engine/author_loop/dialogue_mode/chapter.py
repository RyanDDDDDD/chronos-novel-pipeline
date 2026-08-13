"""行驱动模式·整章入口:预建 beats → extract_stages → 整章 ReAct 回合门控图(react_graph)。

整章是一条 messages 线程 + 引擎回合门控(见 react_graph.py),续跑走原生 sqlite checkpointer;
主笔调用粒度=stage(整 stage 一次性产出正文),状态直读 archive,按 stage 坐标自然演变。"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from engine.author_loop.dialogue_mode.state import BeatInput, StageInput

if TYPE_CHECKING:
    from engine.author_loop.dialogue_mode.react_graph import AuthorTurns

CallLLM = Callable[..., Awaitable[tuple[str, int, int]]]
Emit = Callable[[dict], Awaitable[None]]


def extract_stages(skeleton: list[dict], chapter: int) -> list[StageInput]:
    """预建分拍底稿 → StageInput 列表:逐 stage 聚合该段全部 beat,characters 取该 stage 内所有
    beat 的角色并集(按首次出现顺序去重)。拍边界由构建期 chat agent 分镜决定(不再运行期机械切割);
    stage 内 beats 全部为空文本的段落不产出(没有可写内容)。"""
    out: list[StageInput] = []
    for seg in skeleton:
        chars = [c for c in (seg.get("characters") or []) if c]
        #真实骨架(stages_to_segments)用 key stage_num;兼容历史/测试保留 stage。
        #读错 key 会让每 stage 默认 stage=1 → 状态解析钉死 stage 1(心理冻结)。
        stage = int(seg.get("stage_num", seg.get("stage", 1)) or 1)
        beats: list[BeatInput] = []
        for b in seg.get("beats") or []:
            if not isinstance(b, dict):
                continue
            text = str(b.get("text") or "").strip()
            if not text:
                continue
            beats.append(BeatInput(
                beat_intent=text,
                characters=chars,
                chapter=chapter,
                stage=stage,
                sensation_notes=[str(x).strip() for x in (b.get("sensation_notes") or [])
                                  if str(x).strip()],
                dialogue_draft=str(b.get("dialogue_draft") or "").strip(),
            ))
        if not beats:
            continue
        out.append(StageInput(chapter=chapter, stage=stage, characters=chars, beats=beats))
    return out


def extract_entry_points(stages: list[StageInput]) -> dict[str, int]:
    """每角色本章首次出场的 stage 号(取自已聚合的 StageInput 序列,不重新扫 skeleton 原始 dict)。

    状态已改直读 archive(见 chapter_state.py),这里只需要"该角色进入态该以哪个 stage 坐标广播"
    这一个更小的坐标集合,不再需要 recap/clothing 字段(那是给已退役的运行期 LLM seed 用的)。"""
    out: dict[str, int] = {}
    for s in stages:
        for c in s.characters:
            if c not in out:
                out[c] = s.stage
    return out


async def run_dialogue_chapter(
    chapter: int,
    call_llm: CallLLM,
    prose_style: str = "",
    emit: Emit | None = None,
    *,
    resume: bool = False,
    author_turns: AuthorTurns,
) -> str:
    """整章入口:读预建骨架 → extract_stages → 整章 ReAct 回合门控图(原生 checkpointer)。"""
    from utils.paths import author_loop_graph_checkpoint_path

    from engine.author_loop.build import SkeletonNotBuiltError, load_prebuilt_skeleton
    from engine.author_loop.dialogue_mode.react_graph import run_react_chapter_persisted

    try:
        skeleton = load_prebuilt_skeleton(chapter)
    except SkeletonNotBuiltError as exc:
        if emit is not None:
            await emit({"type": "author_loop_error", "chapter": chapter, "error": str(exc)})
        return ""
    stages = extract_stages(skeleton, chapter)
    return await run_react_chapter_persisted(
        stages,
        author_turns,
        call_llm,
        emit=emit,
        prose_style=prose_style,
        cp_path=author_loop_graph_checkpoint_path(),
        thread_id=f"ch{chapter}",
        resume=resume,
    )
