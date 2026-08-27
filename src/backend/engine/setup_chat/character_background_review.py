"""Background character quality review -- gate_character moved off the interactive
add_character/edit_character tool-call critical path.

Character create/edit tools persist immediately; the quality review runs here via
SCHEDULER (debounced per (novel, character name)) and, by default, notifies the chat agent
through trigger_system_notice_turn, whether the review accepted outright or a fix agent
had to patch the character (see docs/superpowers/specs/2026-08-09-setup-review-fix-agent-design.md).
The review/fix itself always runs regardless of caller; notify_chat only gates whether the
result is announced in the chat transcript (manual edits from the cast setup page pass
notify_chat=False -- see tools.py::_edit_character_core / _add_character_core)."""
from __future__ import annotations

import asyncio

from api.services.setup_chat_review_feedback import (
    REVIEW_FEEDBACK,
    ReviewFeedbackEntry,
    ReviewKey,
    ReviewStatus,
    handle_review_timeout,
)
from utils.paths import use_novel

from engine.setup_chat.world_tools import WORLD_DIMENSION_TOOLS

_ADD_WORLD_RACE_TOOL = next(t for t in WORLD_DIMENSION_TOOLS if t.name == "add_world_race")

_CHARACTER_FIX_PROMPT = (
    "你是「角色卡修复助手」，只负责根据质量评审反馈修改这一个角色的卡面。\n"
    "规则：\n"
    "1. 这是单次推理机会，没有后续轮次能看到工具调用结果再补调用——把需要的修改在这一轮里"
    "一次性规划好，除非反馈明确指出多处相互独立的问题，否则只调用一次 edit_character；\n"
    "2. edit_character 需要传入角色的完整字段（不是增量 patch），修改前先保留你已知道的角色现有信息，"
    "不要把没被反馈点名的字段改空或改乱；\n"
    "3. 只针对反馈里点名的问题动手，不做反馈之外的自由发挥；\n"
    "4. 若反馈里出现【种族设定】，先判断角色声明的种族是不是世界设定里已有种族的另一种措辞/拼写"
    "（比如「精灵」vs「精灵族」）——是的话调用 edit_character 把角色的 race 改成世界设定里的准确"
    "名称；如果确实是一个全新种族（世界设定里完全没有对应概念），调用 add_world_race 把这个种族"
    "补充进世界设定（name 用角色声明的种族名，desc 结合反馈里给的角色背景酌情撰写），角色卡本身"
    "不用改；\n"
    "5. 在调用工具的同一条回复里，用一两句中文简要说明你具体改了什么，不要复述反馈原文。"
)

# Process-global, ephemeral, per-novel: which character names currently have a background
# review job (this module) running -- mirrors skeleton_pipeline.py's _ACTIVE_REVIEWS shape,
# just keyed by character name instead of chapter number. Used to edge-trigger the
# character_review_started/_done WS broadcasts (only the first concurrent job announces
# "started", only the last one announces "done") so multiple characters created back-to-back
# collapse into a single toast instead of flickering it on/off.
_ACTIVE_CHARACTER_REVIEWS: dict[str, set[str]] = {}


def mark_review_active(novel_id: str, name: str) -> None:
    _ACTIVE_CHARACTER_REVIEWS.setdefault(novel_id, set()).add(name)


def clear_review_active(novel_id: str, name: str) -> None:
    s = _ACTIVE_CHARACTER_REVIEWS.get(novel_id)
    if s is not None:
        s.discard(name)


def any_review_active(novel_id: str) -> bool:
    return bool(_ACTIVE_CHARACTER_REVIEWS.get(novel_id))


async def _broadcast_character_review_event(novel_id: str, event_type: str) -> None:
    from api.routes import _hub_instance

    await _hub_instance().broadcast({"type": event_type, "novel_id": novel_id})


def schedule_character_quality_review(name: str, *, notify_chat: bool = True) -> None:
    """Schedule (coalesced per (novel, character name)) a background cast review reading
    the latest on-disk character. No _PendingReview-style merge state is needed here (unlike
    world_background_review.schedule_world_quality_review) -- the job always re-reads the
    roster fresh when it fires, so repeated calls for the same character just dedup onto the
    same SCHEDULER job name (including notify_chat: if a manual and a chat-triggered edit for
    the same character race within one debounce window, whichever call scheduled the job first
    wins its notify_chat value -- same tradeoff character_portrait_generation already accepts)."""
    from api.services.scheduler import SCHEDULER
    from utils.paths import active_novel_id

    novel_id = active_novel_id()
    if notify_chat:
        REVIEW_FEEDBACK.mark_pending(novel_id, ("character", name))
    SCHEDULER.schedule_once(
        f"character-fix:{novel_id}:{name}", 0.0,
        lambda: _run_character_review(novel_id, name, notify_chat=notify_chat), dedup=True,
        on_timeout=lambda: _on_character_review_timeout(novel_id, name, notify_chat=notify_chat),
    )


