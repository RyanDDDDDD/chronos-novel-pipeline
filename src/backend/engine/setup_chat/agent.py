"""Set up co-creation dialogue agent: create_react_agent assembly + single wheel drive."""
from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable

from loguru import logger
from utils.paths import (
    SKILLS_DIR,
    setup_chat_checkpoint_path,
)


def _tool_output_text(output: object) -> str:
    """The output of on_tool_end may be ToolMessage: take content (that is, the success/failure text returned to LLM)."""
    content = getattr(output, "content", output)
    return content if isinstance(content, str) else str(content)


def _load_prompt() -> str:
    path = os.path.join(SKILLS_DIR, "setup_chat_base.md")
    with open(path, encoding="utf-8") as f:
        return f.read()


_IDENTITY = "你是「设定共创编排者」，帮助用户反复对话打磨**一部具体小说**的世界观、人物、剧情。"


def resolved_default_identity() -> str:
    """Identity in effect when no pipeline `chat_identity` override is set:
    content-pack `active_identity()` takes precedence over the neutral default."""
    from context.content_packs import active_identity
    return active_identity() or _IDENTITY


_PROSE_FRAMING = (
    "## 文风基调（生成描述性文字时遵循）\n"
    "下面是当前小说的文风设定。你在写世界背景、场景描述、角色因果设定等**描述性文字**时贴合此基调；"
    "但势力名、章标题等**结构化字段保持简洁精炼**，勿堆砌辞藻、勿写成成段散文。"
)

_NOVEL_TITLE_FRAMING = (
    "## 当前小说\n"
    "标题：「{title}」\n"
    "可据此对题材/基调做初步判断。若判断标题信息量不足，或跟已构建的世界观/设定明显不符，"
    "可用 present_choices 向用户建议更贴切的标题，用户确认后再调用 rename_novel_title 执行；"
    "不要未经确认直接改，也不要反复提同一件事。"
)

_STAGE_COUNT_FRAMING = (
    "## 章节字数与 stage 数下限\n"
    "当前章节字数目标为 {target_words} 字/章。写整章章纲（generate_one_chapter）或局部增删段"
    "（patch_chapter）后，本章最终 stage 数不得少于 {suggested}——这是硬性校验，不达标会被拒绝"
    "写入并要求重试，不是可以斟酌的建议。"
)

# Module-level, set once by build_agent() -- memory.py's pre_model_hook reads it
# each turn to compute this turn's tool routing. None until the first
# build_agent() call (single agent singleton per process, rebuilt only on novel
# switch -- see reset_setup_chat).
_ALL_TOOLS: list | None = None
_TOOL_VECTORS: dict[str, list[float]] | None = None


def all_registered_tools() -> list:
    return list(_ALL_TOOLS or [])


def tool_vectors_cache() -> dict[str, list[float]]:
    return dict(_TOOL_VECTORS or {})


def compose_system_prompt() -> str:
    """
System prompt = identity + base + skill metadata index + current novel title + current novel style card.

    The title/style card change with the active novel (per-novel configuration); when the novel
    is changed, reset_setup_chat will discard the agent singleton. Build_agent will be rebuilt in
    the next round, so it will be updated automatically. With guardrails: The style is used for
    descriptive text, and structure fields are kept simple.

    Identity precedence: pipeline `chat_identity` (non-empty) > content-pack
    `active_identity()` > neutral `_IDENTITY` default -- see
    engine.modes.author_loop_skill_prefs.load_dialogue_prefs and
    `resolved_default_identity`."""

    from api.services.novels import get_novel_name
    from utils.paths import active_novel_id

    from engine.execution.prose_style import build_active_prose_style_card
    from engine.modes.author_loop_skill_prefs import DEFAULT_TARGET_WORDS, load_dialogue_prefs
    from engine.setup.plot.validator import suggested_min_stage_count
    from engine.setup_chat.skills import (
        render_skill_index,
        setup_chat_skill_dirs,
    )

    prefs = load_dialogue_prefs()
    custom_identity = str(prefs.get("chat_identity", "")).strip()
    target_words = prefs.get("target_words", DEFAULT_TARGET_WORDS)
    identity = custom_identity or resolved_default_identity()
    parts = [identity, _load_prompt()]
    index = render_skill_index(setup_chat_skill_dirs())
    if index:
        parts.append(index)
    title = get_novel_name(active_novel_id())
    parts.append(_NOVEL_TITLE_FRAMING.format(title=title))
    parts.append(_STAGE_COUNT_FRAMING.format(
        target_words=target_words, suggested=suggested_min_stage_count(target_words)))
    prose = build_active_prose_style_card()
    if prose:
        parts.append(f"{_PROSE_FRAMING}\n\n{prose}")
    return "\n\n".join(parts)


