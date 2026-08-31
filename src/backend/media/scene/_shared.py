"""Shared helpers for sandbox (media.scene.generation) and author-page
(media.scene.author) scene-image generation: present-character appearance tags,
present-character portrait bytes (Precise Reference sources), and image-gen model
resolution against a dialogue-prefs bucket."""
from __future__ import annotations

_MAX_REFERENCES = 6


def _resolve_scene_image_entry(config_key: str) -> dict | None:
    """The image_gen entry to use for scene generation. `config_key` selects the dialogue-prefs
    bucket that holds the binding: "sandbox_llm_params" for the sandbox canvas's 场景生图 node,
    "llm_params" for the main-writer canvas's 场景生图 node. Resolution:
    1. the entry bound to that bucket's `scene_image.model_ref`;
    2. failing that, the sole image_gen entry if exactly one exists (so a single-model setup
       works with no explicit binding, parity with character_portrait).
    Either way the entry must be a NovelAI one -- V4.5 Precise Reference is NovelAI-only.
    Returns None when nothing usable is configured."""
    from domain.model_catalog import load_custom_models
    from engine.modes.author_loop_skill_prefs import load_dialogue_prefs

    node = load_dialogue_prefs().get(config_key, {}).get("scene_image", {})
    model_ref = node.get("model_ref") if isinstance(node, dict) else None
    image_gen_entries = [m for m in load_custom_models() if m.get("provider") == "image_gen"]

    if model_ref:
        entry = next((m for m in image_gen_entries if m.get("id") == model_ref), None)
    elif len(image_gen_entries) == 1:
        entry = image_gen_entries[0]
    else:
        entry = None

    if entry is None or entry.get("service") != "novelai":
        return None
    return entry


def _lore_by_name() -> dict[str, dict]:
    from engine.setup_chat.tools import _name_key
    from repositories import get_lore_repo

    return {
        _name_key(c): c for c in get_lore_repo().list_raw() if isinstance(c, dict)
    }


def _character_visual_tags(names: list[str]) -> dict[str, str]:
    by_name = _lore_by_name()
    out: dict[str, str] = {}
    for n in names:
        tags = (by_name.get(n) or {}).get("portrait_visual_tags")
        if isinstance(tags, str) and tags.strip():
            out[n] = tags.strip()
    return out


def _character_portrait_bytes(names: list[str]) -> dict[str, bytes]:
    from utils.paths import portrait_path

    by_name = _lore_by_name()
    out: dict[str, bytes] = {}
    for n in names:
        rel = (by_name.get(n) or {}).get("portrait_path")
        if isinstance(rel, str) and rel:
            try:
                with open(portrait_path(rel), "rb") as f:
                    out[n] = f.read()
            except OSError:
                pass
    return out
