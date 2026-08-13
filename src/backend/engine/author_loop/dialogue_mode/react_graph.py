"""回合门控图:整章一条 messages 线程,引擎控回合,主笔只写正文。

热路径:task_packet(投喂整个 stage 的任务包)→ author_prose(主笔一次性写完这个 stage 的
候选正文)→ review_stage(保真/字数/文风审核,通过或重试耗尽后定稿)→ advance。角色动态态
(psychology/posture/clothing/action/demeanor)由 state_derive 在章开场与各 stage 定稿后
LLM 推演(见 state_derive.py),不再从 archive 读取。"""
from __future__ import annotations

import asyncio
import logging
import operator
import os
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Protocol, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from engine.author_loop.dialogue_mode.alarm import record_census, report_alarm
from engine.author_loop.dialogue_mode.cards import render_character_card
from engine.author_loop.dialogue_mode.stage_review import (
    render_review_feedback,
    review_candidate,
)
from engine.author_loop.dialogue_mode.state_derive import (
    derive_character_states,
    derive_initial_states,
)
from engine.author_loop.dialogue_mode.turns import (
    build_system_prompt,
    render_task_packet,
    with_log,
)

CallLLM = Callable[..., Awaitable[tuple[str, int, int]]]

_log = logging.getLogger(__name__)

KEEP_FULL_STAGES = 1   #给 LLM 的视图保留最近 N 个已完成 stage 的完整回合;更早的坍缩成骨架概要
MAX_STAGE_REVIEW_RETRIES = 2


class AuthorTurns(Protocol):
    """主笔回合执行体:只写正文(带整章记忆)。由 hub 实现真 LLM 版。"""

    async def prose_turn(self, messages: list, *, step: int) -> str: ...


class ReactChapterState(TypedDict, total=False):
    """整章图状态:messages 记忆本体 + 队列 + 累加通道。"""

    #── 线程与队列 ──
    messages: Annotated[list[AnyMessage], add_messages]   #整章记忆本体
    stages: list[dict]            #StageInput 序列化(chapter/stage/characters/beats/index)
    stage_idx: int

    #── 累加通道 ──
    parts: Annotated[list[str], operator.add]
    part_stage_idx: Annotated[list[int], operator.add]   #parts[j] 源自 stages[part_stage_idx[j]](空正文 stage 被跳过,故不能按位置对齐)
    part_character_states: Annotated[list[dict], operator.add]   #跟 parts/part_stage_idx 同位对齐的逐 part 状态快照

    #── 单 stage 控制字段(每 stage task_packet 重置) ──
    character_states: dict[str, dict]  # 当前动态状态(5 字段),供本 stage task_packet 组卡片用
    prose: str                        #本 stage 最新一版正文
    stage_review_retry_count: int     #本 stage 审核重试计数(每 stage 在 task_packet 重置为 0)
    review_decision: str              #review_stage 节点写、_route_review 读的图内部路由信号


def _emit_of(config: RunnableConfig | None):
    """从 config 取 emit 回调;默认 → None(测试/无前端时静默)。"""
    if not config:
        return None
    return (config.get("configurable") or {}).get("emit")


def _tag(msg: AnyMessage, stage_idx: int) -> AnyMessage:
    """给消息打 stage 序号标记(additional_kwargs),供 _llm_view 按 stage 坍缩;不改消息语义。"""
    msg.additional_kwargs = {**(msg.additional_kwargs or {}), "stage_idx": stage_idx}
    return msg


def _stage_skeleton_text(stage: dict) -> str:
    """该 stage 全部 beat 的骨架 text 拼接,供坍缩后的骨架概要使用。"""
    return "\n".join(str(b.get("beat_intent") or "").strip()
                     for b in (stage.get("beats") or []) if isinstance(b, dict))


