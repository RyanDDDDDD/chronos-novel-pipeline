"""Zero-maintenance prompt-syntax adapter keyed off a checkpoint's base_model string
(SD1.5 / SDXL / Pony / Flux). Pure string rules -- no LLM call, no per-checkpoint mapping
table, so it never needs updating when new checkpoints show up under an already-supported
architecture. Unknown/missing base_model is a deliberate no-op (existing SD1.5/SDXL-style
default prompts already work fine without adaptation)."""
from __future__ import annotations


def _classify(base_model: str | None) -> str:
    text = (base_model or "").lower()
    if "pony" in text:
        return "pony"
    if "flux" in text:
        return "flux"
    if "xl" in text:
        return "sdxl"
    if "1.5" in text:
        return "sd15"
    return "unknown"


def adapt_for_base_model(positive: str, negative: str, base_model: str | None) -> tuple[str, str]:
    arch = _classify(base_model)
    if arch == "pony":
        return (
            f"score_9, score_8_up, score_7_up, score_6_up, {positive}",
            f"score_4, score_5, score_6, {negative}",
        )
    if arch == "flux":
        # Flux is guidance-distilled -- Novita ignores/underuses negative_prompt for it,
        # and it responds better to a natural-language carrier sentence than a raw tag list.
        return f"A detailed illustration of {positive}.", ""
    return positive, negative
