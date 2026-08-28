"""Assemble the final Novita prompt/negative_prompt: cached visual tags + selected art
style preset + optional freeform addendum, then run the base-model adapter as the last
step (adapter operates on the fully composed string, not just the preset fragment, so
e.g. Pony's score-tag prefix covers the whole prompt)."""
from __future__ import annotations

from media.portrait.base_model_adapter import adapt_for_base_model
from media.portrait.style_presets import get_art_style_preset


def build_portrait_prompt(
    visual_tags: str,
    base_model: str | None = None,
    *,
    identity_tags: str | None = None,
) -> tuple[str, str]:
    from engine.modes.author_loop_skill_prefs import load_dialogue_prefs

    prefs = load_dialogue_prefs()
    preset = get_art_style_preset(prefs.get("portrait_style_preset_id"))
    extra_positive = (prefs.get("portrait_style_prompt") or "").strip()
    extra_negative = (prefs.get("portrait_negative_prompt") or "").strip()

    # A manual danbooru identity anchor (e.g. "shiroko (blue archive), blue archive") leads
    # the positive prompt verbatim -- booru models weight the earliest tags most heavily.
    lead = (identity_tags or "").strip()
    positive_parts = [p for p in (lead, visual_tags, preset.positive_fragment, extra_positive) if p]
    negative_parts = [p for p in (preset.negative_fragment, extra_negative) if p]
    positive = ", ".join(positive_parts)
    negative = ", ".join(negative_parts)

    return adapt_for_base_model(positive, negative, base_model)