def _llm_view(state: ReactChapterState) -> list:
    """给 LLM 的历史视图:比最近 KEEP_FULL_STAGES 个 stage 更早的回合坍缩成一条骨架概要。

    记忆=质量来源,但旧 stage 的中间回合(任务包/正文)在定稿后只剩噪音;正文事实由骨架代表
    (零 LLM,骨架即已验证的免费摘要)。只压视图不动 checkpoint:resume/审计/save 全量保留;
    坍缩块内容一经生成永不再变,历史仍是稳定前缀,前缀缓存基本不丢。"""
    cutoff = int(state.get("stage_idx", 0)) - KEEP_FULL_STAGES
    if cutoff <= 0:
        return list(state["messages"])
    stages = state.get("stages") or []
    out: list = []
    compacted: set[int] = set()
    for m in state["messages"]:
        s = (getattr(m, "additional_kwargs", None) or {}).get("stage_idx")
        if not isinstance(s, int) or s >= cutoff:
            out.append(m)
            continue
        if s in compacted:
            continue
        compacted.add(s)
        skeleton = _stage_skeleton_text(stages[s]) if s < len(stages) else ""
        out.append(AIMessage(content=f"【第 {s + 1} 个 stage 定稿概要】\n{skeleton}"))
    return out


def _task_packet_node(call_llm: CallLLM):
    """投喂本 stage 任务包 + 重置单 stage 控制字段。stage_idx==0 时先推演一次开场动态状态(见
    state_derive.derive_initial_states)并广播一次进入态，之后每个 stage 沿用图内
    character_states。生成前额外跑一次跨章记忆召回(engine.memory_recall.recall),按
    stage.characters 作为在场角色过滤语义假阳性,冷却窗口落盘持久化、不按章节重置。"""
    async def _n(state: ReactChapterState, config: RunnableConfig) -> dict:
        from repositories.entities import MemoryOrigin

        from engine.memory_recall.event_log import (
            load_event_log,
            load_recall_cooldown,
            save_recall_cooldown,
        )
        from engine.memory_recall.recall import recall_relevant_context
        from engine.modes.author_loop_skill_prefs import load_dialogue_prefs

        recall_prefs = load_dialogue_prefs()
        recall_cooldown_turns = recall_prefs.get("recall_cooldown_turns", 10)
        recall_top_k = recall_prefs.get("recall_top_k", 5)

        i = state["stage_idx"]
        stage = state["stages"][i]

        parts = state.get("parts") or []
        prior_prose = parts[-1] if parts else ""
        turn_index = len(load_event_log().get("entries") or [])
        active_cast = dict.fromkeys(stage.get("characters") or [], 0)
        recall_context, updated_cooldown, _recalled_settings = await asyncio.to_thread(
            recall_relevant_context,
            _stage_skeleton_text(stage), chapter=stage["chapter"], origin=MemoryOrigin.AUTHOR_LOOP,
            prior_prose=prior_prose, turn_index=turn_index, cooldown=load_recall_cooldown(),
            active_cast=active_cast, max_items=recall_top_k, cooldown_turns=recall_cooldown_turns,
        )
        save_recall_cooldown(updated_cooldown)

        emit = _emit_of(config)
        if emit is not None:
            await _emit_recall(emit, i, recall_context)

        character_states = state.get("character_states") or {}
        update: dict[str, Any] = {
            "messages": [_tag(
                HumanMessage(content=render_task_packet(
                    stage=stage, character_states=character_states,
                    recall_context=recall_context,
                )), i,
            )],
            "prose": "",
            "stage_review_retry_count": 0,
        }
        if i == 0:
            characters = list(stage.get("characters") or [])
            cards = [
                {"name": name, "card": render_character_card(name, stage["chapter"], stage["stage"])}
                for name in characters
            ]
            stage_description = _stage_skeleton_text(stage)
            initial = await derive_initial_states(
                cards, stage_description, with_log(call_llm, step=i, agent="state_derive"),
            )
            update["character_states"] = initial
            if emit is not None:
                await _emit_entry_state(emit, initial)
        return update
    return _n


def _author_prose_node(author_turns: AuthorTurns):
    """主笔基于整章记忆写本 stage 候选正文——只生成,不定稿(定稿动作挪进 _finalize_stage,
    只在 review_stage 判定通过或重试耗尽后调用一次,避免重试时重复 emit/累加 parts)。"""
    async def _n(state: ReactChapterState) -> dict:
        i = state["stage_idx"]
        text = await author_turns.prose_turn(_llm_view(state), step=i)
        prose = (text or "").strip()
        return {"messages": [_tag(AIMessage(content=text), i)], "prose": prose}
    return _n


