import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "backend"))

from repositories.plot_outline import stages_to_segments  # noqa: E402


def test_stages_to_segments_builds_segment_shape(monkeypatch):
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters", lambda text: ["男主甲"],
    )
    ch_data = {
        "title": "测试章",
        "stages": [
            {
                "title": "阶段甲",
                "description": "甲剧情",
                "location": "甲地",
                "clothing": {},
            },
        ],
    }
    title, segs = stages_to_segments(ch_data)
    assert title == "测试章"
    assert segs[0]["index"] == 0
    assert segs[0]["title"] == "阶段甲"
    assert segs[0]["location"] == "甲地"
    assert segs[0]["text"] == "甲剧情"   #text is initialized to the original outline (plot/text merged)
    assert "plot" not in segs[0]
    assert segs[0]["characters"] == ["男主甲"]
    assert "char_roles" not in segs[0]


def test_stages_to_segments_carries_beats():
    ch_data = {
        "title": "测试章",
        "stages": [
            {
                "stage_num": 2,
                "title": "阶段甲",
                "description": "甲剧情",
                "beats": [{"text": "扩写拍一", "dialogue": []}],
                "location": "甲地",
                "characters": {},
            },
        ],
    }
    _, segs = stages_to_segments(ch_data)
    assert segs[0]["stage_num"] == 2
    assert segs[0]["beats"] == [{"text": "扩写拍一", "dialogue": []}]


def test_stages_to_segments_filters_summary_title():
    title, segs = stages_to_segments({"title": "第6章基础剧情概要", "stages": []})
    assert title is None
    assert segs == []
