"""Automatic, code-triggered character_timeline derivation -- replaces the chat-agent-driven
timeline-derivation skill's per-character present_choices loop. Chapter creation/edit tools
(tools.py::generate_one_chapter/patch_chapter/edit_character) schedule a cascade
here via schedule_timeline_cascade instead of relying on the agent to notice and rebuild.

Target discovery (missing_timeline_targets) is artifact-derived, not a persisted progress
table: "does this (chapter, name) coordinate have a snapshot yet" is recomputed fresh every
call, so a cleared-then-recreated chapter or a retried failure is picked up automatically
without any separate bookkeeping -- same self-healing philosophy as
world_pipeline.py::_chapter_timeline_done."""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


def _plot_chapters() -> list[int]:
    from repositories import get_plot_repo
    chapters = get_plot_repo().list_raw()
    return sorted(
        int(c["chapter"]) for c in chapters if isinstance(c, dict) and "chapter" in c
    )


def missing_timeline_targets(
    min_chapter: int, names: str | list[str] | None = None, *, max_chapter: int | None = None,
) -> list[tuple[int, str]]:
    """(chapter, name) pairs among plot chapters in [min_chapter, max_chapter or +inf] that
    don't yet have a timeline snapshot at that chapter. Sorted by chapter ascending (rolling
    derivation must proceed in chapter order); character order within a chapter is
    insignificant (parallel fan-out, see run_timeline_cascade). names: None -> every character
    in the chapter's roster; a bare string is normalized to a one-item list."""
    from context import character_timeline

    from engine.setup_chat.timeline_seed import _chapter_roster

    if isinstance(names, str):
        names = [names]
    out: list[tuple[int, str]] = []
    for chapter in _plot_chapters():
        if chapter < min_chapter or (max_chapter is not None and chapter > max_chapter):
            continue
        roster = _chapter_roster(chapter)
        if names is not None:
            roster = [n for n in roster if n in names]
        for name in roster:
            snaps = character_timeline.load_timeline(name)["snapshots"]
            if not any(s.get("chapter") == chapter for s in snaps):
                out.append((chapter, name))
    return out


_TIMELINE_AUTO_SYS = (
    "你是角色档案自动推演引擎。角色档案是角色逐章的状态演变增量(delta)——只产"
    "「这一章相对上一章变了什么」，不变的字段完全不要提及，引擎会据 delta 机械沿用旧值。\n"
    "固定字段集（只能用这些键）：sliders / gender / physique / race / identity_background / "
    "address_ref / self_ref / personality / verbal_tic / hobbies。\n"
    "滑块门控字段（address_ref、self_ref、personality、physique 神态）：仅当这一章滑块档位相比"
    "上一章有变化时才更新，否则不写。personality 变了但档位没变会被引擎打回。\n"
    "personality：一两句散文描述该角色此刻的性格/说话气质，自由撰写，别套固定类型名；严禁空字符串。\n"
    "事件驱动字段（gender、physique 器官异化）：按本章场景/剧情走，跟滑块无关。\n"
    "physique：值=各子字段的完整新描述，优先复用给定的「当前 physique 子字段」键（同一部位永远落"
    "同一键，保跨拍一致），确需新部位再新增子字段。\n"
    "sliders：每轴给 {level: 合法档位号, text: 贴合此刻的一句叙述}，level 从给定的档位号菜单里选。\n"
    "self_ref / address_ref 必须是 dict：self_ref 形如 {\"_default\": [...], \"对某对象\": [...]}；"
    "address_ref 形如 {\"对象名\": [...]}。\n"
    "只输出 JSON，形如 {\"sliders\": {...}, \"personality\": \"...\", ...}，不要输出任何 JSON 以外的文字。"
    "没有任何字段发生实质变化时输出空对象 {}。"
)

_MAX_ATTEMPTS = 3  # 首次 + 2 次重试


