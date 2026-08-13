"""Code-defined fixed pipeline for world/schema/character/plot/timeline construction.

Replaces construction_plan.json + TASK_SPECS for these six TaskKinds with a plain
Python stage list — no agent-authored task list, no persisted plan file for this
scope. Completion is re-derived from real artifacts on every call via
derive_task_status (unchanged — that function never needed the JSON file, it only
ever took a {kind, params} dict as its argument). See
docs/superpowers/specs/2026-07-08-world-construction-code-pipeline-design.md.

skeleton_stage uses skeleton_pipeline (which also owns dialogue design via its 3b
extension menu). Edit tools pass through ungated — see plan_runner.gate_tool_call."""
from __future__ import annotations

from dataclasses import dataclass, field

from engine.setup_chat.construction_plan import TaskKind, derive_task_status
from engine.setup_chat.world_tools import WORLD_PIPELINE_TOOL_NAMES


@dataclass(frozen=True)
class WorldStage:
    kind: str
    tools: frozenset[str]
    skill: str


WORLD_STAGES: tuple[WorldStage, ...] = (
    WorldStage(TaskKind.WORLD, WORLD_PIPELINE_TOOL_NAMES, "world-interview"),
    WorldStage(TaskKind.CHARACTER, frozenset({"add_character"}), "character-interview"),
    WorldStage(TaskKind.PLOT_CHAPTER, frozenset({"generate_one_chapter"}), "plot-interview"),
    WorldStage(TaskKind.TIMELINE, frozenset({"write_character_archive"}), ""),
)

_TOOL_STAGE: dict[str, WorldStage] = {
    tool: stage for stage in WORLD_STAGES for tool in stage.tools
}


def stage_of(tool_name: str) -> WorldStage | None:
    return _TOOL_STAGE.get(tool_name)


def _stage_done(stage: WorldStage, chapter: int | None) -> bool:
    if stage.kind == TaskKind.PLOT_CHAPTER:
        # Aggregate "is there any plot chapter" — derive_task_status's PLOT_CHAPTER
        # branch requires an exact chapter match, it has no aggregate form; PLOT_ALL
        # ("any chapter exists") is what this stage's completion actually means,
        # correct whether the chapter was written via generate_one_chapter.
        return derive_task_status({"kind": TaskKind.PLOT_ALL, "params": {}}) == "done"
    if stage.kind == TaskKind.TIMELINE and chapter is not None:
        return derive_task_status({"kind": TaskKind.TIMELINE, "params": {"chapter": chapter}}) == "done"
    return derive_task_status({"kind": stage.kind, "params": {}}) == "done"


def _chapter_arg(args: dict) -> int | None:
    ch = args.get("chapter", args.get("chapter_index"))
    return ch if isinstance(ch, int) else None


@dataclass(frozen=True)
class Chain:
    target: WorldStage
    chapter: int | None
    missing_stages: list[WorldStage] = field(default_factory=list)
    missing_timeline_chapters: list[int] = field(default_factory=list)
    upcoming: list[WorldStage] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return bool(self.missing_stages or self.missing_timeline_chapters)


def _build_chain(stage: WorldStage, chapter: int | None) -> Chain:
    idx = WORLD_STAGES.index(stage)
    missing_stages = [s for s in WORLD_STAGES[:idx] if not _stage_done(s, chapter)]
    missing_chapters: list[int] = []
    if stage.kind == TaskKind.TIMELINE and chapter is not None:
        from engine.setup_chat.plan_runner import _missing_prior_timeline_chapters
        missing_chapters = _missing_prior_timeline_chapters(chapter)
    return Chain(
        target=stage, chapter=chapter, missing_stages=missing_stages,
        missing_timeline_chapters=missing_chapters, upcoming=list(WORLD_STAGES[idx + 1:]),
    )


def resolve_chain(tool_name: str, args: dict) -> Chain | None:
    """None when tool_name isn't part of WORLD_STAGES — caller passes through ungated."""
    stage = stage_of(tool_name)
    if stage is None:
        return None
    # Chapter identity only matters for the `timeline` stage (sequential-chapter
    # rule); other stages' completion doesn't depend on which chapter was attempted,
    # so a stray chapter_index/chapter arg must not become part of their identity.
    chapter = _chapter_arg(args) if stage.kind == TaskKind.TIMELINE else None
    if stage.kind == TaskKind.TIMELINE and chapter is not None:
        name = args.get("name")
        if isinstance(name, str) and name:
            mark_timeline_active(chapter, name)
    return _build_chain(stage, chapter)


# Process-global, not persisted: remembers (target kind, chapter-or-None) of the
# last blocked chain, purely so the injection layer and frontend overview can show
# a live roadmap. Losing it on restart is harmless — the next blocked call
# recomputes the same chain from real artifacts (same pattern as
# plan_runner._PENDING_REPAIR).
_ACTIVE_TARGET: tuple[str, int | None] | None = None
_ACTIVE_TIMELINE_TARGET: tuple[int, str] | None = None  # (chapter, name)


def active_timeline_target() -> tuple[int, str] | None:
    return _ACTIVE_TIMELINE_TARGET


def mark_timeline_active(chapter: int, name: str) -> None:
    """Record that (chapter, name) is the timeline target currently being derived — set
    whenever a TIMELINE-stage tool call resolves both a chapter and a character name, and by
    read_archive_seed on a successful (non-empty) read. Single value, not a set — the automatic
    background cascade (timeline_auto.py) and the manual refine tool both only ever work on one
    character archive at a time; a later call for a different target simply overwrites this."""
    global _ACTIVE_TIMELINE_TARGET
    _ACTIVE_TIMELINE_TARGET = (chapter, name)


