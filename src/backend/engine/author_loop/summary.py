"""摘要追加纯函数（概要 agent 已退役，update_rolling_summary 随之删除；plot setup 仍用 append_summary）。"""
from __future__ import annotations


def append_summary(prev: str, addition: str, *, max_chars: int = 4000) -> str:
    """
Append a summary sentence; if it is too long, the earliest part will be cut off and the tail will be retained (to maintain freshness)."""
    merged = f"{prev}\n{addition}".strip() if prev.strip() else addition.strip()
    if len(merged) <= max_chars:
        return merged
    return merged[-max_chars:]
