"""Background setup world quality review -- gate_world_bible moved off tool-call critical path.

World create/modify tools persist immediately; setup quality hooks run here via SCHEDULER
and notify the chat agent through trigger_system_notice_turn when advisory feedback exists."""
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass

from api.services.setup_chat_review_feedback import (
    REVIEW_FEEDBACK,
    ReviewFeedbackEntry,
    ReviewStatus,
    handle_review_timeout,
)
from utils.paths import use_novel


@dataclass
class _PendingReview:
    complete: bool | None = None
    novel_brief: str | None = None


_PENDING: dict[str, _PendingReview] = {}


def _merge_pending(
    novel_id: str,
    *,
    complete: bool | None,
    novel_brief: str | None,
    ) -> None:
    pending = _PENDING.setdefault(novel_id, _PendingReview())
    if complete is True:
        pending.complete = True
    elif pending.complete is None and complete is not None:
        pending.complete = complete
    if novel_brief:
        pending.novel_brief = novel_brief


async def _broadcast(novel_id: str, event_type: str) -> None:
    from api.routes import _hub_instance

    await _hub_instance().broadcast({"type": event_type, "novel_id": novel_id})


def _render_summary(review_hint: str, error: str | None) -> str:
    lines: list[str] = []
    if review_hint.strip():
        lines.append(review_hint.strip())
    if error:
        lines.append(f"（后台审查异常：{error}）")
    return "\n".join(lines)


_WORLD_FIX_PROMPT = (
    "你是「世界观修复助手」，只负责根据质量评审反馈修改世界观设定的相应维度。\n"
    "规则：\n"
    "1. 这是单次推理机会，没有后续轮次能看到工具调用结果再补调用——根据反馈判断需要改哪些维度"
    "（背景/基调/势力/地理/种族/力量体系/核心主题），把涉及的 set_world_*/refine_world_*/"
    "edit_world_* 工具在这一轮里一次性规划好并全部调用；\n"
    "2. 只改反馈点名的问题，不做反馈之外的自由发挥；\n"
    "3. 在调用工具的同一条回复里，用一两句中文简要说明你具体改了什么，不要复述反馈原文。"
)


async def run_world_fix_agent(rubric: str) -> str:
    from engine.setup_chat.fix_agent_runner import run_single_shot_fix_agent
    from engine.setup_chat.world_tools import WORLD_DIMENSION_TOOLS

    return await run_single_shot_fix_agent(
        node_name="world_fix_agent",
        tools=WORLD_DIMENSION_TOOLS,
        prompt=_WORLD_FIX_PROMPT,
        task_text=f"世界观评审反馈如下，请调用对应维度工具按反馈修改：\n\n{rubric}",
    )


async def _run_world_review(novel_id: str, params: _PendingReview) -> None:
    from repositories import get_world_repo

    from engine.setup_chat.setup_quality_review import gate_world_bible

    review_hint = ""
    error: str | None = None
    try:
        with use_novel(novel_id):
            bible = get_world_repo().get()
            if not isinstance(bible, dict) or not bible:
                from api.routes import _hub_instance

                await _hub_instance().report_review_done(novel_id, ("world",), [])
                return
            _ok, review_hint = await gate_world_bible(
                bible,
                complete=params.complete,
                novel_brief=params.novel_brief,
            )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - background task must never crash the scheduler
        error = str(exc)

    if novel_id in _PENDING:
        from api.services.scheduler import SCHEDULER

        SCHEDULER.schedule_once(
            f"world-review-settle:{novel_id}",
            0.0,
            lambda: _settle(novel_id),
            dedup=True,
        )
        return  # another run is coming; keep the ("world",) barrier unit marked

    await _broadcast(novel_id, "world_review_done")

    from api.routes import _hub_instance

    if error:
        entry = ReviewFeedbackEntry(
            "world", "世界观", ReviewStatus.RESOLVED,
            _render_summary("", error),
        )
    elif review_hint:
        try:
            fix_report = await run_world_fix_agent(review_hint)
            body = f"{review_hint}\n\n已自动修复：{fix_report}"
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a crashed fix agent must still notify
            body = _render_summary(review_hint, str(exc))
        entry = ReviewFeedbackEntry("world", "世界观", ReviewStatus.RESOLVED, body)
    else:
        entry = ReviewFeedbackEntry("world", "世界观", ReviewStatus.CLEAN, "")

    await _hub_instance().report_review_done(novel_id, ("world",), [(("world",), entry)])


async def _settle(novel_id: str) -> None:
    from api.services.scheduler import SCHEDULER

    params = _PENDING.pop(novel_id, _PendingReview())

    run_name = f"world-review-run:{novel_id}"
    old_task = SCHEDULER.cancel_once(run_name)
    if old_task is not None:
        with contextlib.suppress(asyncio.CancelledError):
            await old_task
        await _broadcast(novel_id, "world_review_restarted")
    else:
        await _broadcast(novel_id, "world_review_started")

    SCHEDULER.schedule_once(
        run_name, 0.0, lambda: _run_world_review(novel_id, params), dedup=True,
        on_timeout=lambda: _on_world_review_timeout(novel_id),
    )


async def _on_world_review_timeout(novel_id: str) -> None:
    def _retry() -> None:
        from api.services.scheduler import SCHEDULER

        SCHEDULER.schedule_once(
            f"world-review-run:{novel_id}",
            0.0,
            lambda: _run_world_review(novel_id, _PendingReview()),
            dedup=True,
            on_timeout=lambda: _on_world_review_timeout(novel_id),
        )

    async def _give_up() -> None:
        await _broadcast(novel_id, "world_review_done")

    await handle_review_timeout(
        novel_id, ("world",), kind="world", label="世界观",
        retry=_retry, give_up=_give_up,
    )


def schedule_world_quality_review(
    *,
    complete: bool | None = None,
    novel_brief: str | None = None,
) -> None:
    """Schedule (coalesced per novel) a background gate_world_bible on the latest on-disk bible."""
    from api.services.scheduler import SCHEDULER
    from utils.paths import active_novel_id

    novel_id = active_novel_id()
    REVIEW_FEEDBACK.mark_pending(novel_id, ("world",))
    _merge_pending(novel_id, complete=complete, novel_brief=novel_brief)
    SCHEDULER.schedule_once(
        f"world-review-settle:{novel_id}",
        0.0,
        lambda: _settle(novel_id),
        dedup=True,
    )


def is_world_review_active(novel_id: str) -> bool:
    from api.services.scheduler import SCHEDULER

    return SCHEDULER.has_active_once(f"world-review-run:{novel_id}")
