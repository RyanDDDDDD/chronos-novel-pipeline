"""Upstream-write guard: setup-chat plot writes invalidate a running author_loop
chapter (spec D13/D15, §6). The engine never imports the hub -- the hub registers
an async callback here at construction time, mirroring the existing emit-injection
direction."""
from __future__ import annotations

from collections.abc import Awaitable, Callable

ALL_CHAPTERS: tuple[int, int] = (1, 10**9)

_OPEN_ENDED_TOOLS = frozenset({"generate_one_chapter", "write_character_archive"})
_SINGLE_CHAPTER_TOOLS = frozenset({
    "patch_chapter", "write_chapter_skeleton", "patch_text_fragment", "auto_expand_skeleton",
})
_ALL_CHAPTER_TOOLS = frozenset({"auto_build_setup"})

_guard: Callable[[int, int, str], Awaitable[None]] | None = None


def _chapter_arg(args: dict) -> int | None:
    try:
        return int(args.get("chapter"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def affected_chapter_range(tool_name: str, args: dict) -> tuple[int, int] | None:
    """Inclusive chapter range a write tool invalidates; None = no chapters.

    This table is a manual inventory (spec §6): keep it next to the tools and
    update it when plot-affecting tools change. A plot tool whose chapter arg
    fails to parse conservatively falls back to ALL_CHAPTERS."""
    if tool_name in _ALL_CHAPTER_TOOLS:
        return ALL_CHAPTERS
    if tool_name in _OPEN_ENDED_TOOLS:
        ch = _chapter_arg(args)
        return (ch, 10**9) if ch is not None else ALL_CHAPTERS
    if tool_name in _SINGLE_CHAPTER_TOOLS:
        ch = _chapter_arg(args)
        return (ch, ch) if ch is not None else ALL_CHAPTERS
    return None


def set_author_guard(fn: Callable[[int, int, str], Awaitable[None]] | None) -> None:
    global _guard
    _guard = fn


async def stop_author_if_affected(lo: int, hi: int, reason: str) -> None:
    if _guard is not None:
        await _guard(lo, hi, reason)
