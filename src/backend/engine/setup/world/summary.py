"""world_bible summary rendering: scalar segmentation + power/geographic name + core theme, shared by cast/plot grounding."""
from __future__ import annotations

from typing import Any


def render_world_summary(wb: dict[str, Any] | None) -> str:
    """Renders the world_bible dict to the world settings summary text fed to prompt; returns '' on empty/None."""
    if not isinstance(wb, dict) or not wb:
        return ""
    parts: list[str] = []
    for k in ("tone", "background"):
        if wb.get(k):
            parts.append(f"{k}：{wb[k]}")
    for k in ("factions", "races", "geography", "power_system", "core_themes"):
        items = wb.get(k) or []
        if isinstance(items, list) and items:
            lines = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                name = str(it.get("name", "")).strip()
                desc = str(it.get("desc", "")).strip()
                if not name:
                    continue
                lines.append(f"  - {name}：{desc}" if desc else f"  - {name}")
            if lines:
                parts.append(f"{k}：\n" + "\n".join(lines))
    return "\n".join(parts)


def world_race_names(wb: dict[str, Any] | None) -> list[str]:
    """
List of race names declared in world_bible.races (remove empty, preserve order); no races → []."""
    if not isinstance(wb, dict):
        return []
    out: list[str] = []
    for it in wb.get("races") or []:
        if isinstance(it, dict):
            nm = str(it.get("name", "")).strip()
            if nm:
                out.append(nm)
    return out


def resolve_race_desc(wb: dict[str, Any] | None, race_name: str | None) -> str:
    """Match world_bible.races by name take desc (strip + casefold normalization); missing/unmatched/empty → ''."""
    if not isinstance(wb, dict) or not race_name:
        return ""
    target = race_name.strip().casefold()
    if not target:
        return ""
    for it in wb.get("races") or []:
        if isinstance(it, dict) and str(it.get("name", "")).strip().casefold() == target:
            return str(it.get("desc", "")).strip()
    return ""
