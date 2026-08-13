"""Tests for state_derive_schema prompt builders and normalization."""
from __future__ import annotations

import pytest

from context.content_packs import StateFieldSpec
from context.state_derive_schema import (
    build_init_sys,
    build_init_sys_from_prose,
    format_state_field_value,
    normalize_character_states,
)

# scored_desc 是 content pack 才会贡献的字段类别（baseline 五字段都是 text）；这里合成一个
# 字段而不是借用任何具体 pack 的真实字段名，让这些测试不依赖哪个 pack 装没装。
_SYNTHETIC_SCORED_FIELD = StateFieldSpec(
    key="stress_level", label="压力值", kind="scored_desc", derive_hint="压力值：scored_desc",
)


@pytest.fixture
def scored_field(monkeypatch):
    import context.state_derive_schema as schema

    monkeypatch.setattr(schema, "state_derive_fields", lambda: [_SYNTHETIC_SCORED_FIELD])
    return _SYNTHETIC_SCORED_FIELD


def test_build_init_sys_includes_baseline_keys():
    sys_prompt = build_init_sys()
    for key in ("psychology", "posture", "clothing", "action", "demeanor"):
        assert key in sys_prompt


def test_normalize_scored_desc_clamps_score(scored_field):
    parsed = {"甲": {"stress_level": {"score": 150, "desc": "强烈"}}}
    out = normalize_character_states(parsed, strict_scored_desc=True)
    assert out == {"甲": {"stress_level": {"score": 100, "desc": "强烈"}}}


def test_normalize_scored_desc_strict_failure(scored_field):
    parsed = {"甲": {"stress_level": {"score": "bad", "desc": ""}}}
    assert normalize_character_states(parsed, strict_scored_desc=True) is None


def test_normalize_scored_desc_loose_skips_invalid(scored_field):
    parsed = {"甲": {"stress_level": {"score": "bad", "desc": ""}, "psychology": "紧张"}}
    out = normalize_character_states(parsed, strict_scored_desc=False)
    assert out == {"甲": {"psychology": "紧张"}}


def test_build_init_sys_from_prose_mentions_prose_not_opening_instruction():
    sys_prompt = build_init_sys_from_prose()
    assert "正文" in sys_prompt
    assert "开场" not in sys_prompt


def test_build_init_sys_from_prose_includes_field_schema_and_json_example():
    from context.content_packs import state_derive_fields

    sys_prompt = build_init_sys_from_prose()
    for field in state_derive_fields():
        assert field.key in sys_prompt


def test_format_state_field_value_scored_desc(scored_field):
    assert format_state_field_value(
        "stress_level", {"score": 80, "desc": "身体发热"},
    ) == "80/100，身体发热"
