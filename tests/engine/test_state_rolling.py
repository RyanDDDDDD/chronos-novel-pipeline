"""Tests for Rolling State Generation — Documentation Objects / Input Assembly / Output Parsing."""
import os

import pytest
from utils.paths import ARCHIVE_HOOKS_DIR

_STATE_CORE_DIR = os.path.join(ARCHIVE_HOOKS_DIR, "state_core")


def _patch_rubrics(monkeypatch, role_keyed: dict) -> None:
    role_axes = next(iter(role_keyed.values()))
    flat = {
        ax: (spec.get("levels") if isinstance(spec, dict) else spec)
        for ax, spec in role_axes.items()
    }
    monkeypatch.setattr("engine.archive.sliders.character_rubrics", lambda _n: flat)


def test_state_message_contains_anchors_seed_plot_and_sliders(monkeypatch):
    from engine.archive.archive_hook import ArchiveDeltaContext
    from engine.archive.hook_loader import DELTA_HOOKS
    from engine.archive.state_delta_call import _build_system, _build_user

    rubrics = {"甲": {
        "投入": {"direction": -1, "levels": {"4": "防线紧绷"}},
        "依恋": {"direction": 1, "levels": {"1": "萌芽"}},
    }}
    _patch_rubrics(monkeypatch, rubrics)

    char = {
        "name": "女主丙",
        "role": "甲",
        "causal_anchors": {"起点": "少宗主的骄傲",
                           "执念": "灵魂依然高贵", "渴望": "沦为母犬"},
    }
    relevant = [
        {"stage_num": 1, "description": "当众被贯穿防线", "location": "大殿", "archetype": ""},
    ]
    prior = {"sliders": {"投入": 4, "依恋": 1},
             "state": {"physiology": "肌肉紧绷", "psychology": "强撑抗拒"}}
    ctx = ArchiveDeltaContext(
        char=char, chapter=4, relevant_stages=relevant,
        mode="rolling", prior=prior, prior_appearances=[], call_llm=None,
    )
    combined = _build_system(ctx) + _build_user(ctx)
    assert "少宗主的骄傲" in combined and "沦为母犬" in combined
    assert "防线紧绷" in combined and "萌芽" in combined
    assert '"投入": 4' not in combined
    assert "当众被贯穿防线" in combined


@pytest.mark.asyncio
async def test_parse_state_output_converts_slider_labels(monkeypatch):
    from engine.archive.archive_hook import ArchiveDeltaContext
    from engine.archive.hook_loader import DELTA_HOOKS
    from engine.archive.state_delta_call import run_state_delta_call

    rubrics = {"甲": {
        "投入": {"direction": -1, "levels": {"2": "理智旁观"}},
        "依恋": {"direction": 1, "levels": {"3": "渴求"}},
    }}
    _patch_rubrics(monkeypatch, rubrics)

    async def _call(system, user, label):
        return {"stages": {"1": {
            "thought_process": {"delta": "防线被击穿", "escalation": "宫颈阈值降低"},
            "delta": {
                "sliders": {"投入": "理智旁观", "依恋": "渴求"},
                "state": {"physiology": "身体抢先迎上", "psychology": "理智旁观"},
            },
        }}}

    ctx = ArchiveDeltaContext(
        char={"name": "女主丙", "role": "甲", "causal_anchors": {"起点": "x"}},
        chapter=4, relevant_stages=[{"stage_num": 1, "location": "殿", "description": "x", "archetype": ""}],
        mode="rolling", prior=None, prior_appearances=[], call_llm=_call,
    )
    parsed = await run_state_delta_call(ctx)
    s1 = parsed["1"]
    assert s1["delta"]["sliders"] == {"投入": 2, "依恋": 3}
    assert s1["thought_process"]["delta"] == "防线被击穿"
    assert s1["delta"]["state"]["physiology"] == "身体抢先迎上"


@pytest.mark.asyncio
async def test_parse_state_output_unmatched_label_keeps_warn(monkeypatch):
    from engine.archive.archive_hook import ArchiveDeltaContext
    from engine.archive.state_delta_call import run_state_delta_call

    rubrics = {"submissive": {
        "resistance": {"direction": -1, "levels": {"2": "理智旁观"}},
    }}
    _patch_rubrics(monkeypatch, rubrics)

    async def _call(system, user, label):
        return {"stages": {"1": {"delta": {
            "sliders": {"resistance": "乱写的"},
            "state": {"physiology": "x", "psychology": "y"},
        }}}}

    ctx = ArchiveDeltaContext(
        char={"name": "女主丙", "causal_anchors": {"stance": "submissive"}},
        chapter=4, relevant_stages=[{"stage_num": 1, "location": "殿", "description": "x", "archetype": ""}],
        mode="rolling", prior=None, prior_appearances=[], call_llm=_call,
    )
    parsed = await run_state_delta_call(ctx)
    assert parsed["1"]["delta"]["sliders"].get("resistance") is None


