"""Code-defined pipeline for skeleton-stage expansion within a chapter.

Migrates skeleton_stage off construction_plan.json (see
docs/superpowers/specs/2026-07-08-skeleton-expansion-code-pipeline-design.md) and adds
code-enforced gating for the sub-sequence skills/setup_chat_skills/skeleton-expansion/
skill.md previously only enforced via prose: a chapter-scoped "global direction" pass
once, then per-stage lens (3a) -> extensions (3b) -> write (3c), in that order.
Stage-to-stage order is not enforced (no technical dependency between stages, unlike
TIMELINE's rolling state).

Edit tools pass through ungated — see plan_runner.gate_tool_call. Dialogue design is
not a separate phase/tool at all anymore — it's folded into this pipeline's own 3b
extension menu (beat-dialogue-design skill) and written directly into beat text by
write_chapter_skeleton."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from engine.setup_chat.construction_plan import _stage_beats


class SkeletonPhase(StrEnum):
    DIRECTION = "direction"
    LENS = "lens"
    EXTENSIONS = "extensions"
    WRITE = "write"


_PHASE_TOOLS: dict[SkeletonPhase, str] = {
    SkeletonPhase.DIRECTION: "set_chapter_direction",
    SkeletonPhase.LENS: "set_stage_lens",
    SkeletonPhase.EXTENSIONS: "set_stage_extensions",
    SkeletonPhase.WRITE: "write_chapter_skeleton",
}
_TOOL_PHASE: dict[str, SkeletonPhase] = {tool: phase for phase, tool in _PHASE_TOOLS.items()}

_PHASE_TITLES: dict[SkeletonPhase, str] = {
    SkeletonPhase.DIRECTION: "本章整体方向",
    SkeletonPhase.LENS: "分镜(3a)",
    SkeletonPhase.EXTENSIONS: "情景拓展(3b)",
    SkeletonPhase.WRITE: "分拍写正文(3c)",
}

# Process-global, ephemeral: these choices have no natural on-disk form (pure
# in-conversation decisions), unlike world_pipeline's stages, which are all
# artifact-backed. Losing them on restart is harmless — the affected stage's 3a/3b
# must be redone, no data is corrupted (same trade-off plan_runner._PENDING_REPAIR
# already accepts for its own process-memory cache).
_DIRECTION_SET: set[int] = set()
_LENS_CHOSEN: dict[tuple[int, int], list[str]] = {}
_EXT_CHOSEN: dict[tuple[int, int], list[str]] = {}

_ACTIVE_CHAPTER: int | None = None


def active_chapter() -> int | None:
    return _ACTIVE_CHAPTER


def mark_chapter_active(chapter: int) -> None:
    """Record that `chapter` is the chapter currently undergoing skeleton expansion — set
    whenever any skeleton_pipeline-recognized tool call resolves a chapter number, and by
    read_skeleton_seed on a successful (non-empty) read. Only one chapter tracked at a time,
    matching the skill's own "one chapter at a time" discipline; a later call for a different
    chapter simply overwrites this."""
    global _ACTIVE_CHAPTER
    _ACTIVE_CHAPTER = chapter


def clear_chapter_active(chapter: int) -> None:
    """Called once `chapter`'s skeleton is fully written (chapter_skeleton_complete). No-op if
    `chapter` isn't the currently tracked one (e.g. the agent already moved on to another
    chapter mid-flight) — never clears a different chapter's marker."""
    global _ACTIVE_CHAPTER
    if _ACTIVE_CHAPTER == chapter:
        _ACTIVE_CHAPTER = None


