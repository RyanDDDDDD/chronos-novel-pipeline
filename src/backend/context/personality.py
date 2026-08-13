"""Timeline personality (freeform prose) read helpers."""
from __future__ import annotations


def resolved_personality(state: dict) -> str:
    """Return freeform personality from resolved state."""
    return str(state.get("personality") or "").strip()