@pytest.mark.asyncio
async def test_parse_delta_output_coerces_string_thought_process():
    """When LLM writes thought_process as a string, the parsing layer specification is dict."""
    from engine.archive.archive_hook import ArchiveDeltaContext
    from engine.archive.state_delta_call import run_state_delta_call

    async def _call(system, user, label):
        return {"stages": {"1": {
            "thought_process": "本 stage 剧情推动掌控加深",
            "delta": {"state": {"physiology": "p", "psychology": "q"}},
        }}}

    ctx = ArchiveDeltaContext(
        char={"name": "男主甲", "causal_anchors": {"stance": "dominant"}},
        chapter=4, relevant_stages=[{"stage_num": 1, "location": "殿", "description": "x", "archetype": ""}],
        mode="rolling", prior=None, prior_appearances=[], call_llm=_call,
    )
    parsed = await run_state_delta_call(ctx)
    assert parsed["1"]["thought_process"] == {"delta": "本 stage 剧情推动掌控加深"}


def test_validator_accepts_thought_process_and_sliders():
    from engine.archive.archive_error import assert_valid
    archive = {
        "name": "女主丙",
        "role": "配角",
        "physique": "纤细",
        "extensions": {},
        "thought_process": {"delta": "d", "escalation": "e"},
        "sliders": {"resistance": 2, "addiction": 3},
    }
    assert_valid(archive)


def test_validator_accepts_profile_without_state_or_clothing():
    from engine.archive.archive_error import assert_valid
    assert_valid({"name": "x", "role": "r", "extensions": {}})


def test_state_builder_prompt_has_required_sections():
    p = os.path.join(_STATE_CORE_DIR, "state_builder.md")
    text = open(p, encoding="utf-8").read()
    assert "thought_process" in text and "delta" in text
    assert "因果锚点" in text and "sliders" in text
    assert "标签" in text or "档位" in text
    assert "不复述" in text or "不得复述" in text or "脱离" in text
    assert "上一次" in text or "滚动" in text


def test_state_message_lists_closed_slider_tags(monkeypatch):
    from engine.archive.archive_hook import ArchiveDeltaContext
    from engine.archive.hook_loader import DELTA_HOOKS
    from engine.archive.state_delta_call import _build_system

    rubrics = {"甲": {
        "投入": {"direction": -1, "levels": {
            "5": "意志完整。主动对抗。", "0": "彻底交付。无抵抗。"}},
        "依恋": {"direction": 1, "levels": {
            "0": "毫无。只有排斥。", "5": "鼎炉。常年饥渴。"}},
    }}
    _patch_rubrics(monkeypatch, rubrics)

    ctx = ArchiveDeltaContext(
        char={"name": "女主丙", "role": "甲",
              "causal_anchors": {"起点": "w", "执念": "l", "渴望": "n"}},
        chapter=4, relevant_stages=[{"stage_num": 1, "location": "殿", "description": "x", "archetype": ""}],
        mode="rolling", prior=None, prior_appearances=[], call_llm=None,
    )
    msg = _build_system(ctx)
    assert "意志完整" in msg and "彻底交付" in msg
    assert "原样复制" in msg or "从以下" in msg


def test_state_builder_prompt_hardened():
    p = os.path.join(_STATE_CORE_DIR, "state_builder.md")
    text = open(p, encoding="utf-8").read()
    assert "原样复制" in text
    assert "脚边" in text or "被褥" in text or "之间" in text


def test_state_builder_prompt_has_slider_gating():
    """
Knife ①: address_ref/self_ref/demeanor is gated by slider; state/organ alienation/gender is not gated
(state must be re-derived every stage to track current-stage content while chaining from the prior snapshot)."""
    p = os.path.join(_STATE_CORE_DIR, "state_builder.md")
    text = open(p, encoding="utf-8").read()
    assert "slider 门控" in text                       #Gating rule segment exists
    assert "无变化" in text and "沿用" in text          #sliders remain unchanged → inherited and not output
    #address_ref/self_ref remain gated.
    assert text.count("受 slider 门控") >= 2            #address_ref/self_ref (+look)
    #state is explicitly exempted from the gate and mandatory every stage.
    assert "不受 slider 门控" in text
    assert "每个出场 stage 都必须重新推演并输出" in text
    assert "每个 stage 的 delta 必须含 `state`" in text


def test_relationship_block_delegates_to_social_relations(monkeypatch):
    """_relationship_block thin package: transposed social_relations.relations_for_character."""
    import hooks.archive.social_relations.social_relations as social_relations

    monkeypatch.setattr(
        social_relations, "relations_for_character",
        lambda name, present: f"REL({name},{len(present)})",
    )
    from engine.archive.hook_loader import DELTA_HOOKS
    hook = next(h for h in DELTA_HOOKS if getattr(h, "name", "") == "state")
    assert hook._relationship_block("女甲", ["女甲", "女乙"]) == "REL(女甲,2)"


def test_relationship_block_blank_without_name():
    """
No name → Empty block (downgraded)."""
    from engine.archive.hook_loader import DELTA_HOOKS
    hook = next(h for h in DELTA_HOOKS if getattr(h, "name", "") == "state")
    assert hook._relationship_block("", ["女甲"]) == ""
