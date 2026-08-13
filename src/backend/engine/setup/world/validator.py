"""world_bible schema integrity hard check (pure function). Free prose, no vocabulary lists."""
from __future__ import annotations

from typing import Any

_SCALARS = ("tone", "background")
_NAMED_LISTS = ("factions", "geography", "races", "power_system", "core_themes")


def validate_world_bible(bible: dict[str, Any]) -> list[str]:
    """Returns a list of error descriptions (empty = legal)."""
    errs: list[str] = []
    for k in _SCALARS:
        v = bible.get(k)
        if not isinstance(v, str) or not v.strip():
            errs.append(f"缺必填分节「{k}」（须非空文本）")
    for k in _NAMED_LISTS:
        items = bible.get(k)
        if not isinstance(items, list) or not items:
            errs.append(f"分节「{k}」至少需 1 项")
            continue
        for i, it in enumerate(items):
            if not isinstance(it, dict) or not str(it.get("name", "")).strip() \
                    or not str(it.get("desc", "")).strip():
                errs.append(f"「{k}」第{i + 1}项缺 name/desc")
    return errs
