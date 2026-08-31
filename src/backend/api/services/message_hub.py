"""MessageHub: Domain service for background tasks (File/Settings/Main) and WebSocket broadcast."""
from __future__ import annotations

import asyncio
import os
import shutil
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any, cast

from engine.setup_chat.agent import run_turn
from engine.story_sandbox.graph import (
    restore_state as restore_story_sandbox_state,
)
from engine.story_sandbox.graph import (
    run_turn as run_story_sandbox_turn,
)
from engine.story_sandbox.graph import (
    snapshot_state as snapshot_story_sandbox_state,
)
from engine.story_sandbox.state import LEGACY_BRANCH_ID
from loguru import logger
from utils.paths import (
    active_novel_id,
    author_loop_graph_checkpoint_path,
    author_loop_journal_path,
    setup_chat_dir,
    setup_chat_session_dir,
    use_novel,
)

from api.services.gateway_port import make_gateway
from api.services.setup_chat_turn_queue import (
    SETUP_CHAT_TURN_QUEUE,
    SetupChatTurnKind,
)

if TYPE_CHECKING:
    from engine.execution.style_guard import WordDensityGuard, WordDensityGuardSnapshot
    from engine.story_sandbox.graph import WriteTurn
    from llm.prompt_logger import PromptLogger

    from api.services.setup_chat_review_feedback import ReviewFeedbackEntry, ReviewKey
    from api.services.token_accountant import TokenAccountant

_REWRITE_SYS = (
    "你是文字润色助手。只重写下面给定的这一句话，避开指定的禁用句式，"
    "不改变原意与语气，只输出重写后的这一句，不加引号、不加解释。\n\n"
    "重写指导原则：\n"
    "1. 避免使用陈词滥调和俗套的氛围词。\n"
    "2. 优先通过【具体的物理动作、细节描写或生理反应】来表现人物状态，而非使用抽象的修饰词（例如：不要直接用“嗓音低沉/沙哑”，尝试描述声音的具体质感或直接描写人物动作细节）。\n"
    "3. 保持文字精炼，杜绝无意义的修饰语堆砌。"
)

_SHORT_FIELD_REWRITE_SYS = (
    "你是文字润色助手。下面这句是系统内部使用的一段简短描述片段（建议/状态/摘要类文本，"
    "不是正文）——只重写这一句，避开指定的禁用句式，保持简短概括、不要写成叙事文风，"
    "不改变原意，只输出重写后的这一句，不加引号、不加解释。"
)


def _rewrite_sys(style: str) -> str:
    """Fold the active prose-style card into the guard's rewrite system prompt so a
    guard-triggered local rewrite doesn't drift off the novel's voice."""
    if not style:
        return _REWRITE_SYS
    return f"{_REWRITE_SYS}\n\n本书文风要求（重写后的句子必须遵守）：\n{style}"


def _model_name(llm, fallback: str) -> str:
    """Model name actually driving `llm`'s requests -- falls back to `fallback`
    (the outer cloud model name) when `llm` doesn't expose one. Needed because a
    node can now bind to a different client (e.g. local LMStudio) than the
    enclosing function's outer `llm`, so token accounting/prompt logs must key
    off the node's real client, not the function-wide default."""
    return str(getattr(llm, "model", "") or getattr(llm, "model_name", "") or fallback)


_SANDBOX_TERMINAL_EVENT_TYPES = frozenset({
    "story_sandbox_done", "story_sandbox_error",
    "story_sandbox_turn_cancelled", "story_sandbox_rewrite_done",
    "story_sandbox_suggestions_regenerated", "story_sandbox_suggestions_regenerate_error",
    "story_sandbox_selection_rewrite_done", "story_sandbox_selection_rewrite_error",
    "story_sandbox_profile_mutation_rewrite_done", "story_sandbox_profile_mutation_rewrite_error",
})

_SETUP_CHAT_TERMINAL_EVENT_TYPES = frozenset({
    "setup_chat_final", "setup_chat_done",
    "setup_chat_error", "setup_chat_turn_cancelled",
})


def _scan_resumable() -> list[int]:
    """The whole chapter map checkpoint sqlite already has the progress chapter number (thread_id=ch{N} reverse solution)."""
    from engine.author_loop.dialogue_mode.chapter_checkpoint import scan_resumable_chapters

    return scan_resumable_chapters(author_loop_graph_checkpoint_path())


async def _rename_to_trash_with_retry(
    path: str, *, attempts: int = 10, delay: float = 0.1,
) -> str | None:
    """Rename path to a one-shot trash path -- O(1) regardless of directory size. Returns the
    trash path; returns None when path does not exist (nothing to clear). Retry semantics match
    the old _rmtree_with_retry: right after closing an aiosqlite connection on Windows, OS-level
    file-handle release can lag a beat, so briefly retry instead of failing immediately."""
    if not os.path.exists(path):
        return None
    trash_path = f"{path}.trash-{uuid.uuid4().hex}"
    last_exc: OSError | None = None
    for attempt in range(attempts):
        try:
            os.rename(path, trash_path)
            return trash_path
        except OSError as exc:
            last_exc = exc
            if attempt < attempts - 1:
                await asyncio.sleep(delay)
    raise RuntimeError(f"清空失败：{path} 部分文件被占用，请稍后重试") from last_exc


async def _background_rmtree(path: str) -> None:
    """Trash path already renamed away -- nothing still references it. Log-only on failure."""
    try:
        await asyncio.to_thread(shutil.rmtree, path)
    except OSError:
        logger.exception("[setup_chat] background cleanup failed to remove {}", path)


