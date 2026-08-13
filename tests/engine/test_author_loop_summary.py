"""摘要追加纯函数：append + 超长压缩（update_rolling_summary 已随概要 agent 退役）。"""
from __future__ import annotations

from engine.author_loop.summary import append_summary


def test_append_basic():
    assert append_summary("", "主角抵达。", max_chars=1000) == "主角抵达。"
    assert append_summary("A。", "B。", max_chars=1000) == "A。\nB。"


def test_append_truncates_oldest_when_over_cap():
    base = "句" * 50
    out = append_summary(base, "新事件。", max_chars=20)
    assert out.endswith("新事件。")
    assert len(out) <= 20 + len("新事件。")  #Suppressed early, new events retained