def active_seed_injection() -> str | None:
    """Deterministic per-turn injection (pre_model_hook dispatch target, alongside — not instead
    of — build_plan_activation): while a chapter is actively undergoing skeleton expansion,
    rebuild and return its full grounding text (world + chapter archive + outline)
    every call, so it survives regardless of what the LLM chooses to call. None when no chapter
    is active, or the active chapter turns out to have no plot (edge case: marker set, then plot
    deleted mid-session)."""
    if _ACTIVE_CHAPTER is None:
        return None
    from engine.setup_chat.skeleton_seed import build_skeleton_seed, render_skeleton_seed

    seed = build_skeleton_seed(_ACTIVE_CHAPTER)
    if not seed.get("stages"):
        return None
    return f"【骨架扩写事实记忆·第{_ACTIVE_CHAPTER}章】\n{render_skeleton_seed(seed)}"


def set_chapter_direction(chapter: int, direction: str) -> None:
    _DIRECTION_SET.add(chapter)


def set_stage_lens(chapter: int, stage_num: int, angles: list[str]) -> None:
    _LENS_CHOSEN[(chapter, stage_num)] = list(angles)


def set_stage_extensions(chapter: int, stage_num: int, extensions: list[str]) -> None:
    _EXT_CHOSEN[(chapter, stage_num)] = list(extensions)


def clear_stage_markers(chapter: int, stage_num: int) -> None:
    """Called by the write_chapter_skeleton tool after a successful disk write —
    the lens/extensions markers' job is done; from here on "is this stage expanded"
    is answered by the real beats artifact (_is_expanded), same as
    derive_task_status already does for TaskKind.SKELETON_STAGE."""
    _LENS_CHOSEN.pop((chapter, stage_num), None)
    _EXT_CHOSEN.pop((chapter, stage_num), None)


def _is_expanded(chapter: int, stage_num: int) -> bool:
    """Live artifact check — same criterion derive_task_status already uses for
    TaskKind.SKELETON_STAGE."""
    return bool(_stage_beats(chapter, stage_num))


def chapter_fully_unexpanded(chapter: int) -> bool:
    """True when the chapter has plot stages but none of them has been expanded yet (no stage
    has beats). Kept as a readable special case of chapter_remaining_stage_nums (a chapter with
    zero progress at all) -- some call sites only care about that virgin/non-virgin distinction."""
    stage_nums = _chapter_stage_nums(chapter)
    return bool(stage_nums) and not any(_is_expanded(chapter, sn) for sn in stage_nums)


def chapter_remaining_stage_nums(chapter: int) -> list[int]:
    """Stage nums (chapter order) that don't have beats yet -- i.e. the stages a resume-capable
    auto_expand_skeleton run still needs to touch. Non-empty both for a virgin chapter (all
    stages remaining) and for one with partial manual progress (some stages already written) --
    single source of truth for auto_expand_skeleton's own scope, the tool_router routing-level
    narrowing, and the plan_runner.gate_tool_call execution-time backstop, so AUTO mode steers
    toward the one-shot tool regardless of whether it was switched on before or mid-chapter."""
    return [sn for sn in _chapter_stage_nums(chapter) if not _is_expanded(chapter, sn)]


def is_direction_set(chapter: int) -> bool:
    """Whether set_chapter_direction has already recorded a direction for this chapter (see
    _DIRECTION_SET) -- used by a resuming auto_expand_skeleton run to avoid clobbering a
    direction decided earlier (manually, or by an earlier partial auto run) with a freshly
    drafted one."""
    return chapter in _DIRECTION_SET


def _chapter_stage_nums(chapter: int) -> list[int]:
    from repositories import get_plot_repo

    chapters = get_plot_repo().list_raw()
    ch = next((c for c in chapters if isinstance(c, dict) and c.get("chapter") == chapter), None)
    if ch is None:
        return []
    return sorted(
        s["stage_num"] for s in (ch.get("stages") or [])
        if isinstance(s, dict) and isinstance(s.get("stage_num"), int)
    )