def _bind_chat_model(llm, all_tools: list, routed_names: set[str]) -> object:
    """Resolve the "chat_identity" node's configured model/sampling-param overrides onto
    `llm` and bind the routed tool subset -- the setup_chat agent's main model-selection
    step (`_select_model` in build_agent()), called fresh every turn so a saved
    model/param change takes effect without an agent rebuild (mirrors
    attachment_tool.py's image/text-recognition calls). Model swap must run before
    `.bind_tools()` (RunnableBinding, which sampling-param `.bind()` below produces, has
    no `.bind_tools()`); sampling params are layered on top of the tool-bound model
    instead."""
    from engine.modes.author_loop_skill_prefs import (
        load_dialogue_prefs,
        node_llm_sampling_kwargs,
        resolve_node_base_llm,
    )

    subset = [t for t in all_tools if t.name in routed_names] if routed_names else all_tools
    import_params = load_dialogue_prefs()["import_llm_params"]
    base_llm = resolve_node_base_llm(llm, "chat_identity", import_params)
    model = base_llm.bind_tools(subset)
    sampling = node_llm_sampling_kwargs(base_llm, "chat_identity", import_params)
    return model.bind(**sampling) if sampling else model


def clean_tool_error(e: Exception) -> str:
    """
ToolNode handle_tool_errors callback: Convert tool exceptions into short and actionable Chinese prompts.

    langgraph defaults to "Error invoking tool '...' with" when parameter verification fails (ToolInvocationError)
    kwargs {giant input parameters} ..." - long and difficult to understand. Weak models are easy to be confused into "I will adjust it" and then stop and not resend. Only return here
    For field-level errors, the full text of kwargs will never be returned; for other exceptions, a recoverable prompt will be given to avoid a complete crash.
    Use duck-typing to identify ToolInvocationError(tool_name + source=ValidationError) without coupling its inner class."""

    tool_name = getattr(e, "tool_name", None)
    source = getattr(e, "source", None)
    if tool_name and source is not None and hasattr(source, "errors"):
        lines: list[str] = []
        try:
            for err in source.errors():
                loc = ".".join(str(x) for x in err.get("loc", ()))
                msg = str(err.get("msg", "")).strip()
                if msg:
                    lines.append(f"{loc}：{msg}" if loc else msg)
        except (TypeError, AttributeError):
            lines = []
        detail = "\n".join(lines) or str(source)
        return (
            f"工具 {tool_name} 参数结构有误，未执行：\n{detail}\n"
            "请只修正出错字段后重新调用本工具（无需复述全部内容）。"
        )
    if isinstance(e, RecursionError):
        # 2026-08-12: repeated live-process-only RecursionErrors on write tools
        # (world_tools, edit_character) that never reproduce against the same
        # on-disk data in a fresh process -- the short repr logged via tool_trace
        # discards the traceback, so the actual recursive call chain has never
        # been captured. Log it in full here (exception carries __traceback__)
        # so the next occurrence is diagnosable instead of another guess.
        logger.opt(exception=e).error("[setup-chat] RecursionError in tool call — full traceback for diagnosis")
    return f"工具出错（{type(e).__name__}）：{e}。可调整后重试。"


