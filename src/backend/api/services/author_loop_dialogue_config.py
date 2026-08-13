"""Line-driven pipeline configuration API: per-agent parameters."""
from __future__ import annotations

from engine.modes.author_loop_skill_prefs import (
    load_dialogue_prefs,
    save_dialogue_prefs,
)


def _list_buildtime_review_hooks() -> list[dict]:
    """Skeleton-expansion's review axis (transition + stage sub-axes)."""
    from engine.author_loop.review.review_loader import REVIEW_HOOKS
    from engine.setup_chat.chapter_review import STAGE_HOOK_NAMES, TRANSITION_HOOK_NAMES

    disabled = set(load_dialogue_prefs().get("disabled_buildtime_review_hooks", []))
    by_name = {h.name: h for h in REVIEW_HOOKS}
    out: list[dict] = []
    for name in (*TRANSITION_HOOK_NAMES, *STAGE_HOOK_NAMES):
        hook = by_name.get(name)
        if hook is None:
            continue
        out.append({
            "name": name,
            "display_name": hook.display_name,
            "axis": "transition" if name in TRANSITION_HOOK_NAMES else "stage",
            "enabled": name not in disabled,
        })
    return out


def _list_setup_review_hooks() -> list[dict]:
    """Setup quality gate axis (world bible + character cards before persist)."""
    from engine.author_loop.review.review_loader import REVIEW_HOOKS
    from engine.setup_chat.setup_quality_review import SETUP_CAST_HOOK_NAMES, SETUP_WORLD_HOOK_NAMES

    disabled = set(load_dialogue_prefs().get("disabled_setup_review_hooks", []))
    by_name = {h.name: h for h in REVIEW_HOOKS}
    out: list[dict] = []
    for name in (*SETUP_WORLD_HOOK_NAMES, *SETUP_CAST_HOOK_NAMES):
        hook = by_name.get(name)
        if hook is None:
            continue
        out.append({
            "name": name,
            "display_name": hook.display_name,
            "axis": "world" if name in SETUP_WORLD_HOOK_NAMES else "cast",
            "enabled": name not in disabled,
        })
    return out


def _list_runtime_review_hooks() -> list[dict]:
    """author_loop's candidate-prose review axis (flat, no sub-axes) -- toggled
    independently from the buildtime axis even for a shared hook name (e.g.
    "style")."""
    from engine.author_loop.dialogue_mode.stage_review import RUNTIME_HOOK_NAMES
    from engine.author_loop.review.review_loader import REVIEW_HOOKS

    disabled = set(load_dialogue_prefs().get("disabled_runtime_review_hooks", []))
    by_name = {h.name: h for h in REVIEW_HOOKS}
    out: list[dict] = []
    for name in RUNTIME_HOOK_NAMES:
        hook = by_name.get(name)
        if hook is None:
            continue
        out.append({
            "name": name,
            "display_name": hook.display_name,
            "enabled": name not in disabled,
        })
    return out


def _resolved_identity() -> str:
    from engine.setup_chat.agent import resolved_default_identity
    return resolved_default_identity()


def read_state() -> dict:
    return {
        "config": load_dialogue_prefs(),
        "default_identity": _resolved_identity(),
        "buildtime_review_hooks": _list_buildtime_review_hooks(),
        "runtime_review_hooks": _list_runtime_review_hooks(),
        "setup_review_hooks": _list_setup_review_hooks(),
    }


def write_config(body: dict) -> dict:
    body = body if isinstance(body, dict) else {}
    dlg = body.get("dialogue")
    if isinstance(dlg, dict):
        save_dialogue_prefs(dlg)
    return {"ok": True, **read_state()}