def _bare_call_llm(call_llm: CallLLM, *, step: int, agent: str):
    """把 author_loop 的 (text, tokens_in, tokens_out) 三元组返回适配成
    engine.story_sandbox.summary_fold.fold_turn_into_summary 要求的纯文本返回签名,同时挂上
    with_log 的 prompt 日志归属标记。"""
    tagged = with_log(call_llm, step=step, agent=agent)

    async def _c(system: str, user: str) -> str:
        text, _tokens_in, _tokens_out = await tagged(system, user)
        return text
    return _c


async def _archive_stage_event(
    stage: dict, prose: str, chapter: int, characters: list[str], i: int,
    call_llm: CallLLM, emit,
) -> None:
    """Distill finalized stage prose into zero or more event_log entries (same extract_events
    path as sandbox), persist, archive to vector memory, and broadcast to the frontend. Failure
    never blocks stage finalization -- same best-effort posture as event_log.py's OSError handling."""
    from repositories.entities import MemoryOrigin

    from engine.memory_recall.event_log import (
        append_event_entries,
        build_event_entries,
        load_event_log,
    )

    turn_index = len(load_event_log().get("entries") or [])
    entries = await build_event_entries(
        prose, _bare_call_llm(call_llm, step=i, agent="memory_recall"),
        chapter=chapter, turn_index=turn_index, present=characters,
        origin=MemoryOrigin.AUTHOR_LOOP,
    )
    if not entries:
        return
    await append_event_entries(entries)
    try:
        from repositories import get_sandbox_vector_memory_repo
        await get_sandbox_vector_memory_repo().archive(entries)
    except (OSError, RuntimeError, ValueError):
        _log.exception("author_loop event archive failed")
    if emit is not None:
        await emit({"type": "author_loop_event_log", "index": i, "entries": [
            {
                "summary": e["summary"], "time": e["time"],
                "location": e["location"], "characters": e["characters"],
            }
            for e in entries
        ]})


async def _finalize_stage(
    config: RunnableConfig, i: int, stage: dict, prose: str, chapter: int, stage_num: int,
    character_states: dict[str, dict], call_llm: CallLLM,
) -> dict:
    """本 stage 定稿:emit segment + parts 累加 + 推演下一状态 + 广播角色态 + 归档跨章记忆。由
    review_stage 在通过审核或重试耗尽(带病落账)后调用,只调一次——不能挪回 author_prose,否则
    重试会重复 emit。"""
    emit = _emit_of(config)
    if emit is not None:
        await emit({"type": "author_loop_segment", "index": i,
                    "mode": "dialogue", "agent": "synthesis", "text": prose,
                    "intent": _stage_skeleton_text(stage)})
    update: dict[str, Any] = {}
    if prose:
        derived = await derive_character_states(
            character_states, prose, with_log(call_llm, step=i, agent="state_derive"),
        )
        new_states = {**character_states, **derived}
        update["parts"] = [prose]
        update["part_stage_idx"] = [i]
        update["character_states"] = new_states
        update["part_character_states"] = [new_states]
        characters = list(stage.get("characters") or [])
        if characters and emit is not None:
            await _emit_stage_state(emit, i, characters, new_states)
        await _archive_stage_event(stage, prose, chapter, characters, i, call_llm, emit)
    return update