async def build_agent():
    """
Assemble setup-chat agent: DeepSeek model + tools + system prompt + asynchronous Sqlite checkpointer.

    The agent is driven asynchronously by astream_events, so the checkpointer must use AsyncSqliteSaver (synchronous SqliteSaver
    aput will throw NotImplementedError). The connection is resident with the process-level singleton agent and is closed when the process exits."""

    import aiosqlite
    from langchain_core.messages import HumanMessage
    from langchain_core.messages import SystemMessage as _SM
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.prebuilt import create_react_agent
    from llm.factory import get_cloud_llm
    from utils.paths import setup_chat_dir

    from engine.setup_chat.attachment_tool import (
        build_prose_style_from_import,
        get_image_description,
        list_persisted_attachments,
        read_attachment,
        read_attachment_image,
        read_attachment_images,
        read_persisted_attachment,
    )
    from engine.setup_chat.hooks import make_post_model_hook
    from engine.setup_chat.memory import make_pre_model_hook
    from engine.setup_chat.research import (
        get_character,
        get_plot_points,
        get_world_facts,
        list_characters,
        recall_research,
        web_search,
    )
    from engine.setup_chat.skills import collect_skill_tools

    # add_character/edit_character bind a placeholder schema at @tool decorate time (LangChain
    # requires one); overwrite with a fresh schema on every build_agent() so gender/physique/
    # custom-field descriptions are not frozen at first tools.py import (2026-07-29
    # content-rating-schema-freeze-fix).
    from engine.setup_chat.tool_args import build_add_character_args, build_edit_character_args
    from engine.setup_chat.tools import (
        add_character,
        add_relationship_edge,
        auto_build_setup,
        auto_expand_skeleton,
        delete_chapter,
        delete_character,
        edit_character,
        edit_prose_style_preset,
        generate_one_chapter,
        list_prose_style_presets,
        load_skill,
        patch_chapter,
        patch_text_fragment,
        present_choices,
        query_character_voice,
        read_archive_seed,
        read_archive_status,
        read_author_manuscript,
        read_chapter_skeleton,
        read_character,
        read_character_archive,
        read_prose_style_preset,
        read_relationships,
        read_setup_summary,
        read_skeleton_seed,
        remove_relationship_edge,
        rename_novel_title,
        set_chapter_direction,
        set_stage_extensions,
        set_stage_lens,
        write_chapter_skeleton,
        write_character_archive,
        write_prose_style_preset,
    )
    from engine.setup_chat.transactional_tools import TransactionalToolNode
    from engine.setup_chat.world_tools import WORLD_DIMENSION_TOOLS
    add_character.args_schema = build_add_character_args()
    edit_character.args_schema = build_edit_character_args()

    llm = get_cloud_llm()

    async def _distill_llm(system: str, user: str) -> str:
        resp = await llm.ainvoke([_SM(content=system), HumanMessage(content=user)])
        c = resp.content if hasattr(resp, "content") else str(resp)
        return c if isinstance(c, str) else str(c)

    pre_hook = make_pre_model_hook(setup_chat_dir, _distill_llm)
    post_hook = make_post_model_hook(setup_chat_dir)

    cp_path = setup_chat_checkpoint_path()
    os.makedirs(os.path.dirname(cp_path), exist_ok=True)
    conn = await aiosqlite.connect(cp_path)
    checkpointer = AsyncSqliteSaver(conn)
    await checkpointer.setup()
    #Use explicit ToolNode to take over error formatting: tool exceptions return short and operable Chinese instead of langgraph's default giant dump.
    builtin_tools = [
        read_setup_summary,
        *WORLD_DIMENSION_TOOLS,
        auto_build_setup,
        add_character,
        generate_one_chapter,
        patch_chapter,
        patch_text_fragment,
        edit_character,
        read_archive_seed,
        read_archive_status,
        write_character_archive,
        set_chapter_direction,
        set_stage_lens,
        set_stage_extensions,
        write_chapter_skeleton,
        auto_expand_skeleton,
        read_character,
        read_character_archive,
        read_relationships,
        add_relationship_edge,
        remove_relationship_edge,
        delete_character,
        delete_chapter,
        read_skeleton_seed,
        read_chapter_skeleton,
        read_author_manuscript,
        query_character_voice,
        recall_research,
        web_search,
        list_characters,
        get_character,
        get_world_facts,
        get_plot_points,
        read_attachment,
        read_attachment_image,
        read_attachment_images,
        list_persisted_attachments,
        read_persisted_attachment,
        get_image_description,
        build_prose_style_from_import,
        write_prose_style_preset,
        edit_prose_style_preset,
        list_prose_style_presets,
        read_prose_style_preset,
        load_skill,
        present_choices,
        rename_novel_title,
    ]
    #skill 工具与内置工具撞名 → ToolNode 行为未定义，组装期就地拦截。只对"内建 + 已启用内容包"
    #目录执行代码——IMPORTED_SKILLS_DIR（导入 skill）永远排除，其代码永不执行（见 skills.py
    #collect_skill_tools 文档）。
    from utils.paths import IMPORTED_SKILLS_DIR

    from engine.setup_chat.skills import setup_chat_skill_dirs

    skill_tools: list = []
    taken = {getattr(t, "name", "") for t in builtin_tools}
    for skills_dir in setup_chat_skill_dirs():
        if skills_dir == IMPORTED_SKILLS_DIR:
            continue
        found = collect_skill_tools(skills_dir, existing_tool_names=taken)
        skill_tools.extend(found)
        taken |= {getattr(t, "name", "") for t in found}
    tool_node = TransactionalToolNode(
        [*builtin_tools, *skill_tools],
        handle_tool_errors=clean_tool_error,
    )
    all_tools = [*builtin_tools, *skill_tools]

    from engine.setup_chat import tool_router

    #build_tool_vectors() loads the embedding model (network round-trip to HF Hub even
    #when the model is already cached locally) -- runs during the fire-and-forget startup
    #warm-up task (register_startup_warmup), so calling it inline here blocks the single
    #asyncio event loop and stalls /api/health for as long as the HF Hub check takes.
    tool_vectors = await asyncio.to_thread(tool_router.build_tool_vectors, all_tools)

    global _ALL_TOOLS, _TOOL_VECTORS
    _ALL_TOOLS = all_tools
    _TOOL_VECTORS = tool_vectors

    async def _select_model(state: dict, runtime) -> object:
        routed_names = set(state.get("routed_tool_names") or [])
        return _bind_chat_model(llm, all_tools, routed_names)

    return create_react_agent(
        _select_model,
        tools=tool_node,
        prompt=compose_system_prompt(),
        checkpointer=checkpointer,
        pre_model_hook=pre_hook,
        post_model_hook=post_hook,
    )