async def _on_character_review_timeout(novel_id: str, name: str, *, notify_chat: bool = True) -> None:
    async def _give_up() -> None:
        clear_review_active(novel_id, name)
        if not any_review_active(novel_id):
            await _broadcast_character_review_event(novel_id, "character_review_done")

    if not notify_chat:
        await _give_up()
        return

    def _retry() -> None:
        from api.services.scheduler import SCHEDULER

        SCHEDULER.schedule_once(
            f"character-fix:{novel_id}:{name}", 0.0,
            lambda: _run_character_review(novel_id, name, notify_chat=notify_chat),
            dedup=True,
            on_timeout=lambda: _on_character_review_timeout(novel_id, name, notify_chat=notify_chat),
        )

    await handle_review_timeout(
        novel_id, ("character", name), kind="character", label=f"角色「{name}」",
        retry=_retry, give_up=_give_up,
    )


async def run_character_fix_agent(name: str, rubric: str) -> str:
    from engine.setup_chat.fix_agent_runner import run_single_shot_fix_agent
    from engine.setup_chat.tools import edit_character

    return await run_single_shot_fix_agent(
        node_name="character_fix_agent",
        tools=[edit_character, _ADD_WORLD_RACE_TOOL],
        prompt=_CHARACTER_FIX_PROMPT,
        task_text=f"角色「{name}」的评审反馈如下，请按反馈修改：\n\n{rubric}",
    )


async def _run_character_review(novel_id: str, name: str, *, notify_chat: bool = True) -> None:
    from repositories import get_lore_repo

    from engine.setup.cast.cast_validator import race_mismatch_advisory
    from engine.setup_chat.setup_quality_review import (
        SETUP_CAST_HOOK_NAMES,
        active_hooks,
        format_agent_rubric,
        run_cast_review,
    )
    from engine.setup_chat.tools import _name_key

    key = ("character", name)

    is_first = not any_review_active(novel_id)
    mark_review_active(novel_id, name)

    try:
        if is_first:
            await _broadcast_character_review_event(novel_id, "character_review_started")

        entry: ReviewFeedbackEntry | None = None
        release_only = False

        with use_novel(novel_id):
            roster = get_lore_repo().list_raw()
            char = next((c for c in roster if isinstance(c, dict) and _name_key(c) == name), None)
            if char is None:
                release_only = True  # 审查排队期间角色被删了
            else:
                race_advisory = race_mismatch_advisory(char)
                verdict = await run_cast_review(char)
                needs_fix = verdict.action != "accept" or bool(race_advisory)
                if not needs_fix:
                    entry = ReviewFeedbackEntry(
                        "character", f"角色「{name}」", ReviewStatus.CLEAN, "")
                else:
                    rubric = format_agent_rubric(verdict, active_hooks(SETUP_CAST_HOOK_NAMES))
                    feedback = rubric
                    if race_advisory:
                        block = f"【种族设定】\n{race_advisory}"
                        feedback = f"{feedback}\n\n{block}" if feedback else block
                    try:
                        fix_report = await run_character_fix_agent(name, feedback)
                        if "已被修改" in fix_report:
                            release_only = True  # fix agent 输掉 CAS，静默放行
                        else:
                            body = f"「{name}」的角色卡审查发现以下问题：\n\n{feedback}\n\n已自动修复：{fix_report}"
                            entry = ReviewFeedbackEntry("character", f"角色「{name}」", ReviewStatus.RESOLVED, body)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001 - a crashed fix agent must still notify
                        body = f"「{name}」的角色卡审查发现以下问题：\n\n{feedback}\n\n（自动修复异常：{exc}）"
                        entry = ReviewFeedbackEntry("character", f"角色「{name}」", ReviewStatus.RESOLVED, body)

        if notify_chat:
            from api.routes import _hub_instance

            entries: list[tuple[ReviewKey, ReviewFeedbackEntry]] = (
                [] if (entry is None or release_only) else [(key, entry)]
            )
            await _hub_instance().report_review_done(novel_id, key, entries)
    finally:
        clear_review_active(novel_id, name)
        if not any_review_active(novel_id):
            await _broadcast_character_review_event(novel_id, "character_review_done")
