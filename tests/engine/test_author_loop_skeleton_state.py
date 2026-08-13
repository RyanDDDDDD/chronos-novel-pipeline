"""Main engine load_prebuilt_skeleton (read plot prebuilt beats)."""
from __future__ import annotations

import pytest


def test_load_prebuilt_skeleton_reads_plot(monkeypatch):
    import engine.author_loop.build as build_mod

    monkeypatch.setattr(
        build_mod, "fetch_chapter_outline",
        lambda chapter: ("第一章标题", [
            {"index": 0, "title": "s1", "text": "查案粗纲",
             "beats": [{"text": "主角查案"}], "characters": ["甲"]},
            {"index": 1, "title": "s2", "text": "亲密粗纲",
             "beats": [{"text": "亲密场景"}, {"text": "余韵"}], "characters": ["甲", "乙"]},
        ]),
        raising=False,
    )
    segs = build_mod.load_prebuilt_skeleton(1)
    assert len(segs) == 2
    assert segs[0]["beats"][0]["text"] == "主角查案" and segs[1]["characters"] == ["甲", "乙"]
    assert segs[0]["description"] == "查案粗纲"  # 粗大纲留给进入态 seed
    assert [b["text"] for b in segs[1]["beats"]] == ["亲密场景", "余韵"]


def test_load_prebuilt_skeleton_missing_beats_raises(monkeypatch):
    import engine.author_loop.build as build_mod

    monkeypatch.setattr(
        build_mod, "fetch_chapter_outline",
        lambda chapter: ("t", [
            {"index": 0, "stage_num": 1, "beats": [{"text": "有效拍"}], "characters": ["甲"]},
            {"index": 1, "stage_num": 2, "characters": ["乙"]},  # 缺 beats
        ]),
        raising=False,
    )
    with pytest.raises(build_mod.SkeletonNotBuiltError):
        build_mod.load_prebuilt_skeleton(1)


def test_load_prebuilt_skeleton_blank_beat_text_raises(monkeypatch):
    import engine.author_loop.build as build_mod

    monkeypatch.setattr(
        build_mod, "fetch_chapter_outline",
        lambda chapter: ("t", [
            {"index": 0, "stage_num": 1, "beats": [{"text": "  "}], "characters": ["甲"]},
        ]),
        raising=False,
    )
    with pytest.raises(build_mod.SkeletonNotBuiltError):
        build_mod.load_prebuilt_skeleton(1)