def split_turn_answer_and_thinking(
    msgs: list, last_human: int, persist_dir: str,
) -> tuple[str, str]:
    """
Get the final answer and fold thinking from the messages in this round (after last_human).

    thinking = all ai messages with tool_calls in this round are sanitized and the text is spliced in order \n\n;
    answer = sanitized text of the last ai message without tool_calls. If empty, an empty string is returned."""

    from engine.setup_chat.memory import sanitize_assistant_for_display

    def _clean(c: object) -> str:
        if not isinstance(c, str) or not c.strip():
            return ""
        return sanitize_assistant_for_display(c, persist_dir).strip()

    thinking_parts: list[str] = []
    answer = ""
    for m in msgs[last_human + 1:]:
        if getattr(m, "type", "") != "ai":
            continue
        if getattr(m, "tool_calls", None):
            narration = _clean(getattr(m, "content", ""))
            if narration:
                thinking_parts.append(narration)
            continue
        cleaned = _clean(getattr(m, "content", ""))
        if cleaned:
            answer = cleaned
    return answer, "\n\n".join(thinking_parts)


_RESUME_NOTICE = "检测到上一轮工具调用被中断，正在自动续跑…"
_RESUME_OK_NOTICE = "已自动补跑完成上轮中断的操作。"
_RESUME_FAIL_NOTICE = "上轮工具调用中断且自动重试失败，操作未生效——请稍后重发这一步。"


