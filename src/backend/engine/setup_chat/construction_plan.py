"""Artifact-derived task status for setup-chat construction pipelines.

derive_task_status compares real product files to decide done/pending for each
TaskKind — used by world_pipeline and skeleton_pipeline overview rows and gates.
No JSON plan file is persisted anymore."""
from __future__ import annotations

from enum import StrEnum


class TaskKind(StrEnum):
    """
Build task type; value maps to setup_chat existing build tool."""

    WORLD = "world"
    CHARACTER = "character"
    PLOT_CHAPTER = "plot_chapter"
    PLOT_ALL = "plot_all"
    TIMELINE = "timeline"
    SKELETON_STAGE = "skeleton_stage"


def _cast_names() -> set[str]:
    from repositories import get_lore_repo
    roster = get_lore_repo().list_raw()
    return {c["name"] for c in roster if isinstance(c, dict) and c.get("name")}


def _plot_chapters() -> set[int]:
    from repositories import get_plot_repo
    chapters = get_plot_repo().list_raw()
    return {int(c["chapter"]) for c in chapters
            if isinstance(c, dict) and isinstance(c.get("chapter"), int)}


def _timeline_done(chapter: int, name: str | None) -> bool:
    """Whether this chapter's (or, if given, this character's) archive has been persisted --
    the archive is written once the archive→timeline derive step completes, so a persisted
    row means done (2026-08-09 fix: replaced a stale filesystem scan of the pre-SQLite
    archive.json era; character_archives has been the sole write target for a while, see
    docs/superpowers/specs/2026-08-09-archive-view-sqlite-migration-gap-fix.md)."""
    from repositories import get_archive_repo

    if name:
        return get_archive_repo().get(name, chapter) is not None
    return bool(get_archive_repo().list_built().get(chapter))


def _stage_beats(chapter: int, stage_num: int) -> list[dict] | None:
    """Beats of (chapter, stage_num) from plot; None when chapter/stage/beats missing."""
    from repositories import get_plot_repo
    chapters = get_plot_repo().list_raw()
    ch = next((c for c in chapters if isinstance(c, dict) and c.get("chapter") == chapter), None)
    if ch is None:
        return None
    st = next((s for s in (ch.get("stages") or [])
               if isinstance(s, dict) and s.get("stage_num") == stage_num), None)
    if st is None:
        return None
    beats = st.get("beats")
    return beats if isinstance(beats, list) and beats else None


def _all_timeline_done() -> bool:
    """
Aggregation criterion: All plot chapters have been placed in the file (plot is empty → not completed). For overall timeline tasks without chapters."""
    chapters = _plot_chapters()
    return bool(chapters) and all(_timeline_done(ch, None) for ch in chapters)


def derive_task_status(task: dict) -> str:
    """Compare the real product to derive the task status: 'done' | 'pending'. See each kind branch for criteria."""
    kind = task.get("kind")
    params = task.get("params") or {}
    if kind == TaskKind.WORLD:
        from repositories import get_world_repo

        from engine.setup.world.validator import validate_world_bible

        wb = get_world_repo().get()
        if not isinstance(wb, dict) or not wb:
            return "pending"
        return "done" if not validate_world_bible(wb) else "pending"
    if kind == TaskKind.CHARACTER:
        #Character-by-character tasks are given to given_name (exact); aggregate "build a batch of characters" tasks are given without given_name → cast is either empty or done.
        names = _cast_names()
        gn = params.get("given_name")
        if gn:
            return "done" if gn in names else "pending"
        gns = params.get("given_names")
        if isinstance(gns, list) and gns:
            return "done" if all(n in names for n in gns) else "pending"
        return "done" if names else "pending"
    if kind == TaskKind.PLOT_CHAPTER:
        return "done" if params.get("chapter") in _plot_chapters() else "pending"
    if kind == TaskKind.PLOT_ALL:
        return "done" if _plot_chapters() else "pending"
    if kind == TaskKind.TIMELINE:
        #The chapter-by-chapter task is given to chapter (accurate); the aggregation "whole derived timeline" task has no chapter → each chapter has a file and is done.
        ch = params.get("chapter")
        if isinstance(ch, int):
            return "done" if _timeline_done(ch, params.get("name")) else "pending"
        return "done" if _all_timeline_done() else "pending"
    if kind == TaskKind.SKELETON_STAGE:
        beats = _stage_beats(int(params.get("chapter", 0)), int(params.get("stage_num", 0)))
        return "done" if beats else "pending"
    return "pending"
