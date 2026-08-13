"""Active-cast presence tracking for story_sandbox dynamic character-card injection: a character
mentioned in this turn's director instruction or the previous turn's prose stays "on stage" (its
static persona card gets rendered every turn by cast.py::render_dynamic_cast_block) until it goes
ABSENCE_LIMIT turns without a single mention, at which point it's pruned. Reuses the same
recall.py-style dual-scan input (director instruction ∪ previous turn's prose) feeding a
different vocab (entity_index.py::scan_characters), not a re-derivation of anything already
tracked by state_derive.py's character_states (the 5-field dynamic state, not the static persona
card) -- graph.py::_build_derive_char_node prunes character_states to this module's active_cast
output every turn, so the two stay in lockstep rather than character_states independently
accumulating. Chapter and free mode share this exact mechanism -- there is
no longer a chapter-outline-derived growth cap (see
docs/superpowers/specs/2026-08-01-sandbox-opening-grounding-instruction-only-design.md for why:
capping active_cast against the chapter's full declared roster pre-warmed cards for characters
who might never actually appear if the director's improvisation diverges from the outline). See
docs/superpowers/specs/2026-07-18-sandbox-free-mode-dynamic-cast-design.md."""
from __future__ import annotations

ABSENCE_LIMIT = 3


def update_active_cast(
    active_cast: dict[str, int], hits: set[str], turn_index: int,
) -> dict[str, int]:
    """Bumps every name in `hits` to `turn_index` (first appearance or refreshed), then drops any
    name whose last-seen turn is ABSENCE_LIMIT or more turns behind. Idempotent when re-called
    with the same turn_index (e.g. a rewrite of the same round) -- unlike recall.py's cooldown
    suppression, this only tracks recency, not "already recalled once", so no special same-turn
    stripping is needed."""
    updated = {**active_cast, **{name: turn_index for name in hits}}
    return {name: seen for name, seen in updated.items() if turn_index - seen < ABSENCE_LIMIT}