def _review_stage_node(call_llm: CallLLM):
    """审核门控:保真/字数/文风三项检查(map-reduce,见 stage_review.py)。
    空正文直接定稿(没有可审的内容,维持原有"空正文跳过"不变量)。"""
    async def _n(state: ReactChapterState, config: RunnableConfig) -> dict:
        i = state["stage_idx"]
        stage = state["stages"][i]
        prose = state.get("prose") or ""
        chapter, stage_num = int(stage.get("chapter", 0)), int(stage.get("stage", 0))

        if not prose:
            update = await _finalize_stage(
                config, i, stage, prose, chapter, stage_num,
                state.get("character_states") or {}, call_llm,
            )
            update["review_decision"] = "advance"
            return update

        skeleton_text = _stage_skeleton_text(stage)
        result = await review_candidate(
            skeleton_text=skeleton_text, prose=prose,
            call_llm=with_log(call_llm, step=i, agent="stage_review"),
        )

        if result.passed:
            update = await _finalize_stage(
                config, i, stage, prose, chapter, stage_num,
                state.get("character_states") or {}, call_llm,
            )
            update["review_decision"] = "advance"
            return update

        retry_count = state.get("stage_review_retry_count", 0)
        if retry_count >= MAX_STAGE_REVIEW_RETRIES:
            report_alarm("章节审核-带病落账", chapter=chapter, stage=stage_num,
                        issues="; ".join(result.notes))
            record_census("章节审核", chapter=chapter, stage=stage_num,
                          checks=1, fires=1)
            update = await _finalize_stage(
                config, i, stage, prose, chapter, stage_num,
                state.get("character_states") or {}, call_llm,
            )
            update["review_decision"] = "advance"
            return update

        feedback = render_review_feedback(result)
        return {
            "messages": [_tag(HumanMessage(content=feedback), i)],
            "stage_review_retry_count": retry_count + 1,
            "review_decision": "retry",
        }
    return _n


def _route_review(state: ReactChapterState) -> str:
    return state.get("review_decision", "advance")


async def _advance_node(state: ReactChapterState, config: RunnableConfig) -> dict:
    """本 stage 收尾:广播进度 + 推进 stage_idx(路由由 _route_advance 决定回环/结束)。"""
    i = state["stage_idx"]
    total = len(state["stages"])
    emit = _emit_of(config)
    if emit is not None:
        chapter = int((state["stages"][0] or {}).get("chapter", 0) or 0) if state["stages"] else 0
        await emit({"type": "author_loop_chapter_progress", "done": i + 1, "total": total,
                    "chapter": chapter, "mode": "dialogue"})
    return {"stage_idx": i + 1}


def _route_advance(state: ReactChapterState) -> str:
    return "continue" if state["stage_idx"] < len(state["stages"]) else "end"


#──────────────────────── 前端事件广播(从旧 chapter_graph 原样复制) ────────────────────────
def _state_row(name: str, dyn: dict) -> dict:
    """角色动态态 → 前端状态行(5 字段)。"""
    return {
        "name": name,
        "psychology": str(dyn.get("psychology") or ""),
        "posture": str(dyn.get("posture") or ""),
        "clothing": str(dyn.get("clothing") or ""),
        "action": str(dyn.get("action") or ""),
        "demeanor": str(dyn.get("demeanor") or ""),
    }


async def _emit_stage_state(
    emit, i: int, characters: list[str], character_states: dict[str, dict],
) -> None:
    """广播本 stage 各在场角色动态态(来自图内刚推演出的 character_states)。"""
    rows = [_state_row(name, character_states[name]) for name in characters if name in character_states]
    if rows:
        await emit({"type": "author_loop_state", "index": i, "characters": rows, "mode": "dialogue"})


async def _emit_entry_state(emit, initial_states: dict[str, dict]) -> None:
    """开跑前广播开场推演结果,index=-1 + entry 标记,避与逐 stage 态撞 id。"""
    if not initial_states:
        return
    rows = [_state_row(name, dyn) for name, dyn in initial_states.items()]
    if rows:
        await emit({"type": "author_loop_state", "index": -1, "entry": True,
                    "characters": rows, "mode": "dialogue"})


async def _emit_recall(emit, i: int, recall_context: str) -> None:
    """广播本 stage 生成前召回到的跨章记忆(可能为空字符串,仍然广播——让前端能确认这个机制
    确实跑过,而不是静默不出现)。"""
    await emit({"type": "author_loop_recall", "index": i, "recall_context": recall_context})


#──────────────────────── 装配 & runner ────────────────────────
def build_react_chapter_graph(
    author_turns: AuthorTurns, call_llm: CallLLM, *,
    checkpointer: Any = None,
):
    """装配回合门控图(正文热路径,逐 stage 推进,含审核重试回环)。"""
    g: StateGraph = StateGraph(ReactChapterState)
    g.add_node("task_packet", _task_packet_node(call_llm))
    g.add_node("author_prose", _author_prose_node(author_turns))
    g.add_node("review_stage", _review_stage_node(call_llm))
    g.add_node("advance", _advance_node)

    g.add_edge(START, "task_packet")
    g.add_edge("task_packet", "author_prose")
    g.add_edge("author_prose", "review_stage")
    g.add_conditional_edges("review_stage", _route_review,
                            {"retry": "author_prose", "advance": "advance"})
    g.add_conditional_edges("advance", _route_advance, {"continue": "task_packet", "end": END})
    return g.compile(checkpointer=checkpointer)


