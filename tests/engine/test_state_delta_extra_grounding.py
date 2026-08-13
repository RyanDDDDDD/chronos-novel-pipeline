"""extra_grounding injects the user prompt for unified delta calls."""
from __future__ import annotations

from engine.archive.archive_hook import ArchiveDeltaContext
from engine.archive.state_delta_call import _build_user


def _ctx(extra: str, mode: str = "cold_start") -> ArchiveDeltaContext:
    return ArchiveDeltaContext(
        char={"name": "甲", "causal_anchors": {"stance": "dominant"}},
        chapter=1, relevant_stages=[], mode=mode, prior=None,
        prior_appearances=[], extra_grounding=extra,
    )


def test_extra_grounding_injected():
    out = _build_user(_ctx("生有角与尾"))
    assert "角色背景设定" in out and "生有角与尾" in out


def test_no_extra_grounding_absent():
    out = _build_user(_ctx(""))
    assert "角色背景设定" not in out


def test_extra_grounding_in_rolling_too():
    out = _build_user(_ctx("生有角与尾", mode="rolling"))
    assert "生有角与尾" in out