async def _drive_stream(
    agent,
    inp: dict | None,
    config: dict,
    emit: Callable[[dict], Awaitable[None]],
    persist_dir: str,
    accountant,
) -> None:
    """Drive one graph run (fresh input or None to resume from checkpoint) and
    forward token/tool events. Raises on graph error -- caller owns recovery."""
    from engine.setup_chat import tool_trace
    from engine.setup_chat.memory import safe_stream_emit_len, sanitize_assistant_for_display
    from engine.setup_chat.stream_guard import should_forward_setup_chat_stream
    from engine.setup_chat.tool_progress import emit_scope

    tool_depth = 0
    stream_buf = ""
    emitted_len = 0
    pending_call_seq: dict[str, int] = {}  # run_id (or name fallback) -> tool_trace seq

    if inp is None:
        # After RESUME repair the thread may sit at END; nudge from tools so agent re-plans (spec §5.2).
        try:
            await agent.aupdate_state(config, {}, as_node="tools")
        except Exception:  # noqa: BLE001 — degrade if graph state does not need nudging
            pass

    async def _emit_token(delta: str) -> None:
        nonlocal stream_buf, emitted_len
        stream_buf += delta
        cleaned = sanitize_assistant_for_display(stream_buf, persist_dir)
        safe_len = safe_stream_emit_len(cleaned)
        if safe_len > emitted_len:
            await emit({"type": "setup_chat_token", "delta": cleaned[emitted_len:safe_len]})
            emitted_len = safe_len

    async with emit_scope(emit):
        async for ev in agent.astream_events(inp, version="v2", config=config):
            kind = ev.get("event")
            if kind == "on_tool_start":
                tool_depth += 1
                name = ev.get("name", "")
                key = ev.get("run_id") or name
                pending_call_seq[key] = tool_trace.next_call(name, ev.get("data", {}).get("input"))
                await emit({"type": "setup_chat_tool", "name": name, "phase": "start"})
                if name == "present_choices":
                    from engine.setup_chat.mode import is_auto_mode
                    if not is_auto_mode():
                        choice_inp = ev.get("data", {}).get("input") or {}
                        q = choice_inp.get("question")
                        opts = choice_inp.get("options")
                        if isinstance(q, str) and isinstance(opts, list) and all(isinstance(o, str) for o in opts):
                            await emit({"type": "setup_chat_choice", "question": q, "options": opts})
            elif kind in ("on_tool_end", "on_tool_error"):
                name = ev.get("name", "")
                data = ev.get("data", {})
                key = ev.get("run_id") or name
                seq = pending_call_seq.pop(key, 0)
                if kind == "on_tool_end":
                    tool_trace.log_call_ok(seq, name, _tool_output_text(data.get("output")))
                else:
                    tool_trace.log_call_error(seq, name, data.get("error"))
                await emit({"type": "setup_chat_tool", "name": name, "phase": "end"})
                tool_depth = max(0, tool_depth - 1)
            elif kind == "on_chat_model_stream" and should_forward_setup_chat_stream(tool_depth=tool_depth):
                chunk = ev.get("data", {}).get("chunk")
                delta = getattr(chunk, "content", "") if chunk is not None else ""
                if delta:
                    await _emit_token(delta)
            elif kind == "on_chat_model_end":
                from domain.token_usage import extract_usage

                output = ev.get("data", {}).get("output")
                tin, tout, tcached = extract_usage(output)
                await accountant.record(tin, tout, tcached)


async def _emit_final(
    agent,
    config: dict,
    persist_dir: str,
    emit: Callable[[dict], Awaitable[None]],
) -> None:
    try:
        state = await agent.aget_state(config)
        msgs = (state.values or {}).get("messages", []) if state else []
        last_human = next(
            (i for i in range(len(msgs) - 1, -1, -1) if getattr(msgs[i], "type", "") == "human"),
            -1,
        )
        answer, thinking = split_turn_answer_and_thinking(msgs, last_human, persist_dir)
        if answer:
            await emit({"type": "setup_chat_final", "content": answer, "thinking": thinking})
    except Exception:  # noqa: BLE001
        pass
    await emit({"type": "setup_chat_done"})


async def _heal_and_maybe_resume(
    agent,
    config: dict,
    persist_dir: str,
    emit: Callable[[dict], Awaitable[None]],
    accountant,
    *,
    depth: int = 0,
) -> bool:
    """Turn-end self-heal: dangling call -> restore snapshot + auto-resume once
    (D5/D6/D7). depth>0 means we are healing the resume run itself -> only PAIR
    + persistent alert, never a second resume. Returns True if auto-resume ran."""
    from engine.setup_chat.author_guard import ALL_CHAPTERS, stop_author_if_affected
    from engine.setup_chat.memory import RepairMode, ensure_checkpoint_messages_valid
    from engine.setup_chat.turn_snapshot import (
        bump_resume_attempts,
        restore_if_matches,
        resume_attempts,
    )

    resumed = False
    try:
        if depth > 0 or resume_attempts() >= 1:
            report = await ensure_checkpoint_messages_valid(
                agent, config, persist_dir, mode=RepairMode.PAIR)
            if report.changed and report.dangling_ids:
                await stop_author_if_affected(*ALL_CHAPTERS, "设定回滚，主笔进度已重置")
                restore_if_matches(report.dangling_ids)
                await emit({"type": "setup_chat_notice", "content": _RESUME_FAIL_NOTICE, "persist": True})
            return resumed
        report = await ensure_checkpoint_messages_valid(
            agent, config, persist_dir, mode=RepairMode.RESUME)
        if not (report.changed and report.dangling_ids):
            return resumed
        await stop_author_if_affected(*ALL_CHAPTERS, "设定回滚，主笔进度已重置")
        restore_if_matches(report.dangling_ids)
        bump_resume_attempts()
        await emit({"type": "setup_chat_notice", "content": _RESUME_NOTICE, "persist": False})
        try:
            await _drive_stream(agent, None, config, emit, persist_dir, accountant)
            await emit({"type": "setup_chat_notice", "content": _RESUME_OK_NOTICE, "persist": True})
            resumed = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("[setup-chat] auto-resume failed: {}", exc)
            await _heal_and_maybe_resume(agent, config, persist_dir, emit, accountant, depth=depth + 1)
    except Exception:  # noqa: BLE001
        logger.exception("setup-chat 轮末自愈失败")
    return resumed


