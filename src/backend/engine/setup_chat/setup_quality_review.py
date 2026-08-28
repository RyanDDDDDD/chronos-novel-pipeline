"""Setup quality review: semantic gate for the world bible before persist."""
from __future__ import annotations

from typing import Any

from loguru import logger

from engine.author_loop.review.review_hook import ReviewContext, ReviewHook
from engine.author_loop.review.review_loader import REVIEW_HOOKS
from engine.author_loop.self_review import SelfReviewConfig, SelfReviewVerdict, run_self_review
from engine.setup.chat_summary import render_world_chat

SETUP_WORLD_HOOK_NAMES: tuple[str, ...] = (
    "setup_world_completeness",
    "setup_world_tension",
    "setup_world_distinctiveness",
)
PARTIAL_WORLD_HOOK_NAMES: tuple[str, ...] = (
    "setup_world_tension",
    "setup_world_distinctiveness",
)
_SETUP_REVIEW_THRESHOLD = 80
_SETUP_REVIEW_FLOOR = 60
_WORLD_REVIEW_HINT_PREFIX = "设定质量建议（已写入，可按需改进）："


def active_hooks(names: tuple[str, ...]) -> list[ReviewHook]:
    from engine.modes.author_loop_skill_prefs import load_dialogue_prefs

    disabled = set(load_dialogue_prefs().get("disabled_setup_review_hooks", []))
    return [h for h in REVIEW_HOOKS if h.name in names and h.name not in disabled]


async def _review_llm(system: str, user: str, **_k: Any) -> tuple[str, int, int]:
    from langchain_core.messages import HumanMessage, SystemMessage
    from llm.factory import get_cloud_llm

    from engine.modes.author_loop_skill_prefs import bind_node_llm, load_dialogue_prefs

    llm = bind_node_llm(
        get_cloud_llm(),
        "setup_quality_review",
        load_dialogue_prefs()["import_llm_params"],
    )
    resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    return text, 0, 0


def _review_config() -> SelfReviewConfig:
    return SelfReviewConfig(
        enabled=True,
        threshold=_SETUP_REVIEW_THRESHOLD,
        plugins={},
        scale=100,
    )


def _rewrite_dimensions(verdict: SelfReviewVerdict) -> list[tuple[str, int]]:
    if verdict.action != "rewrite":
        return []
    if verdict.composite < _SETUP_REVIEW_THRESHOLD:
        return list(verdict.scores)
    return [(name, score) for name, score in verdict.scores if score < _SETUP_REVIEW_FLOOR]


def _split_feedback(feedback: str, n: int) -> list[str]:
    text = feedback.strip()
    if n <= 1:
        return [text]
    parts = [p.strip() for p in text.split("\n") if p.strip()]
    if len(parts) == n:
        return parts
    return [text] * n


def format_agent_rubric(verdict: SelfReviewVerdict, hooks: list[ReviewHook]) -> str:
    """Rewrite dimensions only; 【display_name】\\nfeedback; no numeric scores."""
    dims = _rewrite_dimensions(verdict)
    if not dims:
        return ""
    by_name = {h.name: h for h in hooks}
    feedback_parts = _split_feedback(verdict.feedback, len(dims))
    blocks: list[str] = []
    for (name, _score), fb in zip(dims, feedback_parts, strict=False):
        hook = by_name.get(name)
        title = hook.display_name if hook else name
        blocks.append(f"【{title}】\n{fb}")
    return "\n\n".join(blocks)


async def run_world_review(
    bible: dict,
    *,
    novel_brief: str | None = None,
) -> SelfReviewVerdict:
    hooks = active_hooks(SETUP_WORLD_HOOK_NAMES)
    ctx = ReviewContext(
        beat_intent="",
        base_draft="",
        refined="",
        prev_beat_text=None,
        directive="",
        world_text=render_world_chat(bible),
        world_bible=bible,
        novel_brief=novel_brief,
    )
    verdict = await run_self_review(ctx, _review_llm, _review_config(), hooks=hooks)
    logger.info(
        "[setup-review:world] action={} composite={:.1f} scores={}",
        verdict.action,
        verdict.composite,
        verdict.scores,
    )
    return verdict


async def run_world_review_with_hooks(
    bible: dict,
    hook_names: tuple[str, ...],
    *,
    novel_brief: str | None = None,
) -> SelfReviewVerdict:
    hooks = active_hooks(hook_names)
    ctx = ReviewContext(
        beat_intent="",
        base_draft="",
        refined="",
        prev_beat_text=None,
        directive="",
        world_text=render_world_chat(bible),
        world_bible=bible,
        novel_brief=novel_brief,
    )
    return await run_self_review(ctx, _review_llm, _review_config(), hooks=hooks)


async def gate_world_bible(
    bible: dict,
    *,
    novel_brief: str | None = None,
    complete: bool | None = None,
) -> tuple[bool, str]:
    """Run setup world review hooks. Always returns ok=True — callers persist regardless;
    the second value is an advisory rubric when rewrite dimensions are flagged."""
    from engine.setup.world.validator import validate_world_bible

    if complete is None:
        complete = not validate_world_bible(bible)
    hook_names = SETUP_WORLD_HOOK_NAMES if complete else PARTIAL_WORLD_HOOK_NAMES
    hooks = active_hooks(hook_names)
    verdict = await run_world_review_with_hooks(bible, hook_names, novel_brief=novel_brief)
    if verdict.action == "accept":
        return True, ""
    rubric = format_agent_rubric(verdict, hooks)
    if not rubric:
        return True, ""
    return True, f"{_WORLD_REVIEW_HINT_PREFIX}\n\n{rubric}"