class MessageHub:
    """
Central message hub: manages background tasks + multiple WebSocket clients, and maintains event replay buffers."""

    def __init__(self) -> None:
        self._gateway = make_gateway()
        self._author_tasks: dict[str, asyncio.Task] = {}  # type: ignore[type-arg]
        self._author_chapters: dict[str, int] = {}
        # shape: {"novel_id": str, "chapter": int, "events": list[dict]}; key absent = no
        # author_loop task currently running for that novel. Only holds events NOT already
        # journaled (token/progress/style_rewrite/recall/event_log) -- cleared whenever a
        # _MILESTONE-type event fires, since the journal already has that one. See
        # docs/superpowers/specs/2026-08-03-author-loop-live-stream-resync-design.md.
        self._author_loop_live: dict[str, dict] = {}
        self._setup_chat_tasks: dict[str, asyncio.Task] = {}  # type: ignore[type-arg]
        self._setup_chat_agents: dict[str, object] = {}  # value type: engine.setup_chat.agent's built agent
        self._setup_chat_agents_building: dict[str, asyncio.Task] = {}  # type: ignore[type-arg]
        self._setup_chat_pre_state: object | None = None  # LangGraph StateSnapshot
        self._setup_chat_pre_turn_user_msg_id: str | None = None
        self._setup_chat_pre_turn_choice_msg_ids: list[str] = []
        # shape: {"novel_id": str, "instruction": str, "events": list[dict]}; None when no
        # round is currently in flight. See spec
        # docs/superpowers/specs/2026-07-22-setup-chat-live-stream-resync-design.md.
        self._setup_chat_live: dict[str, dict] = {}
        # shape: {"done": int, "total": int}; None when no image attachments are part of
        # the in-flight turn. Aggregate image-recognition progress, tracked at image-count
        # granularity across however many read_attachment_image calls the agent makes --
        # distinct from the text-chunk-granularity novel_import_* events read_attachment
        # broadcasts, which would otherwise be the only signal and flash "1/1" once per
        # image (a single image's vision description is almost always one text chunk).
        self._setup_chat_image_progress: dict[str, dict] = {}
        # shape: {"index": int, "total": int}; tracks read_attachment text-chunk distillation
        # progress per novel while a turn is in flight (mirrors image progress above).
        self._setup_chat_text_progress: dict[str, dict] = {}
        self._story_sandbox_tasks: dict[str, asyncio.Task] = {}  # type: ignore[type-arg]
        self._story_sandbox_pre_states: dict[str, dict] = {}
        self._story_sandbox_derive_retry_cache: dict[tuple[str, int, str], dict] = {}
        self._story_sandbox_word_guards: dict[tuple[str, int, str], WordDensityGuard] = {}
        self._story_sandbox_last_round_word_guard_snapshot: dict[
            tuple[str, int, str], WordDensityGuardSnapshot
        ] = {}
        self._story_sandbox_pre_word_guard_snapshots: dict[str, WordDensityGuardSnapshot] = {}
        # shape: {"novel_id": str, "chapter": int, "mode": SandboxLiveMode, "instruction": str,
        # "events": list[dict]}; None when no round is currently in flight. See spec
        # docs/superpowers/specs/2026-07-19-sandbox-live-turn-recovery-design.md.
        self._story_sandbox_live: dict[str, dict] = {}
        self._background_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]
        self._recovery_checked: set[str] = set()
        from engine.setup_chat.author_guard import set_author_guard
        set_author_guard(self._on_setup_write_affects_author)

    def is_pipeline_busy(self, novel_id: str | None = None) -> bool:
        """Is there any background author-loop task running for this novel.
        novel_id=None checks the currently active novel."""
        nid = novel_id or active_novel_id()
        t = self._author_tasks.get(nid)
        return bool(t and not t.done())

    async def broadcast(self, event: dict) -> None:
        """Delegate Gateway broadcast (retain this method name, all internal self.broadcast
        calls do not need to be changed). Tags every event with novel_id -- resolves to
        whichever novel the calling task is pinned to via use_novel() (Plan 1), which is
        correct even for a background task on a novel the user has since switched away from;
        falls back to active_novel_id() for call sites not wrapped in use_novel() (there
        should be none left after Plan 1/2, but this keeps the method itself safe either way)."""
        event.setdefault("novel_id", active_novel_id())
        await self._gateway.broadcast(event)

    async def add_client(self, ws: object, since_seq: int = 0) -> None:
        await self._gateway.add_client(ws, since_seq)

    def remove_client(self, ws: object) -> None:
        self._gateway.remove_client(ws)

    def journal_events(self, chapter: int, novel_id: str | None = None) -> list[dict]:
        """
Read the chapter's journal event on demand (for front-end playback when opening/restoring a chapter). Do not touch the global buffer——
        The global buffer is an active stream shared across clients. Injecting history will cause pollution, and the coexistence of multiple chapters will lead to cascading, so on-demand REST is used.

        journal is the interrupted history (with author_loop_start, no final state), direct replay will cause the front end to derive
        The illusion of "running". Add an author_loop_stopped mark at the end - the front end falls to idle accordingly (retaining written messages,
        Wait for the response prompt), and display "Continue/Restart" in conjunction with the resumable status. Empty journal → [].

        When this exact (novel_id, chapter) is actively running right now, skip the synthetic
        stopped marker and append the live tail instead (`_author_loop_live`) -- the front end
        replays it through the same wsEventReceived reducer path as real-time WS traffic and
        lands on status='running' with the current beat's streamed text intact, instead of being
        told (wrongly) that the run has stopped."""
        from engine.author_loop.journal import load_events

        nid = novel_id or active_novel_id()
        with use_novel(nid):
            events = load_events(author_loop_journal_path(chapter))
        live = self._author_loop_live.get(nid)
        is_live = live is not None and live["chapter"] == chapter
        if not events:
            if is_live and live is not None:
                return list(live["events"])
            return []
        if is_live and live is not None:
            return [*events, *live["events"]]
        return [*events, {"type": "author_loop_stopped", "chapter": chapter}]

    def resumable_chapters(self, novel_id: str | None = None) -> list[int]:
        """Chapter number with checkpoint (recoverable)."""
        nid = novel_id or active_novel_id()
        with use_novel(nid):
            return _scan_resumable()

    def running_author_loop_chapter(self, novel_id: str | None = None) -> int | None:
        """Which chapter (if any) this novel's author_loop task is running right now.
        `_author_chapters`'s per-novel entry is set right before the task is created and
        popped in its `finally` block -- identical lifecycle to `_author_tasks`, so presence
        alone means the task is alive."""
        nid = novel_id or active_novel_id()
        return self._author_chapters.get(nid)

    async def start_author_loop(
        self, chapter: int, resume: bool = False,
        prose_style: str = "",
    ) -> None:
        """
Start the main writer's paragraph-by-paragraph writing cycle: progress/paragraph-by-paragraph output go ws broadcast. Rejected while running."""
        novel_id = active_novel_id()
        if self.is_pipeline_busy():
            raise RuntimeError("有任务运行中，无法启动主笔写作")
        #Start the front door: World view/Character file/If the skeleton of this chapter is missing, collect them all at once and report an error. Don't run in to have scattered failures.
        #Resume is a continuation of a verified run (and there is a skeleton guard in the inner layer) without re-verification to avoid historical data drift and getting stuck in the continuation.
        if not resume:
            from engine.author_loop.preflight import collect_author_loop_blockers

            blockers = collect_author_loop_blockers(chapter)
            if blockers:
                raise RuntimeError(
                    "无法启动主笔写作，请先补全以下设定：\n"
                    + "\n".join(f"• {b}" for b in blockers)
                )
        from engine.author_loop.journal import append_event

        #Final state flag: the loop must end with done/error; record whether it has been sent, so that _run finally can determine whether to reissue it.
        emitted = {"terminal": False}
        jpath = author_loop_journal_path(chapter)
        _MILESTONE = {
            "author_loop_start",
            "author_loop_segment", "author_loop_state", "author_loop_summary",
            "author_loop_chapter_progress",
            "author_loop_done", "author_loop_error", "author_loop_stopped",
        }

        async def _emit(ev: dict) -> None:
            if ev.get("type") in ("author_loop_done", "author_loop_error"):
                emitted["terminal"] = True
            if ev.get("type") == "author_loop_done":
                #章节完成立即落盘成稿，不依赖任何前端会话还连着——之前成稿保存完全靠前端
                #author_loop_done 监听器（listeners.ts）触发一次 REST 调用，且那个监听器只在
                #发起这次运行的同一个浏览器会话（liveRun=true）里生效：中途刷新/关闭页面会让
                #liveRun 状态丢失，任务本身在服务端照常跑完，但没人会去调用保存，成稿就此漏写。
                from engine.author_loop.build import save_author_loop_chapter

                try:
                    save_author_loop_chapter(chapter)
                except ValueError as e:
                    logger.warning("[author-loop] 章节完成自动落盘成稿失败 chapter={}：{}", chapter, e)
            if ev.get("type") in _MILESTONE:
                #author_loop_segment only falls into the "final draft" state (draft final state), and the process state with draft=True does not fall into it.
                if not (ev.get("type") == "author_loop_segment" and ev.get("draft")):
                    append_event(jpath, ev)
            live = self._author_loop_live.get(novel_id)
            if live is not None:
                if ev.get("type") in _MILESTONE:
                    live["events"] = []
                else:
                    live["events"].append(ev)
            await self.broadcast(ev)

        async def _run() -> None:
            with use_novel(novel_id):
                cancelled = False
                prompt_logger = None
                try:
                    from domain.token_usage import extract_usage
                    from engine.author_loop.dialogue_mode.chapter import run_dialogue_chapter
                    from engine.execution.prose_style import build_active_prose_style_card
                    from engine.execution.style_guard import (
                        WordDensityGuard,
                        forbidden_words_text,
                        get_compiled_patterns,
                        guarded_stream,
                    )
                    from engine.modes.author_loop_skill_prefs import (
                        bind_node_llm,
                        load_dialogue_prefs,
                    )
                    from langchain_core.messages import HumanMessage, SystemMessage
                    from llm.factory import get_cloud_llm, get_style_guard_llm
                    from llm.prompt_logger import PromptLogger

                    from api.services.token_accountant import TokenAccountant

                    llm = get_cloud_llm()
                    model = str(
                        getattr(llm, "model", "") or getattr(llm, "model_name", "") or "cloud"
                    )
                    style_guard_llm = get_style_guard_llm()
                    style_guard_model = _model_name(style_guard_llm, model)
                    llm_params = load_dialogue_prefs().get("llm_params", {})
                    director_llm = bind_node_llm(llm, "director", llm_params)
                    director_model = _model_name(director_llm, model)
                    director_guard_disabled = bool(llm_params.get("director", {}).get("disable_style_guard"))
                    #prompt log: dialogue mode chases agent one by one and drops system/user/response to logs/engine_server.
                    #For scripts/prompt_parse.py to troubleshoot (the node is transparently transmitted through _log_step=beat_idx / _log_agent).
                    #The default falls back to tag/author, ensuring that any call has a record).
                    prompt_logger = PromptLogger(chapter)
                    word_guard = WordDensityGuard()
                    #token 计费:章级累计(override 语义,同章重跑清零重记),写入 token_ledger.json
                    #供 Token 统计页(aggregate_token_stats)消费——此前这里从未构造 accountant,
                    #tokens 全硬编码 0,主笔消耗在统计页永远看不到。
                    accountant = TokenAccountant(
                        novel_id=novel_id, subsystem="author_loop",
                        key=str(chapter), model=model,
                    )
                    accountant.begin()
                    #The writing style is unified using the per-novel writing style card (base+preset+custom addition), which is consistent with setup_chat;
                    #Explicit prose_style (card text) is only overridden. The director node no longer has a separate writing style.
                    style = prose_style or build_active_prose_style_card()

                    async def _call_llm(
                        system: str, user: str, *a, tag: str | None = None, **k,
                    ) -> tuple[str, int, int]:
                        #_log_step (beat_idx)/_log_agent is transparently transmitted by each node to determine the belonging group of prompt_parse.
                        step = int(k.get("_log_step", -1))
                        agent = str(k.get("_log_agent") or tag or "author")
                        active_llm = bind_node_llm(llm, agent, llm_params)
                        agent_model = _model_name(active_llm, model)
                        msgs = [SystemMessage(content=system), HumanMessage(content=user)]
                        t0 = time.monotonic()
                        #Tag marks "user-visible content" (narration/lines/synthesized text): streaming token broadcast, front-end real-time display,
                        #No longer looks stuck. Intermediate step (scheduling/guarding/deduction/summary) does not pass tag → go ainvoke silently.
                        if tag:
                            #role (role name) is delivered with the token event: when agent=character, the front-end live bubble is named accordingly.
                            role = k.get("role")
                            chunks: list[str] = []
                            #OpenAI-compatible streaming only carries usage on a final, empty-content
                            #chunk (stream_usage=True requests it) -- capture that chunk regardless of
                            #whether its (empty) content gets yielded as a visible piece below.
                            usage_chunk: dict = {}

                            async def _token_source() -> AsyncIterator[str]:
                                async for ch in active_llm.astream(msgs, stream_usage=True):
                                    if getattr(ch, "usage_metadata", None):
                                        usage_chunk["chunk"] = ch
                                    piece = ch.content if isinstance(ch.content, str) else str(ch.content)
                                    if piece:
                                        yield piece

                            async def _rewrite(context: str, offending: str, trigger: str) -> str:
                                #命中禁用句式后的局部重写：只喂上文尾巴 + 命中句，不带完整 beat 素材；
                                #system 拼上本书文风卡，避免重写把违规句换成另一种不合文风的句子。
                                await self.broadcast({
                                    "type": "author_loop_style_rewrite",
                                    "status": "start",
                                    "agent": agent,
                                    "role": k.get("role"),
                                })
                                rewrite_user = (
                                    f"上文（仅供承接语气，不要重复）：{context}\n\n"
                                    f"待重写句：{offending}\n\n"
                                    f"这句命中了应避免的词/句式：「{trigger}」——重写时必须换成完全不同的表达，"
                                    f"不能再出现这个词，也不能是雷同结构的变体。\n\n"
                                    f"另外，以下词汇全篇都应避免使用，重写时也不要换成它们中的任何一个："
                                    f"{forbidden_words_text()}"
                                )
                                rewrite_sys = _rewrite_sys(style)
                                t1 = time.monotonic()
                                resp = await style_guard_llm.ainvoke(
                                    [SystemMessage(content=rewrite_sys), HumanMessage(content=rewrite_user)]
                                )
                                rewritten = resp.content if isinstance(resp.content, str) else str(resp.content)
                                rtin, rtout, rtcached = extract_usage(resp)
                                prompt_logger.log_llm_call(
                                    step=step, agent=f"{agent}_guard_rewrite", model=style_guard_model,
                                    system=rewrite_sys, user=rewrite_user, response=rewritten,
                                    tokens_in=rtin, tokens_out=rtout, tokens_cached=rtcached,
                                    duration_s=time.monotonic() - t1,
                                )
                                await accountant.record(rtin, rtout, rtcached, model=style_guard_model)
                                await self.broadcast({
                                    "type": "author_loop_style_rewrite",
                                    "status": "end",
                                    "agent": agent,
                                    "role": k.get("role"),
                                })
                                return rewritten.strip()

                            def _on_exhausted(sentence: str) -> None:
                                prompt_logger.log_event(
                                    "style_guard_exhausted", step=step, agent=agent, sentence=sentence,
                                )

                            async for piece in guarded_stream(
                                _token_source(),
                                patterns=get_compiled_patterns(),
                                rewrite=_rewrite,
                                on_exhausted=_on_exhausted,
                                word_guard=word_guard,
                            ):
                                chunks.append(piece)
                                ev = {"type": "author_loop_token", "agent": tag, "delta": piece}
                                if role:
                                    ev["role"] = role
                                await self.broadcast(ev)
                            text = "".join(chunks)
                            tin, tout, tcached = extract_usage(usage_chunk.get("chunk"))
                        else:
                            resp = await active_llm.ainvoke(msgs)
                            text = resp.content if isinstance(resp.content, str) else str(resp.content)
                            tin, tout, tcached = extract_usage(resp)
                        prompt_logger.log_llm_call(
                            step=step, agent=agent, model=agent_model, system=system, user=user,
                            response=text, tokens_in=tin, tokens_out=tout, tokens_cached=tcached,
                            duration_s=time.monotonic() - t0,
                        )
                        await accountant.record(tin, tout, tcached, model=agent_model)
                        return text, tin, tout

                    self_hub = self
                    assert prompt_logger is not None  #此处 logger 必已构造(嵌套类作用域打断外层收窄)
                    plog = prompt_logger

                    class _HubAuthorTurns:
                        """主笔回合的 LLM 执行体:正文流式(带正则守卫+token 广播)。"""

                        async def prose_turn(self, messages, *, step: int) -> str:  # noqa: ANN001
                            chunks: list[str] = []
                            usage_chunk: dict = {}
                            t0 = time.monotonic()

                            async def _source() -> AsyncIterator[str]:
                                async for ch in director_llm.astream(messages, stream_usage=True):
                                    if getattr(ch, "usage_metadata", None):
                                        usage_chunk["chunk"] = ch
                                    piece = ch.content if isinstance(ch.content, str) else str(ch.content)
                                    if piece:
                                        yield piece

                            async def _rewrite(context: str, offending: str, trigger: str) -> str:
                                await self_hub.broadcast({
                                    "type": "author_loop_style_rewrite",
                                    "status": "start",
                                    "agent": "synthesis",
                                    "role": None,
                                })
                                rewrite_user = (
                                    f"上文（仅供承接语气，不要重复）：{context}\n\n"
                                    f"待重写句：{offending}\n\n"
                                    f"这句命中了应避免的词/句式：「{trigger}」——重写时必须换成完全不同的表达，"
                                    f"不能再出现这个词，也不能是雷同结构的变体。\n\n"
                                    f"另外，以下词汇全篇都应避免使用，重写时也不要换成它们中的任何一个："
                                    f"{forbidden_words_text()}"
                                )
                                resp = await style_guard_llm.ainvoke(
                                    [SystemMessage(content=_rewrite_sys(style)),
                                     HumanMessage(content=rewrite_user)]
                                )
                                rtin, rtout, rtcached = extract_usage(resp)
                                await accountant.record(rtin, rtout, rtcached, model=style_guard_model)
                                rewritten = (
                                    resp.content if isinstance(resp.content, str) else str(resp.content)
                                ).strip()
                                await self_hub.broadcast({
                                    "type": "author_loop_style_rewrite",
                                    "status": "end",
                                    "agent": "synthesis",
                                    "role": None,
                                })
                                return rewritten

                            def _on_exhausted(sentence: str) -> None:
                                plog.log_event(
                                    "style_guard_exhausted", step=step, agent="author",
                                    sentence=sentence,
                                )

                            token_stream = (
                                _source() if director_guard_disabled
                                else guarded_stream(
                                    _source(), patterns=get_compiled_patterns(),
                                    rewrite=_rewrite, on_exhausted=_on_exhausted,
                                    word_guard=word_guard,
                                )
                            )
                            async for piece in token_stream:
                                chunks.append(piece)
                                await self_hub.broadcast(
                                    {"type": "author_loop_token", "agent": "synthesis", "delta": piece})
                            text = "".join(chunks)
                            tin, tout, tcached = extract_usage(usage_chunk.get("chunk"))
                            plog.log_llm_call(
                                step=step, agent="author", model=director_model,
                                system=str(messages[0].content), user=str(messages[-1].content),
                                response=text, tokens_in=tin, tokens_out=tout, tokens_cached=tcached,
                                duration_s=time.monotonic() - t0)
                            await accountant.record(tin, tout, tcached, model=director_model)
                            return text

                    await _emit({
                        "type": "author_loop_start",
                        "chapter": chapter,
                        "resume": resume,
                        "mode": "dialogue",
                    })
                    await run_dialogue_chapter(
                        chapter,
                        _call_llm,
                        style,
                        emit=_emit,
                        resume=resume,
                        author_turns=_HubAuthorTurns(),
                    )
                    if not emitted["terminal"]:
                        await _emit({"type": "author_loop_done", "chapter": chapter, "mode": "dialogue"})
                except asyncio.CancelledError:
                    #Active stop: author_loop_stopped is broadcast by stop_author_loop, and error is not reissued.
                    cancelled = True
                    raise
                except Exception:  #noqa: BLE001 — The error has been emitted, swallowed to avoid task noise
                    pass
                finally:
                    #Final state summary: any non-cancellation exit without done/error (including unexpected paths other than await never returning),
                    #Reissue author_loop_error to ensure that the front end will always jump to running and will not freeze silently.
                    if not cancelled and not emitted["terminal"]:
                        await self.broadcast(
                            {"type": "author_loop_error", "error": "主笔异常退出（未发终态事件）"}
                        )
                    #Explicitly remove the loguru sink of prompt_logger to prevent the resident process from starting the sink repeatedly.
                    if prompt_logger is not None:
                        prompt_logger.close()
                    self._author_tasks.pop(novel_id, None)
                    self._author_chapters.pop(novel_id, None)
                    self._author_loop_live.pop(novel_id, None)

        self._author_chapters[novel_id] = chapter
        self._author_loop_live[novel_id] = {"novel_id": novel_id, "chapter": chapter, "events": []}
        self._author_tasks[novel_id] = asyncio.create_task(_run())

    async def stop_author_loop(self) -> None:
        """Stop writing in the middle: cancel the background task (CancelledError injected at the current
        await point for a smooth exit), broadcast author_loop_stopped. No running task → no-op."""
        novel_id = active_novel_id()
        t = self._author_tasks.get(novel_id)
        if t is None:
            return
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
        self._author_tasks.pop(novel_id, None)
        self._author_chapters.pop(novel_id, None)
        await self.broadcast({"type": "author_loop_stopped", "novel_id": novel_id})

    async def _on_setup_write_affects_author(self, lo: int, hi: int, reason: str) -> None:
        """author_guard callback (spec D13/D14): stop + reset the running chapter
        when a setup write invalidates it. No-op when idle or out of range."""
        novel_id = active_novel_id()
        ch = self._author_chapters.get(novel_id)
        t = self._author_tasks.get(novel_id)
        running = bool(t and not t.done())
        if not running or ch is None or not (lo <= ch <= hi):
            return
        await self.stop_and_reset_author_chapter(reason)

    async def stop_and_reset_author_chapter(self, reason: str) -> None:
        novel_id = active_novel_id()
        ch = self._author_chapters.get(novel_id)
        if ch is None:
            return
        await self.stop_author_loop()
        await self._reset_author_chapter_state(ch)
        await self.broadcast({
            "type": "author_loop_stopped", "chapter": ch, "reason": reason, "novel_id": novel_id,
        })

    async def _reset_author_chapter_state(self, chapter: int) -> None:
        """Delete the chapter's graph checkpoint thread + journal (spec D14)."""
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        cp = author_loop_graph_checkpoint_path()
        if os.path.exists(cp):
            conn = await aiosqlite.connect(cp)
            try:
                saver = AsyncSqliteSaver(conn)
                await saver.adelete_thread(f"ch{chapter}")
            finally:
                await conn.close()
        try:
            os.remove(author_loop_journal_path(chapter))
        except FileNotFoundError:
            pass

        from media.scene.author_store import clear_author_stage_scene_images
        clear_author_stage_scene_images(chapter)

    def is_setup_chat_busy(self, novel_id: str | None = None) -> bool:
        nid = novel_id or active_novel_id()
        t = self._setup_chat_tasks.get(nid)
        return bool(t and not t.done())

    def is_image_recognition_configured(self) -> bool:
        from engine.modes.author_loop_skill_prefs import is_image_recognition_configured

        return is_image_recognition_configured()

    def novel_import_progress_snapshot(self, novel_id: str | None = None) -> dict | None:
        """Running attachment-import progress for one novel -- used by GET /api/setup-chat/status
        so a frontend resync after novel switch can restore the progress bar without relying on
        WS events the user may have missed while viewing another novel."""
        nid = novel_id or active_novel_id()
        img = self._setup_chat_image_progress.get(nid)
        if img is not None:
            return {
                "status": "running",
                "kind": "image",
                "index": img["done"],
                "total": img["total"],
            }
        txt = self._setup_chat_text_progress.get(nid)
        if txt is not None:
            return {
                "status": "running",
                "kind": "text",
                "index": txt["index"],
                "total": txt["total"],
            }
        return None

    async def _ensure_setup_chat_agent(self, novel_id: str):
        """Lazy-build this novel's setup-chat agent instance. Guarded against concurrent
        double-build for the SAME novel_id (a startup warm-up task racing a user's first real
        request) via the in-flight-build Task stashed per novel_id -- different novel_ids
        build fully independently, no cross-novel discard (Plan 1 predecessor had a
        single-slot singleton that discarded an in-flight build if the *global* active novel
        changed mid-build; that concept no longer applies once builds are keyed by novel_id)."""
        if novel_id in self._setup_chat_agents:
            return self._setup_chat_agents[novel_id]
        building = self._setup_chat_agents_building.get(novel_id)
        if building is None:
            from engine.setup_chat.agent import build_agent

            async def _build() -> object:
                with use_novel(novel_id):
                    return await build_agent()

            building = asyncio.create_task(_build())
            self._setup_chat_agents_building[novel_id] = building
        agent = await building
        self._setup_chat_agents_building.pop(novel_id, None)
        self._setup_chat_agents[novel_id] = agent
        return agent

    async def _ensure_story_sandbox_checkpointer(self) -> None:
        """Thin wrapper so SCHEDULER.schedule_once (startup warm-up) has a hub-method-shaped
        callable -- the scheduler only ever registers hub methods, mirroring the existing
        on_stop hooks. Warms up whichever novel is active at process startup; other novels'
        checkpointers are lazily opened on first real use."""
        from engine.story_sandbox.graph import ensure_checkpointer

        await ensure_checkpointer(active_novel_id())

    async def reset_setup_chat(self, novel_id: str | None = None) -> None:
        """Discard this novel's setup-chat agent instance. novel_id=None resets the currently
        active novel's instance (existing callers -- SCHEDULER's on_stop hook, delete-novel
        cleanup -- keep working unchanged). Does not interrupt an in-progress round for that
        novel; if one is running, only the reference is cleared, not the connection.

        Only clears the global AUTO flag when the novel being reset is the currently-focused
        one. Without this guard, novel_memory_scavenger's background eviction of an unrelated
        idle novel (deliberately never the focused one -- see its `nid != focus` filter) would
        silently flip AUTO off for whatever novel the user is actively working on, with no
        frontend signal (found live, 2026-08-21)."""
        from context.content_packs import reload_content_packs
        from engine.setup_chat.mode import is_auto_mode, set_auto_mode

        nid = novel_id or active_novel_id()
        if nid == active_novel_id() and is_auto_mode():
            set_auto_mode(False)  # auto mode is a per-session convenience, not a per-novel setting
            await self.broadcast({"type": "setup_chat_mode_changed", "auto": False})
        reload_content_packs()
        agent = self._setup_chat_agents.pop(nid, None)
        t = self._setup_chat_tasks.get(nid)
        busy = bool(t and not t.done())
        if agent is not None and not busy:
            try:
                await cast(Any, agent).checkpointer.conn.close()
            except Exception:  # noqa: BLE001 - Connection failure is not fatal, just discard it
                pass
        SETUP_CHAT_TURN_QUEUE.clear(nid)
        from api.services.setup_chat_review_feedback import REVIEW_FEEDBACK

        REVIEW_FEEDBACK.clear_all(nid)

    async def reset_all_setup_chat(self) -> None:
        """Close every novel's setup-chat agent connection -- used at process shutdown so no
        novel's sqlite checkpointer connection is left dangling just because it wasn't the
        currently-active one."""
        for nid in list(self._setup_chat_agents):
            await self.reset_setup_chat(nid)

    async def clear_setup_chat_conversation(self) -> None:
        """清空当前小说 setup-chat 的全部状态：短期记忆(checkpoint)+长期记忆(memory)+
        任务进度(construction_plan)+前端消息回放表(session)。忙碌中拒绝——接下来要删
        checkpoint 文件，必须先保证没有活跃连接在写它（Windows 下残留句柄会导致删除失败）。"""
        if self.is_setup_chat_busy():
            raise RuntimeError("对话进行中，无法清空")
        await self.reset_setup_chat()  # 丢弃单例 + 关闭连接（此时保证非 busy，一定会关成功）

        from api.services.token_accountant import TokenAccountant

        TokenAccountant(
            novel_id=active_novel_id(), subsystem="setup", key="chat", model="",
        ).begin()
        trash_path = await _rename_to_trash_with_retry(setup_chat_dir())
        if trash_path is not None:
            task = asyncio.create_task(_background_rmtree(trash_path))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        session_dir = setup_chat_session_dir()
        session_msgs = os.path.join(session_dir, "messages.json")
        try:
            os.remove(session_msgs)
        except FileNotFoundError:
            pass

        from engine.setup_chat.session_record import clear_messages

        clear_messages(session_dir)

        from engine.setup_chat.memory import save_memory

        # Long-term memory (decision distillation) lives in the per-novel chronos.sqlite3
        # documents table, not under setup_chat_dir() -- the trash-rename above never
        # touches it, so it must be wiped separately or old decisions resurface in the
        # next conversation's context.
        save_memory(setup_chat_dir(), {"decisions": []})

    async def wait_for_pending_background_tasks(self) -> None:
        """Test-only: wait for all dispatched background cleanup tasks (currently just
        setup-chat directory deletion) to finish."""
        pending = list(self._background_tasks)
        if pending:
            await asyncio.gather(*pending)

    def _make_setup_chat_emit(self, novel_id: str | None = None):
        from engine.setup_chat.session_record import append_assistant, append_choice, append_system

        session_dir = setup_chat_session_dir(novel_id)

        async def _emit(ev: dict) -> None:
            if ev.get("type") == "setup_chat_final":
                content = ev.get("content", "")
                if isinstance(content, str) and content.strip():
                    thinking = ev.get("thinking", "")
                    append_assistant(
                        session_dir, content,
                        thinking=thinking if isinstance(thinking, str) else "",
                    )
            elif ev.get("type") == "setup_chat_notice" and ev.get("persist"):
                content = ev.get("content", "")
                if isinstance(content, str) and content.strip():
                    append_system(session_dir, content)
            elif ev.get("type") == "setup_chat_choice":
                question = ev.get("question")
                options = ev.get("options")
                if isinstance(question, str) and question.strip() and isinstance(options, list):
                    rec = append_choice(session_dir, question, options)
                    self._setup_chat_pre_turn_choice_msg_ids.append(rec["id"])
            await self._emit_setup_chat(ev)

        return _emit

    async def _emit_setup_chat(self, ev: dict) -> None:
        """Bookkeeping + broadcast in one call -- replaces bare `await self.broadcast(ev)` at
        every setup_chat_* call site (the `_make_setup_chat_emit` closure, plus the two spots
        that broadcast a terminal event directly), so a remounted frontend can recover an
        in-flight round's content. Terminal events clear the cache synchronously (no await)
        before broadcasting, so a concurrent REST history request can never observe a terminal
        event inside the cached list -- it sees either the full in-progress list or None."""
        live = self._setup_chat_live.get(active_novel_id())
        if live is not None:
            live["events"].append(ev)
            if ev.get("type") in _SETUP_CHAT_TERMINAL_EVENT_TYPES:
                self._setup_chat_live.pop(active_novel_id(), None)
        await self.broadcast(ev)

    def _make_setup_chat_accountant(self, novel_id: str):
        from llm.factory import get_cloud_llm

        from api.services.token_accountant import TokenAccountant

        cloud_llm = get_cloud_llm()
        return TokenAccountant(
            novel_id=novel_id, subsystem="setup", key="chat",
            model=str(getattr(cloud_llm, "model", "") or getattr(cloud_llm, "model_name", "") or "cloud"),
        )

    async def check_setup_chat_recovery(self) -> None:
        """Session-load detection (spec D9): once per novel per process."""
        novel_id = active_novel_id()
        if novel_id in self._recovery_checked or self.is_setup_chat_busy():
            return
        self._recovery_checked.add(novel_id)
        from engine.setup_chat.agent import run_recovery

        agent = await self._ensure_setup_chat_agent(novel_id)
        emit = self._make_setup_chat_emit()
        accountant = self._make_setup_chat_accountant(novel_id)

        async def _run() -> None:
            with use_novel(novel_id):
                try:
                    await run_recovery(agent, novel_id, emit, accountant)
                except Exception:  # noqa: BLE001
                    logger.exception("setup-chat 会话加载恢复检测失败")
                finally:
                    self._setup_chat_tasks.pop(novel_id, None)
                    self._setup_chat_live.pop(novel_id, None)
                    await self._on_setup_chat_turn_finished(novel_id)

        self._setup_chat_live[novel_id] = {"novel_id": novel_id, "instruction": "", "events": []}
        self._setup_chat_tasks[novel_id] = asyncio.create_task(_run())

    async def _broadcast_setup_chat_queued(self, novel_id: str) -> None:
        await self.broadcast({
            "type": "setup_chat_queued",
            "novel_id": novel_id,
            "depth": SETUP_CHAT_TURN_QUEUE.len_for(novel_id),
        })

    async def _on_setup_chat_turn_finished(self, novel_id: str) -> None:
        await self._finish_incomplete_image_progress(novel_id)
        # A review batch may have gone quiet while this turn was running -- flush it into
        # the queue now (agent just went idle) before draining.
        await self._maybe_flush_review_feedback(novel_id)
        await self._try_drain_setup_chat_queue(novel_id)

    async def begin_image_recognition_progress(
        self, total: int, *, novel_id: str | None = None,
    ) -> None:
        """Start (or extend) aggregate image-recognition progress for the current turn.
        Called when read_attachment_image(s) actually enters the vision pipeline -- not
        optimistically at turn start -- so the UI bar only appears once work begins."""
        if total <= 0:
            return
        nid = novel_id or active_novel_id()
        state = self._setup_chat_image_progress.get(nid)
        if state is None:
            self._setup_chat_image_progress[nid] = {"done": 0, "total": total}
            await self.broadcast({
                "type": "novel_import_image_start",
                "total": total,
                "novel_id": nid,
            })
            return
        state["total"] += total
        await self.broadcast({
            "type": "novel_import_image_progress",
            "index": state["done"],
            "total": state["total"],
            "ok": True,
            "error": None,
            "novel_id": nid,
        })

    async def _finish_incomplete_image_progress(self, novel_id: str) -> None:
        """Clear stuck image progress when a turn ends before all pages were recognized."""
        state = self._setup_chat_image_progress.pop(novel_id, None)
        if state is None or state["done"] >= state["total"]:
            return
        await self.broadcast({
            "type": "novel_import_image_done",
            "novel_id": novel_id,
            "cancelled": True,
        })

    async def _try_drain_setup_chat_queue(self, novel_id: str) -> None:
        if self.is_setup_chat_busy(novel_id):
            return
        item = SETUP_CHAT_TURN_QUEUE.pop(novel_id)
        if item is None:
            return
        await self._broadcast_setup_chat_queued(novel_id)
        if item.kind == SetupChatTurnKind.SYSTEM_NOTICE:
            await self._execute_system_notice_turn(item.novel_id, item.summary_text)
            return
        raise NotImplementedError(f"setup chat turn kind not wired yet: {item.kind}")

    async def start_setup_chat_turn(
        self, text: str, attachment_ids: list[str] | None = None,
    ) -> str:
        """
Run a round of setting dialogue: user message will be recorded when entering; engine stream will be broadcast through gateway; assistant will be recorded at the end.

        attachment_ids (if any) are folded into the text the agent sees (as an id+filename
        manifest) but NOT into what gets recorded as the user's chat-history message —
        the frontend already shows attachments as separate chips, not inline text."""
        if self.is_setup_chat_busy():
            raise RuntimeError("有任务运行中，无法开始新一轮对话")
        novel_id = active_novel_id()
        await self._execute_user_turn(novel_id, text, attachment_ids or [])
        return "running"

    async def _execute_user_turn(
        self,
        novel_id: str,
        text: str,
        attachment_ids: list[str],
        *,
        user_msg_id: str | None = None,
    ) -> None:
        from engine.setup_chat.session_record import append_user

        session_dir = setup_chat_session_dir()
        if user_msg_id:
            self._setup_chat_pre_turn_user_msg_id = user_msg_id
        else:
            user_rec = append_user(session_dir, text)
            self._setup_chat_pre_turn_user_msg_id = user_rec["id"]
        self._setup_chat_pre_turn_choice_msg_ids = []

        agent_text = text
        self._setup_chat_image_progress.pop(novel_id, None)
        if attachment_ids:
            from engine.setup_chat.attachments import describe_attachments
            manifest = describe_attachments(attachment_ids)
            if manifest:
                agent_text = f"{manifest}\n\n{text}" if text else manifest

        agent = await self._ensure_setup_chat_agent(novel_id)
        _emit = self._make_setup_chat_emit()
        accountant = self._make_setup_chat_accountant(novel_id)

        from engine.setup_chat.turn_snapshot import snapshot_turn_start

        config = {"configurable": {"thread_id": novel_id}}
        self._setup_chat_pre_state = await agent.aget_state(config)
        snapshot_turn_start()

        self._setup_chat_live[novel_id] = {"novel_id": novel_id, "instruction": text, "events": []}

        async def _run() -> None:
            with use_novel(novel_id):
                try:
                    await run_turn(agent, novel_id, agent_text, _emit, accountant)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("[setup_chat] turn failed")
                    await self._emit_setup_chat({"type": "setup_chat_error", "error": str(exc)})
                finally:
                    self._setup_chat_tasks.pop(novel_id, None)
                    self._setup_chat_pre_state = None
                    self._setup_chat_pre_turn_user_msg_id = None
                    self._setup_chat_live.pop(novel_id, None)
                    await self._on_setup_chat_turn_finished(novel_id)

        await self.broadcast({"type": "setup_chat_start", "novel_id": novel_id})
        self._setup_chat_tasks[novel_id] = asyncio.create_task(_run())

    async def regenerate_setup_chat_turn(self, user_text: str) -> str:
        """Retry the last failed assistant reply for ``user_text`` without duplicating the user
        bubble in session_record. Truncates partial checkpoint messages after the matching
        HumanMessage when present; otherwise starts a fresh graph input (e.g. HTTP POST never
        reached the engine)."""
        user_text = user_text.strip()
        if not user_text:
            raise ValueError("没有可重新生成的消息")
        if self.is_setup_chat_busy():
            raise RuntimeError("有任务运行中，无法重新生成")
        novel_id = active_novel_id()
        await self._execute_regenerate_turn(novel_id, user_text)
        return "running"

    async def _execute_regenerate_turn(self, novel_id: str, user_text: str) -> None:
        from engine.setup_chat.session_record import append_user, load_messages

        session_dir = setup_chat_session_dir()
        records = load_messages(session_dir)
        last_user_rec = next((r for r in reversed(records) if r.get("role") == "user"), None)
        if not last_user_rec or last_user_rec.get("content") != user_text:
            last_user_rec = append_user(session_dir, user_text)

        agent = await self._ensure_setup_chat_agent(novel_id)
        config = {"configurable": {"thread_id": novel_id}}
        state = await agent.aget_state(config)
        msgs = list((state.values or {}).get("messages") or [])

        retry = False
        for i in range(len(msgs) - 1, -1, -1):
            if getattr(msgs[i], "type", "") != "human":
                continue
            content = msgs[i].content if isinstance(msgs[i].content, str) else str(msgs[i].content or "")
            if content == user_text:
                trimmed = msgs[: i + 1]
                if len(trimmed) < len(msgs):
                    from langchain_core.messages import RemoveMessage
                    from langgraph.graph.message import REMOVE_ALL_MESSAGES

                    await agent.aupdate_state(
                        config,
                        {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *trimmed]},
                        as_node="agent",
                    )
                retry = True
            break

        from engine.setup_chat.turn_snapshot import restore_turn_start, snapshot_turn_start

        restore_turn_start()

        _emit = self._make_setup_chat_emit()
        accountant = self._make_setup_chat_accountant(novel_id)
        self._setup_chat_pre_state = await agent.aget_state(config)
        snapshot_turn_start()
        self._setup_chat_pre_turn_user_msg_id = last_user_rec["id"]
        self._setup_chat_pre_turn_choice_msg_ids = []
        self._setup_chat_live[novel_id] = {"novel_id": novel_id, "instruction": user_text, "events": []}

        async def _run() -> None:
            with use_novel(novel_id):
                try:
                    await run_turn(agent, novel_id, user_text, _emit, accountant, retry=retry)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("[setup_chat] regenerate turn failed")
                    await self._emit_setup_chat({"type": "setup_chat_error", "error": str(exc)})
                finally:
                    self._setup_chat_tasks.pop(novel_id, None)
                    self._setup_chat_pre_state = None
                    self._setup_chat_pre_turn_user_msg_id = None
                    self._setup_chat_live.pop(novel_id, None)
                    await self._on_setup_chat_turn_finished(novel_id)

        await self.broadcast({"type": "setup_chat_start", "novel_id": novel_id})
        self._setup_chat_tasks[novel_id] = asyncio.create_task(_run())

    async def report_review_done(
        self,
        novel_id: str,
        pending_key: ReviewKey,
        entries: Sequence[tuple[ReviewKey, ReviewFeedbackEntry]],
    ) -> None:
        """Called by the four background review/derivation modules once a job finishes
        (replacing their old direct trigger_system_notice_turn call). `entries` empty
        means the target was deleted while the review was queued / there is nothing to
        report -- the barrier unit is still released. See
        docs/superpowers/specs/2026-08-27-setup-chat-review-feedback-barrier-design.md."""
        from api.services.setup_chat_review_feedback import REVIEW_FEEDBACK

        for buffer_key, entry in entries:
            REVIEW_FEEDBACK.record(novel_id, buffer_key, entry)
        REVIEW_FEEDBACK.clear_pending(novel_id, pending_key)
        REVIEW_FEEDBACK.reset_attempt(novel_id, pending_key)
        await self._maybe_flush_review_feedback(novel_id)

    async def _maybe_flush_review_feedback(self, novel_id: str) -> None:
        """Flush the whole batch as one system-notice turn iff (a) no review for this
        novel is still in flight and (b) the setup-chat agent is idle. Otherwise hold:
        another report_review_done, or _on_setup_chat_turn_finished, will retry."""
        from api.services.setup_chat_review_feedback import (
            REVIEW_FEEDBACK,
            render_review_feedback,
        )

        if REVIEW_FEEDBACK.has_pending(novel_id):
            return
        entries = REVIEW_FEEDBACK.snapshot(novel_id)
        if not entries:
            return
        if self.is_setup_chat_busy(novel_id):
            return
        REVIEW_FEEDBACK.clear_buffer(novel_id)
        await self.trigger_system_notice_turn(novel_id, render_review_feedback(entries))

    async def trigger_system_notice_turn(
        self, novel_id: str, summary_text: str,
    ) -> None:
        """Called once a background job finishes (character review, chapter skeleton
        review, timeline cascade, world review -- see setup_chat_turn_queue.py's
        enqueue_or_merge_system_notice docstring). Folds into an already-queued,
        not-yet-consumed system notice when one exists, so several such jobs landing
        while the agent is busy collapse into a single chat-agent turn instead of one
        per job; drains immediately when the agent is idle."""
        SETUP_CHAT_TURN_QUEUE.enqueue_or_merge_system_notice(novel_id, summary_text)
        await self._broadcast_setup_chat_queued(novel_id)
        await self._try_drain_setup_chat_queue(novel_id)

    async def _execute_system_notice_turn(self, novel_id: str, summary_text: str) -> None:
        from engine.setup_chat.session_record import append_system

        session_dir = setup_chat_session_dir(novel_id)
        append_system(session_dir, "[后台系统事件] 后台任务已完成，详情见下方回复。")

        agent = await self._ensure_setup_chat_agent(novel_id)
        _emit = self._make_setup_chat_emit(novel_id)
        accountant = self._make_setup_chat_accountant(novel_id)
        agent_text = (
            "【系统事件，非用户输入】以下是后台自动审查/修复的结果，请你用自己的话跟用户说明情况"
            f"（不要把这段原文照抄给用户）：\n\n{summary_text}"
        )

        self._setup_chat_live[novel_id] = {
            "novel_id": novel_id, "instruction": agent_text, "events": [],
        }

        async def _run() -> None:
            with use_novel(novel_id):
                try:
                    await run_turn(agent, novel_id, agent_text, _emit, accountant)
                except Exception as exc:  # noqa: BLE001 - background turn, must not raise into drain
                    logger.exception("[setup_chat] background review notify turn failed")
                    await self._emit_setup_chat({"type": "setup_chat_error", "error": str(exc)})
                finally:
                    self._setup_chat_tasks.pop(novel_id, None)
                    self._setup_chat_live.pop(novel_id, None)
                    await self._on_setup_chat_turn_finished(novel_id)

        await self.broadcast({"type": "setup_chat_start", "novel_id": novel_id})
        self._setup_chat_tasks[novel_id] = asyncio.create_task(_run())

    async def advance_image_recognition_progress(
        self, *, ok: bool, error: str | None = None, novel_id: str | None = None,
    ) -> None:
        """Called once per read_attachment_image invocation instead of that tool
        broadcasting its own chunk-level novel_import_* events -- increments the
        turn's image counter and broadcasts aggregate (image count, not text-chunk
        count) progress. No-op if the current turn has no image attachments (or no
        turn is in flight), so a stray/duplicate call can't raise or double-count."""
        nid = novel_id or active_novel_id()
        state = self._setup_chat_image_progress.get(nid)
        if state is None:
            return
        state["done"] += 1
        await self.broadcast({
            "type": "novel_import_image_progress",
            "index": state["done"],
            "total": state["total"],
            "ok": ok,
            "error": error,
            "novel_id": nid,
        })
        if state["done"] >= state["total"]:
            self._setup_chat_image_progress.pop(nid, None)
            await self.broadcast({
                "type": "novel_import_image_done",
                "novel_id": nid,
                "cancelled": False,
            })

    async def note_novel_import_text_start(self, novel_id: str, total: int) -> None:
        self._setup_chat_text_progress[novel_id] = {"index": 0, "total": total}
        await self.broadcast({
            "type": "novel_import_start",
            "total": total,
            "novel_id": novel_id,
        })

    async def note_novel_import_text_progress(
        self,
        novel_id: str,
        *,
        index: int,
        total: int,
        ok: bool,
        error: str | None,
    ) -> None:
        state = self._setup_chat_text_progress.get(novel_id)
        if state is not None:
            state["index"] = index
            state["total"] = total
        await self.broadcast({
            "type": "novel_import_progress",
            "index": index,
            "total": total,
            "ok": ok,
            "error": error,
            "novel_id": novel_id,
        })

    async def note_novel_import_text_done(self, novel_id: str) -> None:
        self._setup_chat_text_progress.pop(novel_id, None)
        await self.broadcast({"type": "novel_import_done", "novel_id": novel_id})

    async def stop_setup_chat_turn(self) -> None:
        """User-initiated cancel + full rollback (D1/D4): graph message-list state, the
        turn-level file-tree snapshot, and the session-record user-message entry all revert
        together. No running task -> no-op, idempotent against the natural-completion race (D5)."""
        novel_id = active_novel_id()
        t = self._setup_chat_tasks.get(novel_id)
        pre_state = self._setup_chat_pre_state
        msg_id = self._setup_chat_pre_turn_user_msg_id
        if t is None:
            return
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
        self._setup_chat_tasks.pop(novel_id, None)
        rollback_failed = False
        try:
            from engine.setup_chat.turn_snapshot import restore_turn_start
            from langchain_core.messages import RemoveMessage
            from langgraph.graph.message import REMOVE_ALL_MESSAGES

            agent = await self._ensure_setup_chat_agent(novel_id)
            config = {"configurable": {"thread_id": novel_id}}
            pre_messages = list(getattr(pre_state, "values", {}).get("messages") or []) if pre_state else []
            await agent.aupdate_state(
                config,
                {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *pre_messages]},
                as_node="agent",
            )
            if not restore_turn_start():
                rollback_failed = True
        except OSError as e:
            logger.warning("setup-chat turn-cancel state rollback failed: {}", e)
            rollback_failed = True
        from engine.setup_chat.session_record import remove_message

        session_dir = setup_chat_session_dir()
        if msg_id is not None:
            if not remove_message(session_dir, msg_id):
                rollback_failed = True
        for choice_id in self._setup_chat_pre_turn_choice_msg_ids:
            if not remove_message(session_dir, choice_id):
                rollback_failed = True
        self._setup_chat_pre_turn_choice_msg_ids = []
        self._setup_chat_pre_state = None
        self._setup_chat_pre_turn_user_msg_id = None
        await self._on_setup_chat_turn_finished(novel_id)
        await self._emit_setup_chat({
            "type": "setup_chat_turn_cancelled", "rollback_failed": rollback_failed, "novel_id": novel_id,
        })

    def is_story_sandbox_busy(self, novel_id: str | None = None) -> bool:
        nid = novel_id or active_novel_id()
        t = self._story_sandbox_tasks.get(nid)
        return bool(t and not t.done())

    async def reset_story_sandbox(self, novel_id: str | None = None) -> None:
        """Discard this novel's checkpointer connection and word-density guards (novel deletion,
        before its directory is trashed). novel_id=None defaults to the currently active novel.
        Never interrupts a turn in progress for that novel (same caution as reset_setup_chat)."""
        nid = novel_id or active_novel_id()
        if self.is_story_sandbox_busy(nid):
            return
        from engine.story_sandbox.graph import close_checkpointer
        await close_checkpointer(nid)
        for key in [k for k in self._story_sandbox_word_guards if k[0] == nid]:
            self._story_sandbox_word_guards.pop(key, None)
        for key in [
            k for k in self._story_sandbox_last_round_word_guard_snapshot if k[0] == nid
        ]:
            self._story_sandbox_last_round_word_guard_snapshot.pop(key, None)

    async def reset_all_story_sandbox(self) -> None:
        """Shutdown teardown: close every novel's checkpointer connection, not just the
        currently active one -- true concurrency means multiple novels can each have an open
        connection at once."""
        from engine.story_sandbox.graph import close_checkpointer

        await close_checkpointer()
        self._story_sandbox_word_guards.clear()
        self._story_sandbox_last_round_word_guard_snapshot.clear()

    def _story_sandbox_word_guard(self, novel_id: str, chapter: int, branch_id: str) -> WordDensityGuard:
        """Get-or-create the persistent per-(novel_id, chapter, branch_id) word-density guard --
        aligns sandbox with author_loop's "one guard shared across the whole chapter" semantics,
        scoped per story line so two branches of the same chapter don't share a sliding-window
        budget."""
        from engine.execution.style_guard import WordDensityGuard

        key = (novel_id, chapter, branch_id)
        guard = self._story_sandbox_word_guards.get(key)
        if guard is None:
            guard = WordDensityGuard()
            self._story_sandbox_word_guards[key] = guard
        return guard

    def _make_guard_text(
        self, *, chapter: int, word_guard: WordDensityGuard,
        accountant: TokenAccountant, sandbox_llm_params: dict,
    ) -> tuple[Callable[[str], Callable[[str], Awaitable[str]]], PromptLogger]:
        """Shared rewrite-LLM/logger/word_guard (unchanged) but returns a per-node closure
        factory instead of one shared closure -- each of the 5 non-prose sandbox nodes gets its
        own disable_style_guard check, mirroring how _make_call_llm(node) already builds a
        separate call_llm_<node> closure per node."""
        from domain.token_usage import extract_usage
        from engine.execution.style_guard import (
            forbidden_words_text,
            get_compiled_patterns,
            guard_text,
        )
        from langchain_core.messages import HumanMessage, SystemMessage
        from llm.factory import get_style_guard_llm
        from llm.prompt_logger import PromptLogger

        style_guard_llm = get_style_guard_llm()
        model = _model_name(style_guard_llm, "cloud")
        prompt_logger = PromptLogger(chapter)

        async def _rewrite(context: str, offending: str, trigger: str) -> str:
            # Mirrors the prose _write_turn rewrite closures' start/end broadcast -- without it
            # the frontend's "检测到 AI 味文本，正在重写" indicator only ever fires for prose
            # hits, silently skipping the 5 short-field nodes this closure guards.
            await self._emit_sandbox({"type": "story_sandbox_style_rewrite", "status": "start"})
            rewrite_user = (
                f"待重写句：{offending}\n\n"
                f"这句命中了应避免的词/句式：「{trigger}」——重写时必须换成完全不同的表达，"
                f"不能再出现这个词，也不能是雷同结构的变体。\n\n"
                f"另外，以下词汇全篇都应避免使用，重写时也不要换成它们中的任何一个："
                f"{forbidden_words_text()}"
            )
            t1 = time.monotonic()
            resp = await style_guard_llm.ainvoke(
                [SystemMessage(content=_SHORT_FIELD_REWRITE_SYS), HumanMessage(content=rewrite_user)]
            )
            rewritten = resp.content if isinstance(resp.content, str) else str(resp.content)
            rtin, rtout, rtcached = extract_usage(resp)
            prompt_logger.log_llm_call(
                step=0, agent="story_sandbox_short_field_guard_rewrite", model=model,
                system=_SHORT_FIELD_REWRITE_SYS, user=rewrite_user, response=rewritten,
                tokens_in=rtin, tokens_out=rtout, tokens_cached=rtcached,
                duration_s=time.monotonic() - t1,
            )
            await accountant.record(rtin, rtout, rtcached)
            await self._emit_sandbox({"type": "story_sandbox_style_rewrite", "status": "end"})
            return rewritten.strip()

        def _on_exhausted(sentence: str) -> None:
            prompt_logger.log_event(
                "style_guard_exhausted", step=0, agent="story_sandbox_short_field", sentence=sentence,
            )

        def _guard_text_for(node: str) -> Callable[[str], Awaitable[str]]:
            disabled = bool(sandbox_llm_params.get(node, {}).get("disable_style_guard"))

            async def _guard(text: str) -> str:
                if not text or disabled:
                    return text
                return await guard_text(
                    text, patterns=get_compiled_patterns(), rewrite=_rewrite,
                    on_exhausted=_on_exhausted, word_guard=word_guard,
                )
            return _guard

        return _guard_text_for, prompt_logger

    async def _emit_sandbox(self, ev: dict) -> None:
        """Bookkeeping + broadcast in one call -- replaces bare `await self.broadcast(ev)` at
        every story_sandbox_* call site inside start_story_sandbox_turn/start_story_sandbox_rewrite/
        stop_story_sandbox_turn, so a remounted frontend can recover an in-flight round's content.
        Terminal events clear the cache synchronously (no await) before broadcasting, so a
        concurrent REST history request can never observe a terminal event inside the cached
        list -- it sees either the full in-progress list or None."""
        nid = active_novel_id()
        live = self._story_sandbox_live.get(nid)
        if live is not None:
            live["events"].append(ev)
            if ev.get("type") in _SANDBOX_TERMINAL_EVENT_TYPES:
                self._story_sandbox_live.pop(nid, None)
        await self.broadcast(ev)

    async def start_story_sandbox_turn(
        self, chapter: int, text: str, submitted_directions: list[str] | None = None,
        *, branch_id: str = LEGACY_BRANCH_ID,
        _write_turn_override: WriteTurn | None = None,
    ) -> None:
        """Run one story-sandbox turn: the real streaming (write_turn) and plain (call_llm)
        LLM-call closures are defined here and injected into the graph, which never touches an
        LLM client itself -- mirrors author_loop's AuthorTurns/CallLLM protocol split.
        submitted_directions, if given, marks the previous round's own suggestions that this
        turn's instruction was built from (see graph.py::run_turn)."""
        if self.is_story_sandbox_busy():
            raise RuntimeError("有任务运行中，无法开始新一轮沙盒回合")

        from utils.timer import sandbox_step_timer

        async with sandbox_step_timer("sandbox_turn_setup", {"chapter": chapter}):
            novel_id = active_novel_id()
            self._story_sandbox_derive_retry_cache.pop((novel_id, chapter, branch_id), None)

            from engine.execution.prose_style import build_active_prose_style_card
            from engine.modes.author_loop_skill_prefs import bind_node_llm, load_dialogue_prefs
            from engine.story_sandbox.derivation_retry import DerivationValidationError
            from engine.story_sandbox.state import SandboxLiveMode, SandboxStepType
            from langchain_core.messages import HumanMessage, SystemMessage
            from llm.factory import get_cloud_llm, get_style_guard_llm

            llm = get_cloud_llm()
            style_guard_llm = get_style_guard_llm()
            style_guard_model = _model_name(style_guard_llm, "cloud")
            sandbox_llm_params = load_dialogue_prefs().get("sandbox_llm_params", {})
            prose_llm = bind_node_llm(llm, "prose", sandbox_llm_params)
            prose_guard_disabled = bool(sandbox_llm_params.get("prose", {}).get("disable_style_guard"))
            word_guard = self._story_sandbox_word_guard(novel_id, chapter, branch_id)
            style = build_active_prose_style_card()

            from domain.token_usage import extract_usage

            from api.services.token_accountant import TokenAccountant

            accountant = TokenAccountant(
                novel_id=novel_id, subsystem="story_sandbox", key=str(chapter),
                model=str(getattr(llm, "model", "") or getattr(llm, "model_name", "") or "cloud"),
            )

            async def _write_turn(system: str, packet: str) -> str:
                async with sandbox_step_timer("prose_write_turn", {"chapter": chapter}):
                    from engine.execution.style_guard import (
                        forbidden_words_text,
                        get_compiled_patterns,
                        guarded_stream,
                    )
                    from engine.story_sandbox.prose_format import strip_prose_preamble
                    from llm.prompt_logger import PromptLogger

                    model = _model_name(prose_llm, "cloud")
                    prompt_logger = PromptLogger(chapter)
                    chunks: list[str] = []
                    usage_chunk: dict = {}

                    async def _token_source():
                        ttft_start = time.monotonic()
                        ttft_logged = False
                        async for ch in prose_llm.astream(
                            [SystemMessage(content=system), HumanMessage(content=packet)], stream_usage=True,
                        ):
                            if getattr(ch, "usage_metadata", None):
                                usage_chunk["chunk"] = ch
                            piece = ch.content if isinstance(ch.content, str) else str(ch.content)
                            if piece:
                                if not ttft_logged:
                                    ttft_logged = True
                                    logger.info(
                                        "[story_sandbox_perf] Node 'prose_ttft' COMPLETED | elapsed_ms={:.2f}",
                                        (time.monotonic() - ttft_start) * 1000,
                                    )
                                yield piece

                async def _rewrite(context: str, offending: str, trigger: str) -> str:
                    #命中禁用句式后的局部重写：只喂上文尾巴 + 命中句，不带完整回合素材；
                    #system 拼上本书文风卡，避免重写把违规句换成另一种不合文风的句子。
                    await self._emit_sandbox({"type": "story_sandbox_style_rewrite", "status": "start"})
                    rewrite_user = (
                        f"上文（仅供承接语气，不要重复）：{context}\n\n"
                        f"待重写句：{offending}\n\n"
                        f"这句命中了应避免的词/句式：「{trigger}」——重写时必须换成完全不同的表达，"
                        f"不能再出现这个词，也不能是雷同结构的变体。\n\n"
                        f"另外，以下词汇全篇都应避免使用，重写时也不要换成它们中的任何一个："
                        f"{forbidden_words_text()}"
                    )
                    rewrite_sys = _rewrite_sys(style)
                    t1 = time.monotonic()
                    resp = await style_guard_llm.ainvoke(
                        [SystemMessage(content=rewrite_sys), HumanMessage(content=rewrite_user)]
                    )
                    rewritten = resp.content if isinstance(resp.content, str) else str(resp.content)
                    rtin, rtout, rtcached = extract_usage(resp)
                    prompt_logger.log_llm_call(
                        step=0, agent="story_sandbox_guard_rewrite", model=style_guard_model,
                        system=rewrite_sys, user=rewrite_user, response=rewritten,
                        tokens_in=rtin, tokens_out=rtout, tokens_cached=rtcached,
                        duration_s=time.monotonic() - t1,
                    )
                    await accountant.record(rtin, rtout, rtcached, model=style_guard_model)
                    await self._emit_sandbox({"type": "story_sandbox_style_rewrite", "status": "end"})
                    return rewritten.strip()

                def _on_exhausted(sentence: str) -> None:
                    prompt_logger.log_event(
                        "style_guard_exhausted", step=0, agent="story_sandbox", sentence=sentence,
                    )

                def _build_token_stream():
                    usage_chunk.clear()
                    return (
                        strip_prose_preamble(_token_source()) if prose_guard_disabled
                        else guarded_stream(
                            strip_prose_preamble(_token_source()), patterns=get_compiled_patterns(),
                            rewrite=_rewrite, on_exhausted=_on_exhausted,
                            word_guard=word_guard,
                        )
                    )

                try:
                    async for piece in _build_token_stream():
                        chunks.append(piece)
                        await self._emit_sandbox({"type": "story_sandbox_token", "delta": piece})
                finally:
                    prompt_logger.close()
                tin, tout, tcached = extract_usage(usage_chunk.get("chunk"))
                await accountant.record(tin, tout, tcached, model=model)
                return "".join(chunks)

            guard_text_for, short_field_prompt_logger = self._make_guard_text(
                chapter=chapter, word_guard=word_guard, accountant=accountant,
                sandbox_llm_params=sandbox_llm_params,
            )

            def _make_call_llm(node: str):
                bound_llm = bind_node_llm(llm, node, sandbox_llm_params)
                node_model = _model_name(bound_llm, "cloud")

                async def _c(system: str, user: str) -> str:
                    t0 = time.monotonic()
                    resp = await bound_llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
                    content = resp.content if isinstance(resp.content, str) else str(resp.content)
                    tin, tout, tcached = extract_usage(resp)
                    short_field_prompt_logger.log_llm_call(
                        step=0, agent=f"story_sandbox_{node}", model=node_model,
                        system=system, user=user, response=content,
                        tokens_in=tin, tokens_out=tout, tokens_cached=tcached,
                        duration_s=time.monotonic() - t0,
                    )
                    await accountant.record(tin, tout, tcached, model=node_model)
                    return content.strip()
                return _c

            call_llm_derive_char = _make_call_llm("derive_char")
            call_llm_derive_scene = _make_call_llm("derive_scene")
            call_llm_summary_fold = _make_call_llm("summary_fold")
            call_llm_event_extract = _make_call_llm("event_extract")
            call_llm_profile_mutate = _make_call_llm("profile_mutate")
            call_llm_suggest = _make_call_llm("suggest")
            call_llm_identify = _make_call_llm("identify_cast")
            call_llm_dialogue_draft = _make_call_llm("dialogue_draft")

            effective_write_turn = (
                _write_turn_override if _write_turn_override is not None else _write_turn
            )

        async def _run() -> None:
            captured_final_text: str | None = None
            with use_novel(novel_id):
                try:
                    async for step in run_story_sandbox_turn(
                        novel_id, chapter, text, write_turn=effective_write_turn,
                        call_llm_derive_char=call_llm_derive_char, call_llm_derive_scene=call_llm_derive_scene,
                        call_llm_summary_fold=call_llm_summary_fold, call_llm_event_extract=call_llm_event_extract, call_llm_profile_mutate=call_llm_profile_mutate,
                        call_llm_suggest=call_llm_suggest, call_llm_identify=call_llm_identify,
                        call_llm_dialogue_draft=call_llm_dialogue_draft,
                        guard_text_derive_char=guard_text_for("derive_char"),
                        guard_text_derive_scene=guard_text_for("derive_scene"),
                        guard_text_summary_fold=guard_text_for("summary_fold"),
                        guard_text_event_extract=guard_text_for("event_extract"),
                        guard_text_profile_mutate=guard_text_for("profile_mutate"),
                        guard_text_suggest=guard_text_for("suggest"),
                        submitted_directions=submitted_directions,
                        branch_id=branch_id,
                    ):
                        if step["type"] == SandboxStepType.INITIAL_STATE:
                            await self._emit_sandbox({
                                "type": "story_sandbox_initial_states", "states": step["states"],
                                "scene_state": step.get("scene_state") or {},
                            })
                        elif step["type"] == SandboxStepType.PROSE:
                            captured_final_text = step["text"]
                            await self._emit_sandbox({
                                "type": "story_sandbox_final", "content": step["text"],
                                "active_cast": step.get("active_cast", []),
                            })
                            await self._emit_sandbox({
                                "type": "story_sandbox_recall_context",
                                "recall_context": step.get("recall_context", ""),
                                "recalled_settings": step.get("recalled_settings", []),
                            })
                        elif step["type"] == SandboxStepType.STATE:
                            await self._emit_sandbox({
                                "type": "story_sandbox_states", "states": step["states"],
                                "scene_state": step.get("scene_state") or {},
                                "active_cast": step.get("active_cast", []),
                            })
                        elif step["type"] == SandboxStepType.SUGGESTIONS:
                            await self._emit_sandbox({
                                "type": "story_sandbox_suggestions", "options": step["options"],
                                "round_id": step.get("round_id"),
                            })
                        elif step["type"] == SandboxStepType.EVENT_LOG:
                            await self._emit_sandbox({
                                "type": "story_sandbox_event_log",
                                "entries": step.get("entries") or [],
                                "rolling_summary": step.get("rolling_summary", ""),
                            })
                        elif step["type"] == SandboxStepType.PROFILE_MUTATION:
                            await self._emit_sandbox({
                                "type": "story_sandbox_profile_mutation",
                                "mutation": step.get("mutation"),
                                "relationship_mutation": step.get("relationship_mutation"),
                            })
                    self._story_sandbox_last_round_word_guard_snapshot[
                        (novel_id, chapter, branch_id)
                    ] = pre_word_guard_snapshot
                    from engine.story_sandbox import branches as sandbox_branches
                    sandbox_branches.touch_branch(chapter, branch_id)
                    self._story_sandbox_derive_retry_cache.pop((novel_id, chapter, branch_id), None)
                    await self._emit_sandbox({"type": "story_sandbox_done"})
                except DerivationValidationError as exc:
                    self._story_sandbox_derive_retry_cache[(novel_id, chapter, branch_id)] = {
                        "mode": "turn", "final_text": captured_final_text,
                        "instruction": text, "submitted_directions": submitted_directions,
                    }
                    await self._emit_sandbox({
                        "type": "story_sandbox_error", "error": str(exc), "code": exc.code.value,
                    })
                except Exception as exc:  # noqa: BLE001
                    logger.exception("[story_sandbox] turn failed")
                    await self._emit_sandbox({"type": "story_sandbox_error", "error": str(exc)})
                finally:
                    short_field_prompt_logger.close()
                    self._story_sandbox_tasks.pop(novel_id, None)
                    self._story_sandbox_pre_states.pop(novel_id, None)
                    self._story_sandbox_live.pop(novel_id, None)

        self._story_sandbox_pre_states[novel_id] = await snapshot_story_sandbox_state(
            novel_id, chapter, branch_id=branch_id,
        )
        pre_word_guard_snapshot = word_guard.snapshot()
        self._story_sandbox_pre_word_guard_snapshots[novel_id] = pre_word_guard_snapshot
        self._story_sandbox_live[novel_id] = {
            "novel_id": novel_id, "chapter": chapter, "branch_id": branch_id,
            "mode": SandboxLiveMode.TURN, "instruction": text, "events": [],
        }
        await self.broadcast({"type": "story_sandbox_start", "chapter": chapter, "novel_id": novel_id})
        self._story_sandbox_tasks[novel_id] = asyncio.create_task(_run())

    async def stop_story_sandbox_turn(self, chapter: int, *, branch_id: str = LEGACY_BRANCH_ID) -> None:
        """User-initiated cancel + full rollback (D1) -- distinct from author_loop's
        stop_author_loop, which keeps already-written content. No running task -> no-op,
        idempotent against the natural-completion race (D5)."""
        novel_id = active_novel_id()
        t = self._story_sandbox_tasks.get(novel_id)
        pre_state = self._story_sandbox_pre_states.get(novel_id)
        pre_word_guard_snapshot = self._story_sandbox_pre_word_guard_snapshots.get(novel_id)
        if t is None:
            return
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
        self._story_sandbox_tasks.pop(novel_id, None)
        rollback_failed = False
        try:
            await restore_story_sandbox_state(
                novel_id, chapter, pre_state or {}, branch_id=branch_id,
            )
        except OSError as e:
            logger.warning("story-sandbox turn-cancel rollback failed: {}", e)
            rollback_failed = True
        if pre_word_guard_snapshot is not None:
            self._story_sandbox_word_guard(novel_id, chapter, branch_id).restore(pre_word_guard_snapshot)
        self._story_sandbox_pre_word_guard_snapshots.pop(novel_id, None)
        self._story_sandbox_pre_states.pop(novel_id, None)
        await self._emit_sandbox({
            "type": "story_sandbox_turn_cancelled", "chapter": chapter,
            "rollback_failed": rollback_failed, "novel_id": novel_id,
        })

    async def start_story_sandbox_rewrite(
        self, chapter: int, feedback: str, *, branch_id: str = LEGACY_BRANCH_ID,
        _write_turn_override: WriteTurn | None = None,
    ) -> None:
        """Regenerate the chapter's latest sandbox round's prose in place, steered by free-text
        feedback -- mirrors start_story_sandbox_turn's streaming/broadcast shape but reuses the
        same busy-guard (a rewrite in flight blocks a normal turn / suggestions regenerate /
        another rewrite, same as everything else in this feature)."""
        if self.is_story_sandbox_busy():
            raise RuntimeError("有任务运行中，无法开始重写")

        novel_id = active_novel_id()
        self._story_sandbox_derive_retry_cache.pop((novel_id, chapter, branch_id), None)

        from engine.execution.prose_style import build_active_prose_style_card
        from engine.modes.author_loop_skill_prefs import bind_node_llm, load_dialogue_prefs
        from engine.story_sandbox.derivation_retry import DerivationValidationError
        from engine.story_sandbox.graph import rewrite_last_round
        from engine.story_sandbox.state import SandboxLiveMode, SandboxStepType
        from langchain_core.messages import HumanMessage, SystemMessage
        from llm.factory import get_cloud_llm, get_style_guard_llm

        llm = get_cloud_llm()
        style_guard_llm = get_style_guard_llm()
        style_guard_model = _model_name(style_guard_llm, "cloud")
        sandbox_llm_params = load_dialogue_prefs().get("sandbox_llm_params", {})
        prose_llm = bind_node_llm(llm, "prose", sandbox_llm_params)
        prose_guard_disabled = bool(sandbox_llm_params.get("prose", {}).get("disable_style_guard"))
        word_guard = self._story_sandbox_word_guard(novel_id, chapter, branch_id)
        pre_word_guard_snapshot = word_guard.snapshot()  # 这次重写开始前，旧正文仍计入的状态
        last_round_snapshot = self._story_sandbox_last_round_word_guard_snapshot.get(
            (novel_id, chapter, branch_id)
        )
        if last_round_snapshot is not None:
            word_guard.restore(last_round_snapshot)  # 撤销被替换的旧正文的词频贡献
        style = build_active_prose_style_card()

        from domain.token_usage import extract_usage

        from api.services.token_accountant import TokenAccountant

        accountant = TokenAccountant(
            novel_id=novel_id, subsystem="story_sandbox", key=str(chapter),
            model=str(getattr(llm, "model", "") or getattr(llm, "model_name", "") or "cloud"),
        )

        async def _write_turn(system: str, packet: str) -> str:
            from engine.execution.style_guard import (
                forbidden_words_text,
                get_compiled_patterns,
                guarded_stream,
            )
            from engine.story_sandbox.prose_format import strip_prose_preamble
            from llm.prompt_logger import PromptLogger

            model = _model_name(prose_llm, "cloud")
            prompt_logger = PromptLogger(chapter)
            chunks: list[str] = []
            usage_chunk: dict = {}

            async def _token_source():
                async for ch in prose_llm.astream(
                    [SystemMessage(content=system), HumanMessage(content=packet)], stream_usage=True,
                ):
                    if getattr(ch, "usage_metadata", None):
                        usage_chunk["chunk"] = ch
                    piece = ch.content if isinstance(ch.content, str) else str(ch.content)
                    if piece:
                        yield piece

            async def _rewrite(context: str, offending: str, trigger: str) -> str:
                #命中禁用句式后的局部重写：只喂上文尾巴 + 命中句，不带完整回合素材；
                #system 拼上本书文风卡，避免重写把违规句换成另一种不合文风的句子。
                await self._emit_sandbox({"type": "story_sandbox_style_rewrite", "status": "start"})
                rewrite_user = (
                    f"上文（仅供承接语气，不要重复）：{context}\n\n"
                    f"待重写句：{offending}\n\n"
                    f"这句命中了应避免的词/句式：「{trigger}」——重写时必须换成完全不同的表达，"
                    f"不能再出现这个词，也不能是雷同结构的变体。\n\n"
                    f"另外，以下词汇全篇都应避免使用，重写时也不要换成它们中的任何一个："
                    f"{forbidden_words_text()}"
                )
                rewrite_sys = _rewrite_sys(style)
                t1 = time.monotonic()
                resp = await style_guard_llm.ainvoke(
                    [SystemMessage(content=rewrite_sys), HumanMessage(content=rewrite_user)]
                )
                rewritten = resp.content if isinstance(resp.content, str) else str(resp.content)
                rtin, rtout, rtcached = extract_usage(resp)
                prompt_logger.log_llm_call(
                    step=0, agent="story_sandbox_rewrite_guard_rewrite", model=style_guard_model,
                    system=rewrite_sys, user=rewrite_user, response=rewritten,
                    tokens_in=rtin, tokens_out=rtout, tokens_cached=rtcached,
                    duration_s=time.monotonic() - t1,
                )
                await accountant.record(rtin, rtout, rtcached, model=style_guard_model)
                await self._emit_sandbox({"type": "story_sandbox_style_rewrite", "status": "end"})
                return rewritten.strip()

            def _on_exhausted(sentence: str) -> None:
                prompt_logger.log_event(
                    "style_guard_exhausted", step=0, agent="story_sandbox_rewrite", sentence=sentence,
                )

            def _build_token_stream():
                usage_chunk.clear()
                return (
                    strip_prose_preamble(_token_source()) if prose_guard_disabled
                    else guarded_stream(
                        strip_prose_preamble(_token_source()), patterns=get_compiled_patterns(),
                        rewrite=_rewrite, on_exhausted=_on_exhausted,
                        word_guard=word_guard,
                    )
                )

            try:
                async for piece in _build_token_stream():
                    chunks.append(piece)
                    await self._emit_sandbox({"type": "story_sandbox_rewrite_token", "delta": piece})
            finally:
                prompt_logger.close()
            tin, tout, tcached = extract_usage(usage_chunk.get("chunk"))
            await accountant.record(tin, tout, tcached, model=model)
            return "".join(chunks)

        guard_text_for, short_field_prompt_logger = self._make_guard_text(
            chapter=chapter, word_guard=word_guard, accountant=accountant,
            sandbox_llm_params=sandbox_llm_params,
        )

        def _make_call_llm(node: str):
            bound_llm = bind_node_llm(llm, node, sandbox_llm_params)
            node_model = _model_name(bound_llm, "cloud")

            async def _c(system: str, user: str) -> str:
                t0 = time.monotonic()
                resp = await bound_llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
                content = resp.content if isinstance(resp.content, str) else str(resp.content)
                tin, tout, tcached = extract_usage(resp)
                short_field_prompt_logger.log_llm_call(
                    step=0, agent=f"story_sandbox_{node}", model=node_model,
                    system=system, user=user, response=content,
                    tokens_in=tin, tokens_out=tout, tokens_cached=tcached,
                    duration_s=time.monotonic() - t0,
                )
                await accountant.record(tin, tout, tcached, model=node_model)
                return content.strip()
            return _c

        call_llm_derive_char = _make_call_llm("derive_char")
        call_llm_derive_scene = _make_call_llm("derive_scene")
        call_llm_summary_fold = _make_call_llm("summary_fold")
        call_llm_event_extract = _make_call_llm("event_extract")
        call_llm_profile_mutate = _make_call_llm("profile_mutate")
        call_llm_suggest = _make_call_llm("suggest")
        call_llm_identify = _make_call_llm("identify_cast")
        call_llm_dialogue_draft = _make_call_llm("dialogue_draft")

        effective_write_turn = (
            _write_turn_override if _write_turn_override is not None else _write_turn
        )

        async def _run() -> None:
            captured_final_text: str | None = None
            with use_novel(novel_id):
                try:
                    final_text = ""
                    final_states: dict = {}
                    final_scene_state: dict = {}
                    final_suggestions: list[str] = []
                    final_recall_context = ""
                    final_recalled_settings: list[dict] = []
                    final_active_cast: list[str] = []
                    final_event_log_entries: list[dict] = []
                    final_rolling_summary = ""
                    final_profile_mutation: dict | None = None
                    final_relationship_mutation: dict | None = None
                    steps = await rewrite_last_round(
                        novel_id, chapter, feedback, write_turn=effective_write_turn,
                        call_llm_derive_char=call_llm_derive_char, call_llm_derive_scene=call_llm_derive_scene,
                        call_llm_summary_fold=call_llm_summary_fold, call_llm_event_extract=call_llm_event_extract, call_llm_profile_mutate=call_llm_profile_mutate,
                        call_llm_suggest=call_llm_suggest, call_llm_identify=call_llm_identify,
                        call_llm_dialogue_draft=call_llm_dialogue_draft,
                        guard_text_derive_char=guard_text_for("derive_char"),
                        guard_text_derive_scene=guard_text_for("derive_scene"),
                        guard_text_summary_fold=guard_text_for("summary_fold"),
                        guard_text_event_extract=guard_text_for("event_extract"),
                        guard_text_profile_mutate=guard_text_for("profile_mutate"),
                        guard_text_suggest=guard_text_for("suggest"),
                        branch_id=branch_id,
                    )
                    async for step in steps:
                        if step["type"] == SandboxStepType.PROSE:
                            captured_final_text = step["text"]
                            final_text = step["text"]
                            final_recall_context = step.get("recall_context", "")
                            final_recalled_settings = step.get("recalled_settings", [])
                            final_active_cast = step.get("active_cast", [])
                        elif step["type"] == SandboxStepType.STATE:
                            final_states = step["states"]
                            final_scene_state = step.get("scene_state") or {}
                            final_active_cast = step.get("active_cast", final_active_cast)
                            await self._emit_sandbox({
                                "type": "story_sandbox_states", "states": step["states"],
                                "scene_state": final_scene_state,
                                "active_cast": final_active_cast,
                            })
                        elif step["type"] == SandboxStepType.SUGGESTIONS:
                            final_suggestions = step["options"]
                            await self._emit_sandbox({
                                "type": "story_sandbox_suggestions", "options": final_suggestions,
                            })
                        elif step["type"] == SandboxStepType.EVENT_LOG:
                            final_event_log_entries = step.get("entries") or []
                            final_rolling_summary = step.get("rolling_summary", "")
                            await self._emit_sandbox({
                                "type": "story_sandbox_event_log",
                                "entries": final_event_log_entries,
                                "rolling_summary": final_rolling_summary,
                            })
                        elif step["type"] == SandboxStepType.PROFILE_MUTATION:
                            final_profile_mutation = step.get("mutation")
                            final_relationship_mutation = step.get("relationship_mutation")
                            await self._emit_sandbox({
                                "type": "story_sandbox_profile_mutation",
                                "mutation": final_profile_mutation,
                                "relationship_mutation": final_relationship_mutation,
                            })
                    from engine.story_sandbox import branches as sandbox_branches
                    sandbox_branches.touch_branch(chapter, branch_id)
                    self._story_sandbox_derive_retry_cache.pop((novel_id, chapter, branch_id), None)
                    await self._emit_sandbox({
                        "type": "story_sandbox_rewrite_done",
                        "content": final_text,
                        "states": final_states,
                        "scene_state": final_scene_state,
                        "suggestions": final_suggestions,
                        "recall_context": final_recall_context,
                        "recalled_settings": final_recalled_settings,
                        "active_cast": final_active_cast,
                        "entries": final_event_log_entries,
                        "rolling_summary": final_rolling_summary,
                        "mutation": final_profile_mutation,
                        "relationship_mutation": final_relationship_mutation,
                    })
                except DerivationValidationError as exc:
                    self._story_sandbox_derive_retry_cache[(novel_id, chapter, branch_id)] = {
                        "mode": "rewrite", "final_text": captured_final_text,
                        "feedback": feedback,
                    }
                    await self._emit_sandbox({
                        "type": "story_sandbox_error", "error": str(exc), "code": exc.code.value,
                    })
                except Exception as exc:  # noqa: BLE001
                    logger.exception("[story_sandbox] rewrite failed")
                    await self._emit_sandbox({"type": "story_sandbox_error", "error": str(exc)})
                finally:
                    short_field_prompt_logger.close()
                    self._story_sandbox_tasks.pop(novel_id, None)
                    self._story_sandbox_pre_states.pop(novel_id, None)
                    self._story_sandbox_live.pop(novel_id, None)

        self._story_sandbox_pre_states[novel_id] = await snapshot_story_sandbox_state(
            novel_id, chapter, branch_id=branch_id,
        )
        self._story_sandbox_pre_word_guard_snapshots[novel_id] = pre_word_guard_snapshot
        self._story_sandbox_live[novel_id] = {
            "novel_id": novel_id, "chapter": chapter, "branch_id": branch_id,
            "mode": SandboxLiveMode.REWRITE, "instruction": "", "events": [],
        }
        self._story_sandbox_tasks[novel_id] = asyncio.create_task(_run())

    async def retry_story_sandbox_derive(
        self, chapter: int, *, branch_id: str = LEGACY_BRANCH_ID,
    ) -> None:
        """Retries the most recent derive failure: reuses cached prose when available."""
        if self.is_story_sandbox_busy():
            raise RuntimeError("有任务运行中，无法重试")
        novel_id = active_novel_id()
        cached = self._story_sandbox_derive_retry_cache.get((novel_id, chapter, branch_id))
        if cached is None:
            raise RuntimeError("没有可重试的推演失败记录，请重新输入指令")

        from engine.story_sandbox.graph import WriteTurn

        async def _cached_write_turn(_system: str, _packet: str) -> str:
            return cast(str, cached["final_text"])

        override = cast(WriteTurn, _cached_write_turn) if cached["final_text"] is not None else None
        if cached["mode"] == "turn":
            await self.start_story_sandbox_turn(
                chapter, cached["instruction"], branch_id=branch_id,
                submitted_directions=cached["submitted_directions"],
                _write_turn_override=override,
            )
        else:
            await self.start_story_sandbox_rewrite(
                chapter, cached["feedback"], branch_id=branch_id,
                _write_turn_override=override,
            )

    async def start_story_sandbox_selection_rewrite(
        self, chapter: int, original_text: str, anchor_offset: int, feedback: str,
        round_id: str | None = None, *, branch_id: str = LEGACY_BRANCH_ID,
    ) -> None:
        """Rewrite just a director-selected fragment of one sandbox round's prose (round_id when
        given, else the chapter's latest round) -- a lightweight, non-streaming text-polish patch:
        no character/scene-state re-derivation, no event-log/profile-mutation/suggestions re-roll,
        since the selection is understood to reword existing content rather than change what
        happens. Reuses the same busy-guard as every other story_sandbox_* flow -- round_id exists
        so the frontend can queue a request made while busy and fire it once this clears, still
        landing on the round the user actually selected rather than whatever is `turns[-1]` by
        then (see rewrite_selection's docstring)."""
        if self.is_story_sandbox_busy():
            raise RuntimeError("有任务运行中，无法开始重写")

        from domain.token_usage import extract_usage
        from engine.execution.prose_style import build_active_prose_style_card
        from engine.modes.author_loop_skill_prefs import bind_node_llm, load_dialogue_prefs
        from engine.story_sandbox.graph import rewrite_selection
        from engine.story_sandbox.state import SandboxLiveMode
        from langchain_core.messages import HumanMessage, SystemMessage
        from llm.factory import get_cloud_llm
        from llm.prompt_logger import PromptLogger

        from api.services.token_accountant import TokenAccountant

        llm = get_cloud_llm()
        sandbox_llm_params = load_dialogue_prefs().get("sandbox_llm_params", {})
        bound_llm = bind_node_llm(llm, "selection_rewrite", sandbox_llm_params)
        model = _model_name(bound_llm, "cloud")
        novel_id = active_novel_id()
        word_guard = self._story_sandbox_word_guard(novel_id, chapter, branch_id)
        style = build_active_prose_style_card()
        prompt_logger = PromptLogger(chapter)

        accountant = TokenAccountant(
            novel_id=novel_id, subsystem="story_sandbox", key=str(chapter),
            model=str(getattr(llm, "model", "") or getattr(llm, "model_name", "") or "cloud"),
        )

        async def _call_llm(system: str, user: str) -> str:
            t0 = time.monotonic()
            resp = await bound_llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
            content = resp.content if isinstance(resp.content, str) else str(resp.content)
            tin, tout, tcached = extract_usage(resp)
            prompt_logger.log_llm_call(
                step=0, agent="story_sandbox_selection_rewrite", model=model,
                system=system, user=user, response=content,
                tokens_in=tin, tokens_out=tout, tokens_cached=tcached,
                duration_s=time.monotonic() - t0,
            )
            await accountant.record(tin, tout, tcached, model=model)
            return content.strip()

        # No word_guard restore dance here, unlike the whole-round rewrite: there's no
        # per-fragment snapshot to roll back to, and the new fragment's words getting record()ed
        # without subtracting the old fragment's is an acceptable, self-healing drift (the sliding
        # window naturally evicts stale content) -- see the design spec's word_guard section.
        guard_text_for, short_field_prompt_logger = self._make_guard_text(
            chapter=chapter, word_guard=word_guard, accountant=accountant,
            sandbox_llm_params=sandbox_llm_params,
        )

        async def _run() -> None:
            with use_novel(novel_id):
                try:
                    new_prose = await rewrite_selection(
                        novel_id, chapter, original_text, anchor_offset, feedback,
                        call_llm=_call_llm, guard_text=guard_text_for("selection_rewrite"),
                        style_card=style, round_id=round_id, branch_id=branch_id,
                    )
                    await self._emit_sandbox({
                        "type": "story_sandbox_selection_rewrite_done", "content": new_prose,
                        "round_id": round_id,
                    })
                except ValueError as exc:
                    await self._emit_sandbox({
                        "type": "story_sandbox_selection_rewrite_error", "error": str(exc),
                        "round_id": round_id,
                    })
                except Exception as exc:  # noqa: BLE001
                    logger.exception("[story_sandbox] selection rewrite failed")
                    await self._emit_sandbox({
                        "type": "story_sandbox_selection_rewrite_error", "error": str(exc),
                        "round_id": round_id,
                    })
                finally:
                    prompt_logger.close()
                    short_field_prompt_logger.close()
                    self._story_sandbox_tasks.pop(novel_id, None)
                    self._story_sandbox_live.pop(novel_id, None)

        self._story_sandbox_live[novel_id] = {
            "novel_id": novel_id, "chapter": chapter, "branch_id": branch_id,
            "mode": SandboxLiveMode.SELECTION_REWRITE, "instruction": original_text, "events": [],
        }
        await self._emit_sandbox({
            "type": "story_sandbox_selection_rewrite_start", "round_id": round_id, "novel_id": novel_id,
        })
        self._story_sandbox_tasks[novel_id] = asyncio.create_task(_run())

    async def story_sandbox_history(
        self, chapter: int, novel_id: str | None = None, *, branch_id: str = LEGACY_BRANCH_ID,
    ) -> dict:
        """Return this chapter's full round history -- each with its own prose/
        character_states/suggestions snapshot -- so the frontend can reconstruct the identical
        three-segment timeline for every past turn, not just the latest. live_round additionally
        exposes the currently in-flight round's already-broadcast event sequence (None when
        nothing is in flight for this exact (novel_id, chapter, branch_id), or a different one
        is) -- lets a remounted frontend replay it through reduceStorySandboxEvent instead of
        losing it."""
        from engine.story_sandbox.graph import peek_state

        nid = novel_id or active_novel_id()
        state = await peek_state(nid, chapter, branch_id=branch_id)
        live = self._story_sandbox_live.get(nid)
        live_round = None
        if (
            live is not None and live["chapter"] == chapter
            and live["branch_id"] == branch_id
        ):
            live_round = {
                "mode": live["mode"], "instruction": live["instruction"], "events": live["events"],
            }
        return {
            "rounds": state.get("turns") or [],
            "active_cast": sorted((state.get("active_cast") or {}).keys()),
            "live_round": live_round,
        }

    async def create_story_sandbox_branch(
        self, chapter: int, name: str | None = None, source_branch_id: str | None = None,
    ) -> dict:
        """Creates a new story line. When source_branch_id is given, forks the new branch from
        that branch's current state (checkpoint/turns + event-log + vector-memory), with fresh
        ids for the copied memory entries so the two branches' later independent rewrites never
        collide (see graph.fork_branch's docstring). Without source_branch_id, creates a blank
        branch (the zero-branches bootstrap case). Refuses while a turn is in progress, same
        busy-guard rule as start_story_sandbox_turn/delete_story_sandbox_branch."""
        if self.is_story_sandbox_busy():
            raise RuntimeError("上一轮沙盒回合还在进行，请稍候")
        from engine.story_sandbox import branches as sandbox_branches

        record = sandbox_branches.create_branch(chapter, name)
        if source_branch_id:
            from engine.memory_recall.event_log import copy_entries_for_branch
            from engine.story_sandbox.graph import fork_branch
            from repositories import get_sandbox_vector_memory_repo

            novel_id = active_novel_id()
            id_remap = await fork_branch(novel_id, chapter, source_branch_id, record["id"])
            if id_remap:
                await copy_entries_for_branch(chapter, record["id"], id_remap)
                await get_sandbox_vector_memory_repo().copy_branch(
                    chapter, source_branch_id, record["id"], id_remap,
                )
        return record

    async def delete_story_sandbox_branch(self, chapter: int, branch_id: str) -> dict:
        """Deletes one story line: wipes its checkpoint thread + its own event_log/vector-memory
        entries (reset_chapter, the same primitive the old whole-chapter reset used, now scoped
        to a single branch), then removes it from the branch registry. Refuses while a turn is
        in progress, same busy-guard rule as start_story_sandbox_turn. Returns the branch record
        the caller should switch to (delete_branch auto-creates a replacement if this was the
        chapter's last branch). Does NOT touch story_sandbox's token-ledger cell for this
        chapter -- cost accounting stays chapter-scoped, shared across that chapter's branches,
        deliberately not split per-branch (branches are a narrative concept, not a cost-tracking
        one); the old whole-chapter reset used to zero that cell, but doing so on a single
        branch's deletion would incorrectly wipe cost attributable to its still-live siblings."""
        if self.is_story_sandbox_busy():
            raise RuntimeError("上一轮沙盒回合还在进行，请稍候")
        from engine.story_sandbox import branches as sandbox_branches
        from engine.story_sandbox.graph import reset_chapter

        novel_id = active_novel_id()
        await reset_chapter(novel_id, chapter, branch_id=branch_id)
        self._story_sandbox_word_guards.pop((novel_id, chapter, branch_id), None)
        self._story_sandbox_last_round_word_guard_snapshot.pop((novel_id, chapter, branch_id), None)
        return sandbox_branches.delete_branch(chapter, branch_id)

    async def reset_story_sandbox_branch(self, chapter: int, branch_id: str) -> dict:
        """Clears one story line's content in place: wipes its checkpoint thread + its own
        event_log/vector-memory entries (reset_chapter, same primitive delete_story_sandbox_branch
        uses), but keeps the branch's registry record (id/name/created_at) instead of removing it --
        only updated_at is bumped via touch_branch. Refuses while a turn is in progress, same
        busy-guard rule as delete_story_sandbox_branch. Does NOT touch story_sandbox's token-ledger
        cell for this chapter, for the same reason delete doesn't (see delete_story_sandbox_branch's
        docstring: cost accounting is chapter-scoped, shared across branches)."""
        if self.is_story_sandbox_busy():
            raise RuntimeError("上一轮沙盒回合还在进行，请稍候")
        from engine.story_sandbox import branches as sandbox_branches
        from engine.story_sandbox.graph import reset_chapter

        novel_id = active_novel_id()
        await reset_chapter(novel_id, chapter, branch_id=branch_id)
        self._story_sandbox_word_guards.pop((novel_id, chapter, branch_id), None)
        self._story_sandbox_last_round_word_guard_snapshot.pop((novel_id, chapter, branch_id), None)
        sandbox_branches.touch_branch(chapter, branch_id)
        return sandbox_branches.get_branch(chapter, branch_id)

    async def regenerate_story_sandbox_suggestions(
        self, chapter: int, *, hint: str = "", branch_id: str = LEGACY_BRANCH_ID,
    ) -> None:
        """Re-roll the most recent round's suggestions: one plain LLM call, run as a
        background task (mirrors start_story_sandbox_turn/start_story_sandbox_rewrite) so a
        remounted frontend can recover an in-flight regenerate via story_sandbox_history's
        live_round, instead of losing track of it the way a directly-awaited request would.
        Refuses while a turn is in progress, same busy-guard rule as start_story_sandbox_turn."""
        if self.is_story_sandbox_busy():
            raise RuntimeError("有任务运行中，无法重新生成建议")

        from domain.token_usage import extract_usage
        from engine.modes.author_loop_skill_prefs import bind_node_llm, load_dialogue_prefs
        from engine.story_sandbox.graph import regenerate_suggestions
        from engine.story_sandbox.state import SandboxLiveMode
        from langchain_core.messages import HumanMessage, SystemMessage
        from langgraph.prebuilt import create_react_agent
        from llm.factory import get_cloud_llm

        from api.services.token_accountant import TokenAccountant

        llm = get_cloud_llm()
        novel_id = active_novel_id()
        word_guard = self._story_sandbox_word_guard(novel_id, chapter, branch_id)
        sandbox_llm_params = load_dialogue_prefs().get("sandbox_llm_params", {})
        bound_llm = bind_node_llm(llm, "suggest", sandbox_llm_params)
        suggest_model = _model_name(bound_llm, "cloud")
        accountant = TokenAccountant(
            novel_id=novel_id, subsystem="story_sandbox", key=str(chapter),
            model=str(getattr(llm, "model", "") or getattr(llm, "model_name", "") or "cloud"),
        )

        async def _call_llm(system: str, user: str) -> str:
            resp = await bound_llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
            content = resp.content if isinstance(resp.content, str) else str(resp.content)
            tin, tout, tcached = extract_usage(resp)
            await accountant.record(tin, tout, tcached, model=suggest_model)
            return content.strip()

        async def _run_skill_agent(system: str, user: str, tools: list) -> str:
            #One-shot, checkpointer-less agent -- this call never spans more than a single
            #regenerate request, so there's nothing to persist across turns (unlike
            #setup_chat's agent.py, which needs a checkpointer for its multi-turn thread).
            agent = create_react_agent(llm, tools=tools, prompt=system)
            result = await agent.ainvoke(
                {"messages": [HumanMessage(content=user)]}, config={"recursion_limit": 8},
            )
            content = result["messages"][-1].content
            return content if isinstance(content, str) else str(content)

        guard_text_for, short_field_prompt_logger = self._make_guard_text(
            chapter=chapter, word_guard=word_guard, accountant=accountant,
            sandbox_llm_params=sandbox_llm_params,
        )

        async def _run() -> None:
            with use_novel(novel_id):
                try:
                    suggestions = await regenerate_suggestions(
                        novel_id, chapter, _call_llm, hint=hint, run_skill_agent=_run_skill_agent,
                        guard_text=guard_text_for("suggest"), branch_id=branch_id,
                    )
                    await self._emit_sandbox({
                        "type": "story_sandbox_suggestions_regenerated", "options": suggestions,
                    })
                except Exception as exc:  # noqa: BLE001
                    logger.exception("[story_sandbox] suggestions regenerate failed")
                    await self._emit_sandbox({
                        "type": "story_sandbox_suggestions_regenerate_error", "error": str(exc),
                    })
                finally:
                    short_field_prompt_logger.close()
                    self._story_sandbox_tasks.pop(novel_id, None)
                    self._story_sandbox_live.pop(novel_id, None)

        self._story_sandbox_live[novel_id] = {
            "novel_id": novel_id, "chapter": chapter, "branch_id": branch_id,
            "mode": SandboxLiveMode.SUGGESTIONS_REGENERATE, "instruction": hint, "events": [],
        }
        #No streaming step precedes the terminal regenerated/error event for this one-shot call,
        #unlike a turn's first token or a rewrite's first delta -- without this, the frontend's
        #busy tracking (keyed off story_sandbox_* event prefixes) never sees an in-flight signal
        #and the novel-switch guard stays unlocked for the whole call.
        await self._emit_sandbox({"type": "story_sandbox_suggestions_regenerating", "novel_id": novel_id})
        self._story_sandbox_tasks[novel_id] = asyncio.create_task(_run())

    async def rewrite_story_sandbox_profile_mutation(
        self, chapter: int, feedback: str, *, branch_id: str = LEGACY_BRANCH_ID,
    ) -> None:
        """Re-derive profile/relationship mutation for the latest round only, steered by user
        feedback -- no prose re-generation. Runs as a background task (mirrors
        regenerate_story_sandbox_suggestions) so remounted frontends can recover via
        story_sandbox_history's live_round."""
        if self.is_story_sandbox_busy():
            raise RuntimeError("有任务运行中，无法重写档案突变")

        from domain.token_usage import extract_usage
        from engine.modes.author_loop_skill_prefs import bind_node_llm, load_dialogue_prefs
        from engine.story_sandbox.graph import rewrite_profile_mutation
        from engine.story_sandbox.state import SandboxLiveMode
        from langchain_core.messages import HumanMessage, SystemMessage
        from llm.factory import get_cloud_llm
        from llm.prompt_logger import PromptLogger

        from api.services.token_accountant import TokenAccountant

        llm = get_cloud_llm()
        novel_id = active_novel_id()
        word_guard = self._story_sandbox_word_guard(novel_id, chapter, branch_id)
        sandbox_llm_params = load_dialogue_prefs().get("sandbox_llm_params", {})
        bound_llm = bind_node_llm(llm, "profile_mutate", sandbox_llm_params)
        model = _model_name(bound_llm, "cloud")
        prompt_logger = PromptLogger(chapter)
        accountant = TokenAccountant(
            novel_id=novel_id, subsystem="story_sandbox", key=str(chapter),
            model=str(getattr(llm, "model", "") or getattr(llm, "model_name", "") or "cloud"),
        )

        async def _call_llm(system: str, user: str) -> str:
            t0 = time.monotonic()
            resp = await bound_llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
            content = resp.content if isinstance(resp.content, str) else str(resp.content)
            tin, tout, tcached = extract_usage(resp)
            prompt_logger.log_llm_call(
                step=0, agent="story_sandbox_profile_mutate_rewrite", model=model,
                system=system, user=user, response=content,
                tokens_in=tin, tokens_out=tout, tokens_cached=tcached,
                duration_s=time.monotonic() - t0,
            )
            await accountant.record(tin, tout, tcached, model=model)
            return content.strip()

        guard_text_for, short_field_prompt_logger = self._make_guard_text(
            chapter=chapter, word_guard=word_guard, accountant=accountant,
            sandbox_llm_params=sandbox_llm_params,
        )

        async def _run() -> None:
            with use_novel(novel_id):
                try:
                    profile_mutation, relationship_mutation, round_index = await rewrite_profile_mutation(
                        novel_id, chapter, feedback,
                        call_llm_profile_mutate=_call_llm,
                        guard_text=guard_text_for("profile_mutate"),
                        branch_id=branch_id,
                    )
                    await self._emit_sandbox({
                        "type": "story_sandbox_profile_mutation_rewrite_done",
                        "round_index": round_index,
                        "profile_mutation": profile_mutation,
                        "relationship_mutation": relationship_mutation,
                    })
                except ValueError as exc:
                    await self._emit_sandbox({
                        "type": "story_sandbox_profile_mutation_rewrite_error", "error": str(exc),
                    })
                except Exception as exc:  # noqa: BLE001
                    logger.exception("[story_sandbox] profile mutation rewrite failed")
                    await self._emit_sandbox({
                        "type": "story_sandbox_profile_mutation_rewrite_error", "error": str(exc),
                    })
                finally:
                    prompt_logger.close()
                    short_field_prompt_logger.close()
                    self._story_sandbox_tasks.pop(novel_id, None)
                    self._story_sandbox_live.pop(novel_id, None)

        self._story_sandbox_live[novel_id] = {
            "novel_id": novel_id, "chapter": chapter, "branch_id": branch_id,
            "mode": SandboxLiveMode.PROFILE_MUTATION_REWRITE, "instruction": feedback, "events": [],
        }
        await self._emit_sandbox({"type": "story_sandbox_profile_mutation_rewriting", "novel_id": novel_id})
        self._story_sandbox_tasks[novel_id] = asyncio.create_task(_run())

    async def setup_chat_history(self, novel_id: str | None = None) -> list[dict]:
        """Read history from the session message table for front-end playback - no agent is created, no checkpoint is touched.
        The table is missing and the old checkpoint has a history → Lazy backfill once (migrate)."""
        from engine.setup_chat.checkpoint_reader import backfill_if_missing
        from utils.paths import setup_chat_checkpoint_path, setup_chat_dir

        nid = novel_id or active_novel_id()
        with use_novel(nid):
            session_dir = setup_chat_session_dir()
            return await backfill_if_missing(
                session_dir,
                setup_chat_checkpoint_path(),
                nid,
                persist_dir=setup_chat_dir(),
            )

    def setup_chat_live_round(self, novel_id: str | None = None) -> dict | None:
        """Expose the in-flight round's already-broadcast event sequence (see
        _setup_chat_live/_emit_setup_chat) for GET /api/setup-chat/history to bolt onto its
        response, scoped to the requested novel (not necessarily the active pointer)."""
        nid = novel_id or active_novel_id()
        live = self._setup_chat_live.get(nid)
        if live is None:
            return None
        return {"instruction": live["instruction"], "events": live["events"]}

    async def stop_all_pipelines(self) -> None:
        """Clear the WS replay buffer (/api/chapters/{}/reset and app shutdown)."""
        self._gateway.clear_buffer()

    async def shutdown(self) -> None:
        """App shutdown (FastAPI lifespan call): clear WS replay buffer."""
        await self.stop_all_pipelines()