async def _call_llm(system: str, user: str) -> str:
    """Stateless, non-streaming, no session binding -- exactly get_cloud_llm's documented
    use case (background/utility calls outside any chat turn). Routed through the
    "timeline_derive" node like its sibling capability nodes (image_recognition/
    text_recognition/chat_identity/review/auto_build_setup) so the 对话 tab can configure
    its model/sampling params -- previously called get_cloud_llm() with no override at all."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from llm.factory import get_cloud_llm

    from engine.modes.author_loop_skill_prefs import bind_node_llm, load_dialogue_prefs

    llm = bind_node_llm(get_cloud_llm(), "timeline_derive", load_dialogue_prefs()["import_llm_params"])
    resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
    return str(resp.content)


async def _derive_one(chapter: int, name: str) -> dict | None:
    """build_timeline_seed -> render_timeline_seed as the user prompt -> LLM -> JSON parse ->
    tools._write_timeline_delta. Retries up to _MAX_ATTEMPTS - 1 times on parse failure or
    validation rejection; returns None (caller logs + aborts the cascade) once exhausted.

    cold_start (this character's first plotted appearance, no prior chapter has a delta for
    them) skips the LLM call entirely -- writes an empty delta so resolve_from folds straight
    onto the lore baseline (the character's default cast card), which is what the archive ends
    up being anyway. Only chapters where the character has already appeared before (rolling
    mode) go through the LLM to derive what actually changed."""
    from loguru import logger

    from engine.setup_chat.timeline_seed import build_timeline_seed, render_timeline_seed
    from engine.setup_chat.tools import _write_timeline_delta
    from engine.story_sandbox.llm_json import extract_json_dict

    seed = build_timeline_seed(name, chapter)

    if seed["mode"] == "cold_start":
        baseline = _write_timeline_delta(chapter, name, {})
        if isinstance(baseline, str):
            logger.error(
                "[timeline_auto] cold_start baseline write failed for chapter={} name={}: {}",
                chapter, name, baseline,
            )
            return None
        return dict(baseline["archive"])

    user_prompt = render_timeline_seed(seed)

    last_error = ""
    for _attempt in range(_MAX_ATTEMPTS):
        try:
            raw = await _call_llm(_TIMELINE_AUTO_SYS, user_prompt)
        except Exception as exc:  # noqa: BLE001 -- network/provider errors are retry candidates
            last_error = str(exc)
            continue
        parsed = extract_json_dict(raw)
        if parsed is None:
            last_error = f"unparseable JSON: {raw[:200]!r}"
            continue
        result = _write_timeline_delta(chapter, name, parsed)
        if isinstance(result, str):
            last_error = result
            continue
        return dict(result["archive"])

    logger.error(
        "[timeline_auto] derivation failed for chapter={} name={} after {} attempts: {}",
        chapter, name, _MAX_ATTEMPTS, last_error,
    )
    return None


async def _run_character(
    name: str,
    chapters: list[int],
    on_progress: Callable[[str, bool, str | None], Awaitable[None]] | None,
) -> None:
    """Walks one character's own missing chapters strictly in order (rolling derivation
    requires this character's earlier chapters resolved first -- but only THIS character's;
    it has no data dependency on any other character's progress). Stops at this character's
    own first hard failure -- does not affect other characters' independent walks, which keep
    running in run_timeline_cascade's fan-out regardless."""
    from loguru import logger

    for chapter in chapters:
        archive = await _derive_one(chapter, name)
        ok = archive is not None
        if on_progress is not None:
            error = None if ok else f"第{chapter}章「{name}」角色档案推演失败（已重试用尽）"
            await on_progress(name, ok, error)
        if not ok:
            logger.error(
                "[timeline_auto] {} 的级联在第 {} 章终止（该角色后续章节不再处理，其它角色不受影响）",
                name, chapter,
            )
            return


async def run_timeline_cascade(
    min_chapter: int,
    names: str | list[str] | None = None,
    *,
    max_chapter: int | None = None,
    on_progress: Callable[[str, bool, str | None], Awaitable[None]] | None = None,
) -> None:
    """Fan-out by CHARACTER, not by chapter: one lookup finds every missing (chapter, name)
    coordinate in range, grouped into one ascending chapter list per character, then every
    character's own walk runs as an independent concurrent task (asyncio.gather). Characters
    have no data dependency on each other, so a slow or failing character never blocks
    another's progress -- only within a single character's own chapters is order preserved
    (rolling derivation needs that character's own prior chapter resolved first).

    on_progress(name, ok, error), when given, is awaited once per (chapter, name) attempt --
    reserved for callers that want per-character progress hooks; the automatic background
    trigger passes None (log only)."""
    targets = missing_timeline_targets(min_chapter, names, max_chapter=max_chapter)

    by_name: dict[str, list[int]] = {}
    for chapter, name in targets:
        by_name.setdefault(name, []).append(chapter)

    await asyncio.gather(*(
        _run_character(name, chapters, on_progress) for name, chapters in by_name.items()
    ))


def _render_cascade_summary(results: list[tuple[str, bool, str | None]]) -> str:
    """Structured facts fed to the chat agent, mirroring
    skeleton_background_review._render_background_summary's philosophy --
    not user-facing prose, the triggered turn's own LLM call composes the actual reply."""
    names = sorted({name for name, ok, _error in results if ok})
    failures = [error for _name, ok, error in results if not ok and error]
    lines = []
    if names:
        lines.append(f"已为角色 {'、'.join(names)} 重新推演档案。")
    lines.extend(failures)
    return "\n".join(lines)


async def _run_cascade_and_notify(
    min_chapter: int, names: list[str] | None, novel_id: str, *, notify_chat: bool = True,
) -> None:
    """Wraps run_timeline_cascade with novel pinning + a completion notification --
    kept separate from run_timeline_cascade itself so its existing fan-out/ordering
    tests stay untouched; this is purely an outer layer. Pins novel_id the same way
    skeleton_background_review._run_chapter_review_fix does and for the same reason:
    this runs on SCHEDULER's own background loop task, unrelated to whichever
    request's context originally called schedule_timeline_cascade."""
    from utils.paths import use_novel

    results: list[tuple[str, bool, str | None]] = []

    async def _collect(name: str, ok: bool, error: str | None) -> None:
        results.append((name, ok, error))

    with use_novel(novel_id):
        await run_timeline_cascade(min_chapter, names, on_progress=_collect)

    await _broadcast_cascade_event(novel_id, "timeline_cascade_done")

    if not results or not notify_chat:
        return

    summary = _render_cascade_summary(results)
    from api.routes import _hub_instance

    await _hub_instance().trigger_system_notice_turn(novel_id, summary)


@dataclass
class _CascadePendingScope:
    names: set[str] | None = None
    min_chapter: int | None = None
    # OR-merged: a manual-edit call (notify_chat=False) coalescing into a batch that also
    # contains a chat-triggered call (notify_chat=True, the default) must still notify --
    # the chat side has something to report even if the manual side doesn't.
    notify_chat: bool = False


_CASCADE_PENDING: dict[str, _CascadePendingScope] = {}


def _merge_cascade_scope(
    novel_id: str, min_chapter: int, names: list[str] | None, *, notify_chat: bool = True,
) -> None:
    scope = _CASCADE_PENDING.setdefault(novel_id, _CascadePendingScope())
    scope.min_chapter = min_chapter if scope.min_chapter is None else min(scope.min_chapter, min_chapter)
    scope.notify_chat = scope.notify_chat or notify_chat
    if names is None:
        scope.names = None
    elif scope.names is not None:
        scope.names = set(scope.names) | set(names)
    else:
        scope.names = set(names)


async def _broadcast_cascade_event(novel_id: str, event_type: str) -> None:
    from api.routes import _hub_instance
    await _hub_instance().broadcast({"type": event_type, "novel_id": novel_id})


async def _settle_cascade(novel_id: str) -> None:
    """Dispatched (via SCHEDULER, dedup'd per novel) once per burst of schedule_timeline_cascade
    calls: cancels whatever cascade run is currently active for this novel (if any), then
    starts a fresh one covering the merged pending scope. Only one _settle_cascade per novel
    can ever be inflight at a time (SCHEDULER's own dedup on the settle job's name), so this
    function's own body doesn't need a lock."""
    from api.services.scheduler import SCHEDULER

    scope = _CASCADE_PENDING.pop(novel_id, _CascadePendingScope())

    run_name = f"timeline-cascade-run:{novel_id}"
    old_task = SCHEDULER.cancel_once(run_name)
    if old_task is not None:
        with contextlib.suppress(asyncio.CancelledError):
            await old_task
        await _broadcast_cascade_event(novel_id, "timeline_cascade_restarted")
    else:
        await _broadcast_cascade_event(novel_id, "timeline_cascade_started")

    names = sorted(scope.names) if scope.names is not None else None
    min_chapter = scope.min_chapter if scope.min_chapter is not None else 1
    notify_chat = scope.notify_chat
    SCHEDULER.schedule_once(
        run_name, 0.0,
        lambda: _run_cascade_and_notify(min_chapter, names, novel_id, notify_chat=notify_chat),
        dedup=True,
        on_timeout=lambda: _on_cascade_timeout(novel_id),
    )


async def _on_cascade_timeout(novel_id: str) -> None:
    await _broadcast_cascade_event(novel_id, "timeline_cascade_done")


def is_cascade_active(novel_id: str) -> bool:
    """GET /api/novels/status snapshot uses this -- True iff a cascade run is currently
    inflight for this novel (not counting a settle job still merging/deciding)."""
    from api.services.scheduler import SCHEDULER
    return SCHEDULER.has_active_once(f"timeline-cascade-run:{novel_id}")


def schedule_timeline_cascade(
    min_chapter: int, names: str | list[str] | None = None, *, notify_chat: bool = True,
) -> None:
    """Automatic-trigger entry point: merges this request's scope into the novel's pending
    scope, then dispatches (dedup'd per novel) a "settle" job that actually cancels any
    running cascade and restarts one covering everything accumulated so far. Several rapid
    edits before the settle job gets a chance to run all land in the same merged scope --
    _merge_cascade_scope runs synchronously here, before the dedup check, so nothing is lost
    even when the settle dispatch itself gets deduped away. notify_chat=False (manual cast-page
    edits) only suppresses the chat notice for this call's contribution -- see
    _CascadePendingScope.notify_chat for the OR-merge semantics when it coalesces with a
    chat-triggered call."""
    from api.services.scheduler import SCHEDULER
    from utils.paths import active_novel_id

    if isinstance(names, str):
        names = [names]
    novel_id = active_novel_id()
    _merge_cascade_scope(novel_id, min_chapter, names, notify_chat=notify_chat)
    SCHEDULER.schedule_once(
        f"timeline-cascade-settle:{novel_id}", 0.0, lambda: _settle_cascade(novel_id), dedup=True,
    )
