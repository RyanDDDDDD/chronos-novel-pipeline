"""The main author starts the front door: Verify all necessary products at one time before running, and if they are missing, an error will be reported (not fail-fast).

Why this door is needed: The main writer relies on three types of pre-built products: world view/character file/skeleton of this chapter. Past deficiencies are only in circulation.
Errors were reported sporadically after I ran in (and the half-finished character file - the fields were there but collapsed - could get away with it). Here we are dispatching background tasks
Previously, all gaps were closed at once, allowing users to fill them in one round instead of reporting one at a time.

Verification scope: The world view and character files are the **global** front-end; the outline/skeleton only verifies the **chapter being started** - start by chapter,
You shouldn't be stopped because other chapters haven't built a skeleton. The relationship map is not easy to get started with (it lacks graceful downgrading on the consumer side, which does not affect writing)."""
from __future__ import annotations


def collect_author_loop_blockers(chapter: int) -> list[str]:
    """
Collect all unsatisfied preconditions before starting the main chapter of chapter, and return the blocking reason list (empty = can be started)."""
    blockers: list[str] = []
    blockers.extend(_world_blockers())
    blockers.extend(_roster_blockers())
    blockers.extend(_chapter_blockers(chapter))
    return blockers


def _world_blockers() -> list[str]:
    """World view: world_bible If the rendering summary is empty, it is considered not to be constructed."""
    from repositories import get_world_repo

    from engine.setup.world.summary import render_world_summary

    bible = get_world_repo().get()
    if not render_world_summary(bible if isinstance(bible, dict) else {}):
        return ["未构建世界观——请先「构建世界观」。"]
    return []


def _roster_blockers() -> list[str]:
    """
Role files: If the database is empty, it will be blocked directly; if it is not empty, hard schema verification will be performed (per-role field integrity)."""
    from repositories import get_lore_repo

    from engine.setup.cast.cast_validator import validate_roster

    roster = get_lore_repo().list_raw()
    if not roster:
        return ["未构建角色班底——请先「构建角色」。"]
    #Empty libraries have been blocked above. Here we only check whether the fields of the libraries that actually have roles are complete one by one.
    return validate_roster(roster)


def _chapter_blockers(chapter: int) -> list[str]:
    """Outline of this chapter + skeleton: load_prebuilt_skeleton has covered the two deficiencies of "no plot/stages" and "skeleton not expanded"."""
    from utils.paths import active_novel_id

    from engine.setup_chat import skeleton_pipeline

    if skeleton_pipeline.is_review_active(active_novel_id(), chapter):
        return [f"第{chapter}章骨架仍在后台审查/修复中，完成后才能开始写正文。"]

    from engine.author_loop.build import SkeletonNotBuiltError, load_prebuilt_skeleton

    try:
        load_prebuilt_skeleton(chapter)
    except SkeletonNotBuiltError as exc:
        return [str(exc)]
    return []