async def run_turn(
    agent,
    novel_id: str,
    text: str,
    emit: Callable[[dict], Awaitable[None]],
    accountant,
    *,
    retry: bool = False,
) -> None:
    """Run a round of dialogue: stream token/tool events; self-heal + auto-resume at end.

    retry=True reuses the checkpoint as-is (caller must have truncated partial assistant
    messages and left the user HumanMessage in place) instead of appending another one."""
    from utils.paths import setup_chat_dir

    from engine.setup_chat import tool_trace
    from engine.setup_chat.hooks import SETUP_CHAT_RECURSION_LIMIT
    from engine.setup_chat.memory import RepairMode, ensure_checkpoint_messages_valid
    from engine.setup_chat.turn_snapshot import restore_if_matches

    tool_trace.start_turn(novel_id, text)
    try:
        from engine.setup_chat.mode import is_auto_mode

        persist_dir = setup_chat_dir()
        recursion_limit = 256 if is_auto_mode() else SETUP_CHAT_RECURSION_LIMIT
        config = {
            "configurable": {"thread_id": novel_id},
            "recursion_limit": recursion_limit,
        }
        report = await ensure_checkpoint_messages_valid(agent, config, persist_dir, mode=RepairMode.PAIR)
        if report.changed and report.dangling_ids:
            from engine.setup_chat.author_guard import ALL_CHAPTERS, stop_author_if_affected
            await stop_author_if_affected(*ALL_CHAPTERS, "设定回滚，主笔进度已重置")
            restore_if_matches(report.dangling_ids)
            await emit({
                "type": "setup_chat_notice",
                "content": "上一轮有工具调用被中断未执行（已回滚），模型已知情，可让它继续。",
                "persist": True,
            })
        inp = None if retry else {"messages": [{"role": "user", "content": text}]}
        try:
            await _drive_stream(agent, inp, config, emit, persist_dir, accountant)
        except Exception as exc:
            err = str(exc)
            if "recursion limit" in err.lower() or "GraphRecursionError" in type(exc).__name__:
                err = "本轮工具调用次数过多，已自动停止。请拆成更小步骤重试"
            await emit({"type": "setup_chat_error", "error": err})
        await _heal_and_maybe_resume(agent, config, persist_dir, emit, accountant)
        await _emit_final(agent, config, persist_dir, emit)
    finally:
        tool_trace.end_turn()


async def run_recovery(
    agent,
    novel_id: str,
    emit: Callable[[dict], Awaitable[None]],
    accountant,
) -> None:
    """Session-load recovery (D9): heal + auto-resume without competing input."""
    from utils.paths import setup_chat_dir

    from engine.setup_chat import tool_trace
    from engine.setup_chat.hooks import SETUP_CHAT_RECURSION_LIMIT

    config = {"configurable": {"thread_id": novel_id}, "recursion_limit": SETUP_CHAT_RECURSION_LIMIT}
    persist_dir = setup_chat_dir()
    tool_trace.start_turn(novel_id, "(会话恢复)")
    try:
        if await _heal_and_maybe_resume(agent, config, persist_dir, emit, accountant):
            await _emit_final(agent, config, persist_dir, emit)
    finally:
        tool_trace.end_turn()
