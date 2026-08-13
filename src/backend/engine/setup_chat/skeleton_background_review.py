"""Background review + auto-fix for a chapter's just-completed skeleton (spec:
docs/superpowers/specs/2026-08-04-skeleton-chapter-review-background-design.md).

write_chapter_skeleton used to run the transition/style review synchronously inside
the tool call once a chapter's beats were all written, forcing multi-round
generate-review-revise cycles into a single user-facing turn. This module moves that
off the critical path: schedule_chapter_review_fix is called once the chapter's
beats are complete, runs review + (if needed) one fix-agent pass in the background,
then always notifies the chat agent via a real triggered turn (message_hub.trigger_system_notice_turn)
regardless of outcome."""
from __future__ import annotations

import asyncio
import contextlib

from utils.paths import use_novel

from engine.setup_chat import skeleton_pipeline, skeleton_writer
from engine.setup_chat.chapter_review import (
    StageReview,
    TransitionReview,
    render_chapter_review_report,
    run_chapter_stage_review,
    run_chapter_transition_review,
)

_CHAPTER_SKELETON_FIX_PROMPT = (
    "你是「章节骨架修复助手」，只负责根据审查反馈重新生成本章里评审不通过的 stage。\n"
    "规则：\n"
    "1. 这是单次推理机会，没有后续轮次能看到工具调用结果再补调用——先判断每条反馈是否值得为此"
    "重新生成整段（明显琐碎、无关紧要的可以跳过），再把需要修的所有 stage 在这一轮里一次性规划好；\n"
    "2. 需要修的每个 stage 调用一次 regenerate_stage(stage_num, guidance)，guidance 用反馈原文"
    "或你归纳后的修改意见；有多个 stage 需要修时，把每个 stage 对应的调用都在这一轮里发出去；\n"
    "3. 在调用工具的同一条回复里，用一两句中文简要说明具体修了哪些 stage、大致改了什么，不要复述反馈原文。"
)


def _collect_failing_feedback(
    transitions: list[TransitionReview], stage_reviews: list[StageReview],
) -> dict[int, list[str]]:
    """Attributes a failing transition's feedback to its to_stage -- regenerating
    to_stage is the existing manual-revision fix for a bad transition. A stage that
    fails both a transition check and its own per-stage check accumulates both
    feedback strings."""
    failing: dict[int, list[str]] = {}
    for tr in transitions:
        if tr.verdict.action == "rewrite":
            failing.setdefault(tr.to_stage, []).append(tr.verdict.feedback)
    for sr in stage_reviews:
        if sr.verdict.action == "rewrite":
            failing.setdefault(sr.stage_num, []).append(sr.verdict.feedback)
    return failing


def _render_background_summary(
    transitions: list[TransitionReview],
    stage_reviews: list[StageReview],
    error: str | None,
    fix_report: str | None,
) -> str:
    """Structured facts fed to the chat agent -- not user-facing prose. The
    triggered turn's own LLM call composes the actual reply. The failing stages (if any)
    were already regenerated in-place by the background fix agent (regenerate_stage writes
    straight to the plot repo), so this must never read as an invitation for the chat agent
    to re-apply the same feedback itself via write_chapter_skeleton/patch_chapter."""
    report = render_chapter_review_report(transitions, stage_reviews) or "全部通过。"
    lines = [report]
    if fix_report:
        lines.append(f"已自动修复：{fix_report}")
    if error:
        lines.append(f"（异常：{error}）")
    if fix_report or error:
        lines.append(
            "以上是后台自动审查与修复的结果，仅供你了解情况；不需要、也不要据此再手动调用工具修改。"
        )
    return "\n".join(lines)


async def _broadcast_skeleton_event(novel_id: str, event_type: str, chapter: int | None = None) -> None:
    from api.routes import _hub_instance

    ev: dict = {"type": event_type, "novel_id": novel_id}
    if chapter is not None:
        ev["chapter"] = chapter
    await _hub_instance().broadcast(ev)


async def mark_review_scheduled(novel_id: str, chapter: int) -> None:
    """Mark a chapter as under review and notify the frontend when this starts the novel's
    first in-flight review job (subsequent chapters piggyback without a second started event)."""
    if not skeleton_pipeline.any_review_active(novel_id):
        await _broadcast_skeleton_event(novel_id, "skeleton_review_started")
    skeleton_pipeline.mark_review_active(novel_id, chapter)


async def cancel_active_review(novel_id: str, chapter: int, *, restarting: bool = True) -> None:
    """Called before plot/skeleton edits touch this chapter: cancel any in-flight review/auto-fix
    job and wait for it to stop so the caller's save_all() cannot race the job's.

    restarting=True (default): broadcast skeleton_review_restarted -- the caller will reschedule
    review after editing (write_chapter_skeleton / patch_chapter).

    restarting=False: clear the review-active flag and broadcast skeleton_review_done when this
    was the last active chapter -- used when the edit invalidates beats and no new review is
    scheduled (generate_one_chapter replace)."""
    from api.services.scheduler import SCHEDULER

    from engine.setup_chat import skeleton_pipeline

    task = SCHEDULER.cancel_once(f"skeleton-chapter-fix:{novel_id}:{chapter}")
    if task is not None:
        with contextlib.suppress(asyncio.CancelledError):
            await task
    if restarting:
        if task is not None:
            await _broadcast_skeleton_event(novel_id, "skeleton_review_restarted", chapter)
    elif skeleton_pipeline.is_review_active(novel_id, chapter):
        skeleton_pipeline.clear_review_active(novel_id, chapter)
        if not skeleton_pipeline.any_review_active(novel_id):
            await _broadcast_skeleton_event(novel_id, "skeleton_review_done")


