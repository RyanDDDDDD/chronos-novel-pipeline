"""Neutral parsing of dialogue chain: character_archive resolution."""
from __future__ import annotations

import json
from typing import Any

_LORE_CONSTANT_KEYS = ("name", "given_name")


def parse_character_archives(raw: dict[str, Any]) -> dict[str, dict]:
    """character_archive pre-inject dict → {full name: flat archive_dict}."""
    parsed: dict[str, dict] = {}
    for name, raw_val in (raw or {}).items():
        try:
            parsed[name] = json.loads(raw_val) if isinstance(raw_val, str) else dict(raw_val)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return expand_archives_to_stages(parsed)


def expand_archives_to_stages(archives: dict[str, dict]) -> dict[str, dict]:
    """Raw lore+timeline payload → resolved flat profile (one snapshot per chapter, at stage=1);
    an already-resolved archive dict passes through unchanged."""
    from context.character_resolver import resolve_from

    out: dict[str, dict] = {}
    for name, obj in archives.items():
        if "_lore" in obj and "_timeline" in obj:
            lore, snaps, ch = obj["_lore"], obj["_timeline"], int(obj["_chapter"])
            base = {k: lore[k] for k in _LORE_CONSTANT_KEYS if k in lore}
            out[name] = {**base, **resolve_from(lore, snaps, ch, 1)}
        else:
            out[name] = obj
    return out

