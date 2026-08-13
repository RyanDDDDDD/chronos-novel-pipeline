"""The race field of the cast skeleton enters lore with merge."""
from __future__ import annotations

from engine.setup.cast.parse import merge_cast


def test_merge_carries_race():
    skeleton = [{"given_name": "甲", "role": "r", "gender": "female",
                 "race": "魔族", "causal_anchors": {"stance": "dominant"}}]
    deepdive = [{"given_name": "甲", "physique": {}}]
    out = merge_cast(skeleton, deepdive)
    assert out[0]["race"] == "魔族"


def test_merge_without_race_ok():
    skeleton = [{"given_name": "乙", "role": "r", "gender": "female",
                 "causal_anchors": {"stance": "submissive"}}]
    out = merge_cast(skeleton, [{"given_name": "乙"}])
    assert "race" not in out[0]