def _regenerate_stage_tool_for(chapter: int):
    """Factory bound to one chapter -- the fix agent operates on exactly one chapter per run,
    so `chapter` doesn't need to be an LLM-filled tool parameter. Not registered on the
    interactive chat agent's tool list; only used inside run_chapter_skeleton_fix_agent."""
    from langchain_core.tools import StructuredTool

    from engine.setup_chat.tools import _fill_dialogue_drafts

    async def regenerate_stage(stage_num: int, guidance: str) -> str:
        from repositories import get_plot_repo

        chapters = get_plot_repo().list_raw()
        ch = next((c for c in chapters if c.get("chapter") == chapter), None)
        if ch is None:
            return f"第{chapter}章已被删除，无法重生成 stage {stage_num}。"
        result = await skeleton_writer.generate_stage_beats(
            chapter, stage_num, overview=guidance, is_revision=True)
        if isinstance(result, str):
            return f"stage {stage_num} 重生成失败：{result}"
        by_num = {s.get("stage_num"): s for s in ch["stages"]}
        await _fill_dialogue_drafts(chapter, by_num, {stage_num: result})
        by_num[stage_num]["beats"] = result
        get_plot_repo().save_all(chapters)
        return f"stage {stage_num} 已按反馈重新生成。"

    return StructuredTool.from_function(
        coroutine=regenerate_stage, name="regenerate_stage",
        description="按给定反馈重新生成指定 stage 的 beats。",
    )


async def run_chapter_skeleton_fix_agent(chapter: int, failing: dict[int, list[str]]) -> str:
    from engine.setup_chat.fix_agent_runner import run_single_shot_fix_agent

    task = "\n".join(f"stage {n}：{'; '.join(fb)}" for n, fb in failing.items())
    return await run_single_shot_fix_agent(
        node_name="chapter_skeleton_fix_agent",
        tools=[_regenerate_stage_tool_for(chapter)],
        prompt=_CHAPTER_SKELETON_FIX_PROMPT,
        task_text=f"第{chapter}章以下 stage 未通过审查：\n\n{task}",
    )


async def _run_chapter_review_fix(chapter: int, novel_id: str) -> None:
    """The background coroutine itself: one review pass -> (if needed) one fix-agent run --
    no re-review after the fix, since review only judges "needs fixing or not", not "is the
    fix good enough". A clean completion (not cancelled) clears _ACTIVE_REVIEWS and notifies;
    a cancellation (via cancel_active_review, above) leaves _ACTIVE_REVIEWS set (the chapter is
    about to be restarted, so from an outside observer's view it never stopped being "under
    review") and never reaches the code after the try/except -- CancelledError propagates
    straight through it."""
    await mark_review_scheduled(novel_id, chapter)

    from repositories import get_plot_repo

    error: str | None = None
    transitions: list[TransitionReview] = []
    stage_reviews: list[StageReview] = []
    fix_report: str | None = None
    try:
        with use_novel(novel_id):
            chapters = get_plot_repo().list_raw()
            ch = next((c for c in chapters if c.get("chapter") == chapter), None)
            if ch is None:
                error = "章节已被删除，审查中止。"
            else:
                all_stages = ch.get("stages") or []
                transitions, stage_reviews = await asyncio.gather(
                    run_chapter_transition_review(all_stages),
                    run_chapter_stage_review(all_stages),
                )
                failing = _collect_failing_feedback(transitions, stage_reviews)
                if failing:
                    fix_report = await run_chapter_skeleton_fix_agent(chapter, failing)
    except Exception as exc:  # noqa: BLE001 - background task must never leave the chapter locked
        error = f"后台审查异常：{exc}"

    skeleton_pipeline.clear_review_active(novel_id, chapter)
    if not skeleton_pipeline.any_review_active(novel_id):
        await _broadcast_skeleton_event(novel_id, "skeleton_review_done")

    summary = _render_background_summary(transitions, stage_reviews, error, fix_report)
    from api.routes import _hub_instance  # engine-layer callback into hub, see attachment_tool.py

    await _hub_instance().trigger_system_notice_turn(novel_id, summary)


def schedule_chapter_review_fix(chapter: int) -> None:
    """Called by write_chapter_skeleton once a chapter's beats are all complete.
    Dedup on (novel, chapter) so re-entering this function for the same chapter
    while a job is already queued/running is a no-op, mirroring
    timeline_auto.schedule_timeline_cascade."""
    from api.services.scheduler import SCHEDULER
    from utils.paths import active_novel_id

    novel_id = active_novel_id()
    name = f"skeleton-chapter-fix:{novel_id}:{chapter}"
    SCHEDULER.schedule_once(
        name, 0.0, lambda: _run_chapter_review_fix(chapter, novel_id), dedup=True,
        on_timeout=lambda: _on_chapter_review_timeout(novel_id, chapter),
    )


async def _on_chapter_review_timeout(novel_id: str, chapter: int) -> None:
    skeleton_pipeline.clear_review_active(novel_id, chapter)
    if not skeleton_pipeline.any_review_active(novel_id):
        await _broadcast_skeleton_event(novel_id, "skeleton_review_done")
