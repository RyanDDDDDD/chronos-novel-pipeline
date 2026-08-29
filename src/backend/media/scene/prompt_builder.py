"""Assemble the scene positive/negative prompt: LLM scene base + the shared art-style preset
fragment + the per-novel freeform addendum. Unlike media.portrait.prompt_builder this does
NOT run the base-model adapter -- V4.5's base_model classifies as 'unknown' (adapter no-op)
and the per-character captions must stay free of score-tag prefixes."""
from __future__ import annotations

from media.portrait.style_presets import get_art_style_preset


def build_scene_positive(base: str) -> tuple[str, str]:
    from engine.modes.author_loop_skill_prefs import load_dialogue_prefs

    prefs = load_dialogue_prefs()
    preset = get_art_style_preset(prefs.get("portrait_style_preset_id"))
    extra_pos = (prefs.get("portrait_style_prompt") or "").strip()
    extra_neg = (prefs.get("portrait_negative_prompt") or "").strip()

    positive = ", ".join(p for p in (base.strip(), preset.positive_fragment, extra_pos) if p)
    negative = ", ".join(p for p in (preset.negative_fragment, extra_neg) if p)
    return positive, negative
