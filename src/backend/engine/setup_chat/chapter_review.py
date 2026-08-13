"""Chapter-level skeleton review: once every stage in a chapter has written
beats, run review hooks in parallel and render a combined report.

- Transition axis: review adjacent stage pairs (prev+cur).
- Per-stage axis: review each stage on its own (no prev), so stage1 is covered.

Called from tools.py::write_chapter_skeleton after a successful save so the
agent no longer has to remember to call a separate review tool.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from engine.author_loop.review.review_hook import ReviewContext, ReviewHook
from engine.author_loop.review.review_loader import REVIEW_HOOKS
from engine.author_loop.self_review import SelfReviewConfig, SelfReviewVerdict, run_self_review

# Add a new transition-review axis (needs both prev+cur) by dropping a new
# hooks/review/<name>/hook.py plugin and appending its name here --
# run_chapter_transition_review itself never needs to change.
TRANSITION_HOOK_NAMES: tuple[str, ...] = ("coherence",)

# Add a new per-stage axis (only needs the stage's own text, e.g. style) the
# same way -- run_chapter_stage_review never needs to change either.
STAGE_HOOK_NAMES: tuple[str, ...] = ("style",)


def _active_hooks(names: tuple[str, ...]) -> list[ReviewHook]:
    """Buildtime axis (skeleton-expansion) -- toggled independently from the
    runtime axis (stage_review.py) even for a hook name shared by both, e.g.
    "style"."""
    from engine.modes.author_loop_skill_prefs import load_dialogue_prefs

    disabled = set(load_dialogue_prefs().get("disabled_buildtime_review_hooks", []))
    return [h for h in REVIEW_HOOKS if h.name in names and h.name not in disabled]


def stage_beats_text(stage: dict) -> str:
    """Join a stage's beat texts in order (the comparison basis for review;
    missing/non-list beats -> '')."""
    beats = stage.get("beats")
    if not isinstance(beats, list):
        return ""
    texts: list[str] = []
    for b in beats:
        if not isinstance(b, dict):
            continue
        s = str(b.get("text") or "").strip()
        if s:
            texts.append(s)
    return "\n\n".join(texts)


def chapter_skeleton_complete(stages: list[dict]) -> bool:
    """True iff every stage in the chapter already has non-empty beat text."""
    return bool(stages) and all(stage_beats_text(s) for s in stages)


_SKELETON_REVIEWED_KEY = "skeleton_reviewed"


def chapter_skeleton_reviewed(chapter: int) -> bool:
    """True when the agent has acknowledged post-review fixes (is_reviewed=True on a save)."""
    from repositories import get_plot_repo

    ch = _chapter_dict(get_plot_repo().list_raw(), chapter)
    return bool(ch and ch.get(_SKELETON_REVIEWED_KEY))


def set_chapter_skeleton_reviewed(chapter: int, reviewed: bool) -> None:
    from repositories import get_plot_repo

    chapters = get_plot_repo().list_raw()
    ch = _chapter_dict(chapters, chapter)
    if ch is None:
        return
    if reviewed:
        ch[_SKELETON_REVIEWED_KEY] = True
    else:
        ch.pop(_SKELETON_REVIEWED_KEY, None)
    get_plot_repo().save_all(chapters)


def _chapter_dict(chapters: list, chapter: int) -> dict | None:
    return next(
        (c for c in chapters if isinstance(c, dict) and c.get("chapter") == chapter),
        None,
    )


async def maybe_schedule_skeleton_chapter_review(
    chapter: int,
    stages: list[dict],
    *,
    is_reviewed: bool,
    invalidate_reviewed: bool = False,
) -> None:
    """Gate full-chapter background transition/style review after skeleton edits.

    is_reviewed=True: agent is applying the one post-review fix — mark the chapter reviewed
    and never schedule again until invalidate_reviewed clears the flag (full re-expansion).
    """
    if is_reviewed:
        set_chapter_skeleton_reviewed(chapter, True)
        return

    if invalidate_reviewed:
        set_chapter_skeleton_reviewed(chapter, False)

    if chapter_skeleton_reviewed(chapter):
        return

    if not chapter_skeleton_complete(stages):
        return

    from utils.paths import active_novel_id

    from engine.setup_chat.skeleton_background_review import (
        mark_review_scheduled,
        schedule_chapter_review_fix,
    )

    novel_id = active_novel_id()
    await mark_review_scheduled(novel_id, chapter)
    schedule_chapter_review_fix(chapter)


async def _review_llm(system: str, user: str, **_k: Any) -> tuple[str, int, int]:
    from langchain_core.messages import HumanMessage, SystemMessage
    from llm.factory import get_cloud_llm

    from engine.modes.author_loop_skill_prefs import bind_node_llm, load_dialogue_prefs

    llm = bind_node_llm(get_cloud_llm(), "review", load_dialogue_prefs()["import_llm_params"])
    resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    return text, 0, 0


@dataclass
class TransitionReview:
    from_stage: int
    to_stage: int
    verdict: SelfReviewVerdict


@dataclass
class StageReview:
    stage_num: int
    verdict: SelfReviewVerdict


async def _review_ctx(
    hooks: list[ReviewHook], *, refined: str, prev_beat_text: str | None,
    beats: list[dict] | None = None,
) -> SelfReviewVerdict:
    ctx = ReviewContext(
        beat_intent="",
        base_draft="",
        refined=refined,
        prev_beat_text=prev_beat_text,
        directive="",
        beats=beats,
    )
    cfg = SelfReviewConfig(enabled=True, threshold=min(h.floor for h in hooks), plugins={})
    return await run_self_review(ctx, _review_llm, cfg, hooks=hooks)


async def run_chapter_transition_review(stages: list[dict]) -> list[TransitionReview]:
    """Review every adjacent stage-pair transition in parallel (map = one
    run_self_review call per transition, dispatched together via
    asyncio.gather). stages need not be pre-sorted."""
    hooks = _active_hooks(TRANSITION_HOOK_NAMES)
    ordered = sorted(stages, key=lambda s: s.get("stage_num", 0))
    if not hooks or len(ordered) < 2:
        return []
    pairs = list(zip(ordered, ordered[1:], strict=False))
    verdicts = await asyncio.gather(*(
        _review_ctx(
            hooks,
            refined=stage_beats_text(cur),
            prev_beat_text=stage_beats_text(prev),
        )
        for prev, cur in pairs
    ))
    return [
        TransitionReview(from_stage=prev["stage_num"], to_stage=cur["stage_num"], verdict=v)
        for (prev, cur), v in zip(pairs, verdicts, strict=True)
    ]


async def run_chapter_stage_review(stages: list[dict]) -> list[StageReview]:
    """Review every stage's own text in parallel (map = one run_self_review
    call per stage, dispatched together via asyncio.gather) -- unlike
    run_chapter_transition_review this covers the chapter's first stage too,
    since a per-stage check (e.g. style) has no "previous" to pair against."""
    hooks = _active_hooks(STAGE_HOOK_NAMES)
    ordered = sorted(stages, key=lambda s: s.get("stage_num", 0))
    if not hooks or not ordered:
        return []
    verdicts = await asyncio.gather(*(
        _review_ctx(hooks, refined=stage_beats_text(s), prev_beat_text=None, beats=s.get("beats"))
        for s in ordered
    ))
    return [
        StageReview(stage_num=s["stage_num"], verdict=v)
        for s, v in zip(ordered, verdicts, strict=True)
    ]


async def run_stage_local_review(
    stages: list[dict], stage_num: int,
) -> tuple[list[TransitionReview], list[StageReview]]:
    """Review just one stage plus its existing neighbors' transitions -- for
    patch_chapter's local edits (replace-with-beats/replace_beat/remove), which
    touch at most a couple of stages and don't warrant re-reviewing the whole
    chapter the way write_chapter_skeleton's first-time-complete trigger does.
    A neighbor that hasn't been expanded yet (no beats) is skipped -- nothing
    meaningful to compare its transition against."""
    by_num = {s.get("stage_num"): s for s in stages if isinstance(s, dict)}
    cur = by_num.get(stage_num)
    if cur is None or not stage_beats_text(cur):
        return [], []

    stage_hooks = _active_hooks(STAGE_HOOK_NAMES)
    transition_hooks = _active_hooks(TRANSITION_HOOK_NAMES)

    stage_reviews: list[StageReview] = []
    if stage_hooks:
        verdict = await _review_ctx(
            stage_hooks, refined=stage_beats_text(cur), prev_beat_text=None, beats=cur.get("beats"),
        )
        stage_reviews.append(StageReview(stage_num=stage_num, verdict=verdict))

    transition_reviews: list[TransitionReview] = []
    if transition_hooks:
        pairs: list[tuple[dict, dict]] = []
        prev_stage = by_num.get(stage_num - 1)
        if prev_stage is not None and stage_beats_text(prev_stage):
            pairs.append((prev_stage, cur))
        next_stage = by_num.get(stage_num + 1)
        if next_stage is not None and stage_beats_text(next_stage):
            pairs.append((cur, next_stage))
        if pairs:
            verdicts = await asyncio.gather(*(
                _review_ctx(transition_hooks, refined=stage_beats_text(c), prev_beat_text=stage_beats_text(p))
                for p, c in pairs
            ))
            transition_reviews = [
                TransitionReview(from_stage=p["stage_num"], to_stage=c["stage_num"], verdict=v)
                for (p, c), v in zip(pairs, verdicts, strict=True)
            ]
    return transition_reviews, stage_reviews


def render_chapter_review_report(transitions: list[TransitionReview], stages: list[StageReview]) -> str:
    """Render both transition and per-stage verdicts into one human-readable
    report; '' when there is nothing to report (single-stage chapter with no
    hooks loaded, or no hooks loaded at all)."""
    lines: list[str] = []
    for tr in transitions:
        v = tr.verdict
        if v.action == "accept":
            lines.append(f"stage{tr.from_stage}→stage{tr.to_stage}：过渡通过（{v.composite:.1f}/10）。")
        else:
            lines.append(
                f"stage{tr.from_stage}→stage{tr.to_stage}：过渡建议修改（{v.composite:.1f}/10）——{v.feedback}"
            )
    for sr in stages:
        v = sr.verdict
        if v.action == "accept":
            lines.append(f"stage{sr.stage_num}：文风通过（{v.composite:.1f}/10）。")
        else:
            lines.append(f"stage{sr.stage_num}：文风建议修改（{v.composite:.1f}/10）——{v.feedback}")
    if not lines:
        return ""
    return "\n".join(["【过渡/文风审查】", *lines])