def _chapter_roster(chapter: int) -> list[str]:
    """Union of entity_index.scan_characters(description) hits across all of this chapter's
    plot stages, in stage order. [] when the chapter isn't in plot yet."""
    from repositories import get_plot_repo

    from engine.memory_recall.entity_index import scan_characters

    chapters = get_plot_repo().list_raw()
    ch = next((c for c in chapters if isinstance(c, dict) and c.get("chapter") == chapter), None)
    if ch is None:
        return []
    roster: list[str] = []
    for s in ch.get("stages") or []:
        for name in scan_characters(str(s.get("description") or "")):
            if name not in roster:
                roster.append(name)
    return roster


def _missing_timeline_for(chapter: int) -> list[str]:
    """Roster members (see _chapter_roster) whose timeline hasn't been derived for this
    chapter yet, per the same status check world_pipeline's own TIMELINE task uses
    (construction_plan.derive_task_status with a per-character `name` param — stricter
    than the aggregate any-character check plan_runner._chapter_timeline_done does for
    world_pipeline's own chapter-sequencing rule). [] when the roster is empty (vacuously
    satisfied) or every member's timeline is done."""
    from engine.setup_chat.construction_plan import TaskKind, derive_task_status

    return [
        name for name in _chapter_roster(chapter)
        if derive_task_status(
            {"kind": TaskKind.TIMELINE, "params": {"chapter": chapter, "name": name}}
        ) != "done"
    ]


@dataclass(frozen=True)
class Chain:
    chapter: int
    stage_num: int | None       # None only for the DIRECTION phase (chapter-scoped)
    target: SkeletonPhase
    missing: list[SkeletonPhase] = field(default_factory=list)
    missing_timeline_chars: list[str] = field(default_factory=list)
    batch_violation: str | None = None   # non-None -> reject regardless of `missing`

    @property
    def blocked(self) -> bool:
        return (
            bool(self.missing)
            or bool(self.missing_timeline_chars)
            or self.batch_violation is not None
        )


def _missing_for(chapter: int, stage_num: int | None, target: SkeletonPhase) -> list[SkeletonPhase]:
    missing: list[SkeletonPhase] = []
    if target in (SkeletonPhase.LENS, SkeletonPhase.EXTENSIONS, SkeletonPhase.WRITE):
        if chapter not in _DIRECTION_SET:
            missing.append(SkeletonPhase.DIRECTION)
    if target in (SkeletonPhase.EXTENSIONS, SkeletonPhase.WRITE) and stage_num is not None:
        if (chapter, stage_num) not in _LENS_CHOSEN:
            missing.append(SkeletonPhase.LENS)
    if target == SkeletonPhase.WRITE and stage_num is not None:
        if (chapter, stage_num) not in _EXT_CHOSEN:
            missing.append(SkeletonPhase.EXTENSIONS)
    return missing


def _resolve_write_chain(chapter: int, args: dict) -> Chain | None:
    stages = args.get("stages")
    if not isinstance(stages, list) or not stages:
        return None
    stage_nums: list[int] = []
    for s in stages:
        if not isinstance(s, dict):
            continue
        sn = s.get("stage_num")
        if isinstance(sn, int):
            stage_nums.append(sn)
    if not stage_nums:
        return None
    first_time = [sn for sn in stage_nums if not _is_expanded(chapter, sn)]
    if not first_time:
        # Pure revision batch: treated as an edit, always allowed by this pipeline
        # (same trust level as patch_chapter) — never falls through to the old
        # JSON-driven path.
        return Chain(chapter=chapter, stage_num=stage_nums[0], target=SkeletonPhase.WRITE)
    if len(first_time) > 1:
        return Chain(
            chapter=chapter, stage_num=first_time[0], target=SkeletonPhase.WRITE,
            batch_violation=(
                f"一次调用不能同时首次展开多段（收到 stage {first_time}）——"
                "一次只能首次展开一段，逐段停顿。"
            ),
        )
    stage_num = first_time[0]
    return Chain(chapter=chapter, stage_num=stage_num, target=SkeletonPhase.WRITE,
                 missing=_missing_for(chapter, stage_num, SkeletonPhase.WRITE),
                 missing_timeline_chars=_missing_timeline_for(chapter))


