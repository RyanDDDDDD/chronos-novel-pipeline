"""Engine-held plan orchestration for setup-chat construction pipelines.

world/schema/character/plot_chapter/plot_all/timeline are handled by
engine.setup_chat.world_pipeline; skeleton_stage (and dialogue design, folded into
its 3b extension menu) by engine.setup_chat.skeleton_pipeline — code-defined
pipelines, no JSON file. Edit tools pass through ungated — see gate_tool_call.

Status stays artifact-derived (construction_plan.derive_task_status) so pipeline
rows self-heal when upstream edits invalidate downstream artifacts. Spec:
docs/superpowers/specs/2026-07-07-plan-runner-orchestration-design.md"""
from __future__ import annotations

from engine.setup_chat.construction_plan import TaskKind, derive_task_status


def _chapter_timeline_done(chapter: int) -> bool:
    """Chapter-scoped timeline completion (not an aggregate check — that would
    false-positive for plans that only touch one chapter). Used by
    world_pipeline's sequential-chapter rule (via _missing_prior_timeline_chapters)."""
    return derive_task_status({"kind": TaskKind.TIMELINE, "params": {"chapter": chapter}}) == "done"


def _missing_prior_timeline_chapters(chapter: int) -> list[int]:
    """Earlier plotted chapters (< chapter) whose timeline is not yet derived.
    Timeline rolls forward (write_character_archive reads deltas_before to gate
    personality progression) so it must be derived chapter-by-chapter from chapter 1
    — skipping ahead silently corrupts the rolling state instead of erroring."""
    from engine.setup_chat.construction_plan import _plot_chapters
    return [c for c in sorted(_plot_chapters()) if c < chapter and not _chapter_timeline_done(c)]


def _chapter_exists(chapter: int) -> bool:
    from repositories import get_plot_repo
    return any(isinstance(c, dict) and c.get("chapter") == chapter
               for c in get_plot_repo().list_raw())


def gate_tool_call(name: str, args: dict) -> str | None:
    """Plan-aware tool gate. None -> execute; str -> deterministic rejection text
    (returned to the model instead of running the tool).

    world/schema/character/plot_chapter/plot_all/timeline tools dispatch to
    world_pipeline; skeleton_stage tools (set_chapter_direction/set_stage_lens/
    set_stage_extensions/write_chapter_skeleton) to skeleton_pipeline. Everything
    else (edit tools, research/meta tools) passes through ungated — edit tools'
    targets already exist by construction.

    AUTO mode + world not yet built is a special case: construct_world gets rejected here even
    though world_pipeline.resolve_chain would otherwise allow it (stage_of() maps construct_world
    to the WORLD stage unconditionally, regardless of completion) -- steers the model toward
    auto_build_setup instead. This is the execution-time backstop for tool_router's
    _world_focus_tool_names routing-level narrowing; a genuine "redo the whole world" call once
    world already exists is unaffected (derive_task_status reports WORLD done, condition is
    False).

    Symmetrically, AUTO mode rejects a call that would advance a stage/direction the chapter
    still has left to do (execution-time backstop for tool_router's _skeleton_focus_tool_names
    narrowing toward auto_expand_skeleton) -- this fires for a virgin chapter and for one with
    partial progress alike (chapter_remaining_stage_nums), so switching into AUTO mid-chapter
    can't bypass it. A pure revision call on an already-expanded stage (resolve_chain resolves
    its stage_num to one not in the remaining set) is unaffected -- only first-time advances on
    still-remaining stages get redirected."""
    from engine.setup_chat import skeleton_pipeline, world_pipeline
    from engine.setup_chat.construction_plan import TaskKind, derive_task_status
    from engine.setup_chat.mode import is_auto_mode
    from engine.setup_chat.world_tools import WORLD_PIPELINE_TOOL_NAMES

    if (name in WORLD_PIPELINE_TOOL_NAMES and is_auto_mode()
            and derive_task_status({"kind": TaskKind.WORLD, "params": {}}) != "done"):
        return "AUTO 模式下请改用 auto_build_setup 一键构建整套设定，不要直接调用世界观维度工具。"

    chain = world_pipeline.resolve_chain(name, args)
    if chain is not None:
        if name == "generate_one_chapter":
            ch = args.get("chapter_index", args.get("chapter"))
            if isinstance(ch, int) and _chapter_exists(ch):
                return None
        return world_pipeline.gate(chain)

    skel_chain = skeleton_pipeline.resolve_chain(name, args)
    if skel_chain is not None:
        if is_auto_mode():
            remaining = skeleton_pipeline.chapter_remaining_stage_nums(skel_chain.chapter)
            if remaining and (skel_chain.stage_num is None or skel_chain.stage_num in remaining):
                return ("AUTO 模式下请改用 auto_expand_skeleton 一键扩写整章骨架"
                        "（支持接续已有进度），不要逐段手动调用。")
        return skeleton_pipeline.gate(skel_chain)

    return None


def build_plan_activation() -> str | None:
    """Deterministic per-turn injection. world_pipeline's blocked/active chain
    takes priority, then its proactive next_focus(); then skeleton_pipeline's same
    pair. None when neither pipeline has anything to say right now."""
    from engine.setup_chat import skeleton_pipeline, world_pipeline

    chain = world_pipeline.active_chain() or world_pipeline.next_focus()
    if chain is not None:
        return world_pipeline.render_activation(chain)

    skel_chain = skeleton_pipeline.active_chain() or skeleton_pipeline.next_focus()
    if skel_chain is not None:
        return skeleton_pipeline.render_activation(skel_chain)

    return None


# Repair-task cache: cascade sites record what they cleared; pending_invalidation_note
# renders and clears in one shot (show-once consumption).
_PENDING_REPAIR: list[dict] = []


def record_invalidation(tasks: list[dict]) -> None:
    seen = {t.get("id") for t in _PENDING_REPAIR}
    for t in tasks:
        if t.get("id") not in seen:
            _PENDING_REPAIR.append(t)
            seen.add(t.get("id"))


def pending_invalidation_note() -> str:
    """Render the pending cascade-invalidation reminders and clear the queue —
    the note is already surfaced inline in the triggering edit tool's own return
    text, so there is no separate "activate" step to wait for; showing it once is
    consumption, otherwise the queue would repeat the same stale items forever."""
    global _PENDING_REPAIR
    if not _PENDING_REPAIR:
        return ""
    titles = "、".join(str(t.get("title", t.get("id"))) for t in _PENDING_REPAIR)
    _PENDING_REPAIR = []
    return (f"\n⚠ 本次修改使以下派生产物失效：{titles}。"
            "请直接调用对应建造工具重建（如角色档案用 write_character_archive、"
            "骨架用 write_chapter_skeleton），管道会按序把关。")