def clear_timeline_active(chapter: int, name: str) -> None:
    """Called once (chapter, name)'s timeline is fully written. No-op if it isn't the
    currently tracked target — never clears a different target's marker."""
    global _ACTIVE_TIMELINE_TARGET
    if _ACTIVE_TIMELINE_TARGET == (chapter, name):
        _ACTIVE_TIMELINE_TARGET = None


def active_timeline_seed_injection() -> str | None:
    """Deterministic per-turn injection (pre_model_hook dispatch target, alongside — not
    instead of — skeleton_pipeline.active_seed_injection): while a (chapter, name) timeline
    target is active, rebuild and return its full grounding text (prior resolved state + this
    chapter's relevant stages) every call. None when no target is active, or the target turns
    out to have no plot stages (edge case: marker set, then plot edited mid-session)."""
    if _ACTIVE_TIMELINE_TARGET is None:
        return None
    chapter, name = _ACTIVE_TIMELINE_TARGET
    from engine.setup_chat.timeline_seed import build_timeline_seed, render_timeline_seed

    seed = build_timeline_seed(name, chapter)
    if not seed.get("stages"):
        return None
    return f"【角色档案派生事实记忆·第{chapter}章·{name}】\n{render_timeline_seed(seed)}"


def gate(chain: Chain) -> str | None:
    """None -> allow. str -> rejection text (see render_block_message)."""
    global _ACTIVE_TARGET
    key = (chain.target.kind, chain.chapter)
    if chain.blocked:
        _ACTIVE_TARGET = key
        return render_block_message(chain)
    if _ACTIVE_TARGET == key:
        _ACTIVE_TARGET = None
    return None


def active_chain() -> Chain | None:
    """Recompute the remembered target's chain against live state every call;
    clears the marker once its target stage is satisfied."""
    global _ACTIVE_TARGET
    if _ACTIVE_TARGET is None:
        return None
    kind, chapter = _ACTIVE_TARGET
    stage = next((s for s in WORLD_STAGES if s.kind == kind), None)
    if stage is None:
        _ACTIVE_TARGET = None
        return None
    chain = _build_chain(stage, chapter)
    if not chain.blocked:
        _ACTIVE_TARGET = None
        return None
    return chain


def next_focus() -> Chain | None:
    """Earliest incomplete stage, computed without requiring any prior tool-call
    attempt (fills the gap active_chain() leaves on the normal happy path, where
    nothing is ever blocked so _ACTIVE_TARGET never gets set). Always returns an
    unblocked Chain (missing_stages empty) -- stages are scanned in declaration
    order and returned on the first gap, so everything before it is already
    confirmed done. None when the whole pipeline is complete."""
    for stage in WORLD_STAGES:
        if stage.kind == TaskKind.TIMELINE:
            from engine.setup_chat.construction_plan import _plot_chapters
            from engine.setup_chat.plan_runner import _chapter_timeline_done
            missing_chapters = [
                c for c in sorted(_plot_chapters()) if not _chapter_timeline_done(c)
            ]
            if missing_chapters:
                return _build_chain(stage, missing_chapters[0])
            continue
        if not _stage_done(stage, None):
            return _build_chain(stage, None)
    return None


def render_block_message(chain: Chain) -> str:
    order = "→".join(s.kind for s in [*chain.missing_stages, chain.target])
    lines = [f"「{chain.target.kind}」现在还不能做，前置未完成。"]
    if chain.missing_stages:
        lines.append("缺：" + "、".join(s.kind for s in chain.missing_stages) + "。")
    if chain.missing_timeline_chapters:
        lines.append(f"角色档案须按章顺序推：第 {chain.missing_timeline_chapters} 章还没做。")
    if chain.target.kind == TaskKind.TIMELINE:
        lines.append(
            f"第 {chain.chapter} 章角色档案正在自动构建中，请提醒用户到角色档案页面查看进度；"
            "构建完成前无法继续。"
        )
    lines.append(f"建议顺序：{order}。")
    if chain.upcoming:
        lines.append("之后还有：" + "、".join(s.kind for s in chain.upcoming) + "。")
    else:
        lines.append("这是最后一步。")
    return "".join(lines)


def _load_skill_body(name: str) -> str | None:
    from engine.setup_chat.skills import load_skill_body, setup_chat_skill_dirs
    return load_skill_body(name, setup_chat_skill_dirs())


def render_next_step_message(chain: Chain) -> str:
    """Proactive-focus phrasing (next_focus()-derived, never blocked) -- distinct
    from render_block_message's "you tried something out of order" phrasing."""
    tools = "、".join(sorted(chain.target.tools))
    return f"接下来该做「{chain.target.kind}」了。可用构建工具：{tools}。"


def render_activation(chain: Chain) -> str:
    """Injected each LLM call while a chain is active (build_plan_activation
    dispatch target) -- either a blocked recovery target (active_chain()) or the
    proactive next step (next_focus())."""
    body = render_block_message(chain) if chain.blocked else render_next_step_message(chain)
    sections = []
    for s in [*chain.missing_stages, chain.target]:
        skill_body = _load_skill_body(s.skill)
        if skill_body:
            sections.append(f"### {s.kind}（{s.skill}）\n{skill_body}")
    guide = "\n\n" + "\n\n".join(sections) if sections else ""
    return f"【建设管道进行中】{body}{guide}"