def resolve_chain(tool_name: str, args: dict) -> Chain | None:
    """None when tool_name isn't one of this pipeline's four tools — caller passes
    through ungated (edit tools)."""
    phase = _TOOL_PHASE.get(tool_name)
    if phase is None:
        return None
    chapter = args.get("chapter")
    if not isinstance(chapter, int):
        return None
    mark_chapter_active(chapter)
    if phase == SkeletonPhase.DIRECTION:
        return Chain(chapter=chapter, stage_num=None, target=phase,
                     missing=_missing_for(chapter, None, phase),
                     missing_timeline_chars=_missing_timeline_for(chapter))
    if phase == SkeletonPhase.WRITE:
        return _resolve_write_chain(chapter, args)
    stage_num = args.get("stage_num")
    if not isinstance(stage_num, int):
        return None
    return Chain(chapter=chapter, stage_num=stage_num, target=phase,
                 missing=_missing_for(chapter, stage_num, phase),
                 missing_timeline_chars=_missing_timeline_for(chapter))


# Process-global, not persisted: remembers (chapter, stage_num, phase) of the last
# blocked chain, purely so the injection layer and frontend overview can show a
# live roadmap. Losing it on restart is harmless — the next blocked call recomputes
# the same chain from live state (same pattern as world_pipeline._ACTIVE_TARGET).
_ACTIVE_TARGET: tuple[int, int | None, SkeletonPhase] | None = None

# Process-global, ephemeral, per-novel-per-chapter: which chapters currently have a background
# review/auto-fix job (skeleton_background_review.py) running, keyed by novel_id so two novels
# sharing a chapter number don't interfere. Cleared only on a job's *clean* completion (see
# skeleton_background_review.py::_run_chapter_review_fix) -- a cancelled-then-restarted job
# keeps its chapter marked the whole time, so external observers (the REST snapshot,
# collect_author_loop_blockers) never see a false "not reviewing" blip mid-restart.
_ACTIVE_REVIEWS: dict[str, set[int]] = {}


def mark_review_active(novel_id: str, chapter: int) -> None:
    _ACTIVE_REVIEWS.setdefault(novel_id, set()).add(chapter)


def clear_review_active(novel_id: str, chapter: int) -> None:
    s = _ACTIVE_REVIEWS.get(novel_id)
    if s is not None:
        s.discard(chapter)


def is_review_active(novel_id: str, chapter: int) -> bool:
    return chapter in _ACTIVE_REVIEWS.get(novel_id, set())


def any_review_active(novel_id: str) -> bool:
    return bool(_ACTIVE_REVIEWS.get(novel_id))


def gate(chain: Chain) -> str | None:
    """None -> allow. str -> rejection text.

    batch_violation is a one-shot correction (the agent just needs to split its
    next call) -- it doesn't persist into _ACTIVE_TARGET, unlike a genuine missing-
    phase block, which does (so later-turn injection can keep reminding the agent
    what's still needed)."""
    global _ACTIVE_TARGET
    if chain.batch_violation:
        return chain.batch_violation
    key = (chain.chapter, chain.stage_num, chain.target)
    if chain.blocked:
        _ACTIVE_TARGET = key
        return render_block_message(chain)
    if _ACTIVE_TARGET == key:
        _ACTIVE_TARGET = None
    return None


def active_chain() -> Chain | None:
    """Recompute the remembered target's chain against live state every call;
    clears the marker once its target phase is satisfied."""
    global _ACTIVE_TARGET
    if _ACTIVE_TARGET is None:
        return None
    chapter, stage_num, phase = _ACTIVE_TARGET
    chain = Chain(chapter=chapter, stage_num=stage_num, target=phase,
                  missing=_missing_for(chapter, stage_num, phase),
                  missing_timeline_chars=_missing_timeline_for(chapter))
    if not chain.blocked:
        _ACTIVE_TARGET = None
        return None
    return chain


