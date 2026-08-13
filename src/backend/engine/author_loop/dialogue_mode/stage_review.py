"""Stage-level review gate: run after author_prose and before the stage is
accepted as final. This is the runtime axis of the shared hooks/review/
plugin registry (see engine.author_loop.review.review_loader.REVIEW_HOOKS) --
concurrent map-reduce judging of the candidate prose against its skeleton
(fidelity + expansion_ratio + style), same machinery as
engine.author_loop.self_review.run_self_review already provides.

The buildtime axis (skeleton-expansion's coherence/style,
see engine.setup_chat.chapter_review.py) shares the same hook implementations
where applicable (e.g. "style") but each axis is toggled independently via its
own disabled-hooks config field -- disabling a hook here never affects the
other axis, and vice versa."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from engine.author_loop.review.review_hook import ReviewContext, ReviewHook
from engine.author_loop.review.review_loader import REVIEW_HOOKS
from engine.author_loop.self_review import SelfReviewConfig, run_self_review

CallLLM = Callable[..., Awaitable[tuple[str, int, int]]]

RUNTIME_HOOK_NAMES: tuple[str, ...] = ("fidelity", "expansion_ratio", "style")


def _active_runtime_hooks() -> list[ReviewHook]:
    from engine.modes.author_loop_skill_prefs import load_dialogue_prefs

    disabled = set(load_dialogue_prefs().get("disabled_runtime_review_hooks", []))
    return [h for h in REVIEW_HOOKS if h.name in RUNTIME_HOOK_NAMES and h.name not in disabled]


@dataclass
class ReviewResult:
    passed: bool
    notes: list[str] = field(default_factory=list)


async def review_candidate(*, skeleton_text: str, prose: str, call_llm: CallLLM) -> ReviewResult:
    """Run every currently-active runtime hook concurrently (map, via
    run_self_review) and combine their notes (reduce). No active hooks ->
    accept (empty-set invariant, same as the buildtime axis)."""
    hooks = _active_runtime_hooks()
    if not hooks:
        return ReviewResult(passed=True, notes=[])
    ctx = ReviewContext(
        beat_intent="", base_draft=skeleton_text, refined=prose, prev_beat_text=None, directive="",
    )
    cfg = SelfReviewConfig(enabled=True, threshold=min(h.floor for h in hooks), plugins={})
    verdict = await run_self_review(ctx, call_llm, cfg, hooks=hooks)
    if verdict.action == "accept":
        return ReviewResult(passed=True, notes=[])
    notes = [n for n in verdict.feedback.split("\n") if n.strip()]
    return ReviewResult(passed=False, notes=notes)


def render_review_feedback(result: ReviewResult) -> str:
    lines = ["【本 stage 审核未通过，需要修订】"] + [f"- {n}" for n in result.notes]
    lines.append("请针对以上问题修订，重新产出这个 stage 的完整正文（覆盖之前的版本，不是补丁式追加）。")
    return "\n".join(lines)