def _stage_to_dict(stage, index: int) -> dict:
    """StageInput → JSON 可序列化 dict(checkpointer 通道需纯数据);带 index 供任务包标题。"""
    return {
        "chapter": stage.chapter,
        "stage": stage.stage,
        "characters": list(stage.characters),
        "beats": [
            {
                "beat_intent": b.beat_intent,
                "characters": list(b.characters),
                "chapter": b.chapter,
                "stage": b.stage,
                "sensation_notes": list(b.sensation_notes),
                "dialogue_draft": b.dialogue_draft,
            }
            for b in stage.beats
        ],
        "index": index,
    }


def _initial_state(stages: list[dict], *, prose_style: str = "") -> ReactChapterState:
    core_xp: list[str] = []
    if stages:
        from repositories import get_plot_repo

        core_xp = get_plot_repo().chapter_core_xp(stages[0]["chapter"])
    return {
        "messages": [SystemMessage(content=build_system_prompt(prose_style, core_xp))],
        "stages": stages,
        "stage_idx": 0,
        "parts": [],
        "part_stage_idx": [],
    }


async def run_react_chapter_graph(
    stages: list,
    author_turns: AuthorTurns,
    call_llm: CallLLM,
    emit=None,
    *,
    prose_style: str = "",
    checkpointer: Any = None,
    thread_id: str = "default",
    resume: bool = False,
) -> str:
    """跑整章回合循环,返回拼接正文。resume=True → 同 thread_id 从 checkpoint 续跑。"""
    graph = build_react_chapter_graph(
        author_turns, call_llm, checkpointer=checkpointer,
    )
    total = len(stages)
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id, "emit": emit},
        "recursion_limit": total * 20 + 20,   #每 stage 最多 MAX_STAGE_REVIEW_RETRIES 次重试,每次 2 跳(author_prose+review_stage)
    }
    if emit is not None:
        chapter = int(getattr(stages[0], "chapter", 0) or 0) if stages else 0
        done_at_start = 0
        if resume and checkpointer is not None:
            tup = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id}})
            if tup and tup.checkpoint:
                cv = tup.checkpoint.get("channel_values") or {}
                done_at_start = int(cv.get("stage_idx") or 0)
        await emit({"type": "author_loop_chapter_progress", "done": done_at_start, "total": total,
                    "chapter": chapter, "mode": "dialogue"})
    if resume:
        init = None
    else:
        stage_dicts = [_stage_to_dict(s, i) for i, s in enumerate(stages)]
        init = _initial_state(stage_dicts, prose_style=prose_style)
    final: ReactChapterState = await graph.ainvoke(init, config)
    return "\n\n".join(final.get("parts") or [])


async def run_react_chapter_persisted(
    stages: list,
    author_turns: AuthorTurns,
    call_llm: CallLLM,
    emit=None,
    *,
    prose_style: str = "",
    cp_path: str,
    thread_id: str,
    resume: bool = False,
) -> str:
    """整章图 + LangGraph 原生 sqlite checkpointer(镜像旧 persisted:新跑清旧线程)。"""
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    os.makedirs(os.path.dirname(cp_path) or ".", exist_ok=True)
    conn = await aiosqlite.connect(cp_path)
    try:
        checkpointer = AsyncSqliteSaver(conn)
        await checkpointer.setup()
        cfgk: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        has_cp = (await checkpointer.aget_tuple(cfgk)) is not None
        do_resume = resume and has_cp
        if not do_resume and has_cp:
            await checkpointer.adelete_thread(thread_id)  #新跑清旧线程,防 operator.add 累加叠章
        return await run_react_chapter_graph(
            stages, author_turns, call_llm, emit=emit,
            prose_style=prose_style,
            checkpointer=checkpointer, thread_id=thread_id, resume=do_resume,
        )
    finally:
        await conn.close()