def next_focus() -> Chain | None:
    """Proactive focus scoped to the currently-active chapter (_ACTIVE_CHAPTER) --
    unlike world_pipeline, chapter order isn't fixed here (any plotted chapter may
    be expanded in any order), so there is no well-defined "next chapter" to guess
    at; only the phase progression *within* the active chapter is deterministic.
    None when no chapter is active, or every one of its stages is already
    expanded."""
    if _ACTIVE_CHAPTER is None:
        return None
    chapter = _ACTIVE_CHAPTER
    if chapter not in _DIRECTION_SET:
        return Chain(chapter=chapter, stage_num=None, target=SkeletonPhase.DIRECTION,
                     missing_timeline_chars=_missing_timeline_for(chapter))
    for stage_num in _chapter_stage_nums(chapter):
        if _is_expanded(chapter, stage_num):
            continue
        if (chapter, stage_num) not in _LENS_CHOSEN:
            return Chain(chapter=chapter, stage_num=stage_num, target=SkeletonPhase.LENS,
                         missing_timeline_chars=_missing_timeline_for(chapter))
        if (chapter, stage_num) not in _EXT_CHOSEN:
            return Chain(chapter=chapter, stage_num=stage_num, target=SkeletonPhase.EXTENSIONS,
                         missing_timeline_chars=_missing_timeline_for(chapter))
        return Chain(chapter=chapter, stage_num=stage_num, target=SkeletonPhase.WRITE,
                     missing_timeline_chars=_missing_timeline_for(chapter))
    return None


def render_block_message(chain: Chain) -> str:
    if chain.batch_violation:
        return chain.batch_violation
    stage_part = f" stage {chain.stage_num}" if chain.stage_num is not None else ""
    missing_parts: list[str] = []
    order_parts: list[str] = []
    if chain.missing_timeline_chars:
        missing_parts.append(
            f"角色档案（{'、'.join(chain.missing_timeline_chars)} 未就绪，引擎自动推演中）"
        )
        order_parts.append("等待角色档案自动推演完成")
    missing_parts.extend(_PHASE_TITLES[p] for p in chain.missing)
    order_parts.extend(_PHASE_TITLES[p] for p in [*chain.missing, chain.target])
    lines = [
        f"第{chain.chapter}章{stage_part}「{_PHASE_TITLES[chain.target]}」现在还不能做，前置未完成。",
        "缺：" + "、".join(missing_parts) + "。",
        f"建议顺序：{'→'.join(order_parts)}。",
    ]
    return "".join(lines)


def _load_skill_body(name: str) -> str | None:
    from engine.setup_chat.skills import load_skill_body, setup_chat_skill_dirs
    return load_skill_body(name, setup_chat_skill_dirs())


def render_next_step_message(chain: Chain) -> str:
    """Proactive-focus phrasing (next_focus()-derived) -- distinct from
    render_block_message's "you tried something out of order" phrasing."""
    stage_part = f" stage {chain.stage_num}" if chain.stage_num is not None else ""
    return (f"接下来该做第{chain.chapter}章{stage_part}「{_PHASE_TITLES[chain.target]}」了。"
            f"可用工具：{_PHASE_TOOLS[chain.target]}。")


def render_activation(chain: Chain) -> str:
    """Injected each LLM call while a blocked chain is active (build_plan_activation
    dispatch target). Character archive gaps (missing_timeline_chars) block silently on the
    engine's automatic background derivation (timeline_auto.py) -- there is no dedicated skill
    to inject for the agent to drive that step itself."""
    body = render_block_message(chain) if chain.blocked else render_next_step_message(chain)
    guides: list[str] = []
    skill_body = _load_skill_body("skeleton-expansion")
    if skill_body:
        guides.append(f"### skeleton-expansion\n{skill_body}")
    guide = "\n\n" + "\n\n".join(guides) if guides else ""
    return f"【骨架扩写进行中】{body}{guide}"
