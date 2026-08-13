import json

import pytest
from engine.story_sandbox.profile_mutate import (
    _ALLOWED_PROFILE_FIELDS,
    _normalize_profile_delta,
    build_profile_mutate_node,
)

_RUBRICS = {"侵蚀度": {"0": "清醒", "1": "动摇", "2": "沦陷"}}


async def _identity_guard_text(text: str) -> str:
    return text


def test_allowed_profile_fields_has_exactly_eight_fields():
    assert _ALLOWED_PROFILE_FIELDS == {
        "sliders", "physique", "gender", "race",
        "personality", "identity_background", "hobbies", "verbal_tic",
    }


def test_commit_previous_round_merges_prior_rounds_mutation_into_overlay():
    from engine.story_sandbox.profile_mutate import _commit_previous_round

    committed = _commit_previous_round({
        "turns": [{"profile_mutation": {"甲": {"race": "精灵"}}}],
        "character_profile": {"甲": {"personality": "外冷内热"}},
    })
    assert committed == {"甲": {"personality": "外冷内热", "race": "精灵"}}


def test_commit_previous_round_merges_sliders_per_axis_not_wholesale():
    """Regression: a delta reporting only ONE axis must not wipe out an already-accumulated
    OTHER axis in character_profile's sliders dict -- this is the exact bug that dropped a
    character's 沦陷程度 axis in production once a later round's mutation only re-touched
    身体异化, silently reverting 沦陷程度 to baseline in the rendered card."""
    from engine.story_sandbox.profile_mutate import _commit_previous_round

    committed = _commit_previous_round({
        "turns": [{"profile_mutation": {"甲": {"sliders": {"身体异化": {"level": 2, "text": "触须蔓延"}}}}}],
        "character_profile": {
            "甲": {"sliders": {"沦陷程度": {"level": 2, "text": "开始期待"}, "身体异化": {"level": 1, "text": "初现"}}},
        },
    })
    assert committed == {
        "甲": {"sliders": {
            "沦陷程度": {"level": 2, "text": "开始期待"},
            "身体异化": {"level": 2, "text": "触须蔓延"},
        }},
    }


def test_commit_previous_round_merges_physique_per_slot_not_wholesale():
    from engine.story_sandbox.profile_mutate import _commit_previous_round

    committed = _commit_previous_round({
        "turns": [{"profile_mutation": {"甲": {"physique": {"刺青": "已成形"}}}}],
        "character_profile": {"甲": {"physique": {"小腹": "隆起轮廓"}}},
    })
    assert committed == {"甲": {"physique": {"小腹": "隆起轮廓", "刺青": "已成形"}}}


def test_commit_previous_round_merges_hobbies_as_union_not_wholesale():
    """Regression: a delta reporting only a newly-discovered hobby must not wipe out
    previously-confirmed hobbies -- same failure class as the sliders/physique per-axis/per-slot
    fix above, just for hobbies' list-of-independent-items shape."""
    from engine.story_sandbox.profile_mutate import _commit_previous_round

    committed = _commit_previous_round({
        "turns": [{"profile_mutation": {"甲": {"hobbies": ["剑术"]}}}],
        "character_profile": {"甲": {"hobbies": ["炼金", "占卜"]}},
    })
    assert committed == {"甲": {"hobbies": ["炼金", "占卜", "剑术"]}}


def test_commit_previous_round_merges_hobbies_dedupes_repeated_item():
    from engine.story_sandbox.profile_mutate import _commit_previous_round

    committed = _commit_previous_round({
        "turns": [{"profile_mutation": {"甲": {"hobbies": ["炼金", "剑术"]}}}],
        "character_profile": {"甲": {"hobbies": ["炼金"]}},
    })
    assert committed == {"甲": {"hobbies": ["炼金", "剑术"]}}


def test_commit_previous_round_returns_none_when_no_turns_yet():
    from engine.story_sandbox.profile_mutate import _commit_previous_round

    assert _commit_previous_round({"character_profile": {}}) is None


def test_commit_previous_round_returns_none_when_previous_round_had_no_mutation():
    from engine.story_sandbox.profile_mutate import _commit_previous_round

    assert _commit_previous_round({
        "turns": [{"profile_mutation": None}], "character_profile": {"甲": {"race": "精灵"}},
    }) is None


def test_normalize_profile_delta_strips_unknown_fields(monkeypatch):
    out = _normalize_profile_delta("甲", {"psychology": "紧张", "race": "精灵"}, {})
    assert out == {"race": "精灵"}


def test_normalize_profile_delta_keeps_valid_slider_and_legal_level(monkeypatch):
    out = _normalize_profile_delta(
        "甲", {"sliders": {"侵蚀度": {"level": 1, "text": "开始动摇"}}}, _RUBRICS,
    )
    assert out == {"sliders": {"侵蚀度": {"level": 1, "text": "开始动摇"}}}


def test_normalize_profile_delta_drops_only_the_out_of_range_axis(monkeypatch):
    out = _normalize_profile_delta(
        "甲",
        {"sliders": {
            "侵蚀度": {"level": 1, "text": "动摇"},
            "越界轴": {"level": 99, "text": "非法"},
        }},
        _RUBRICS,
    )
    assert out == {"sliders": {"侵蚀度": {"level": 1, "text": "动摇"}}}


def test_normalize_profile_delta_drops_malformed_slider_shape(monkeypatch):
    out = _normalize_profile_delta("甲", {"sliders": {"侵蚀度": "裸字符串"}}, {})
    assert "sliders" not in out


def test_normalize_profile_delta_drops_non_list_hobbies(monkeypatch):
    out = _normalize_profile_delta("甲", {"hobbies": "不是列表"}, {})
    assert "hobbies" not in out


def test_normalize_profile_delta_keeps_hobbies_list(monkeypatch):
    out = _normalize_profile_delta("甲", {"hobbies": ["炼金", "  ", "剑术"]}, {})
    assert out == {"hobbies": ["炼金", "剑术"]}


@pytest.mark.asyncio
async def test_profile_mutate_node_skips_llm_call_when_no_event_this_turn():
    called = []

    async def call_llm(_system, _user):
        called.append(True)
        return "{}"

    node = build_profile_mutate_node(1, call_llm, _identity_guard_text)
    result = await node({"event_log_entries_this_turn": [], "final_text": "正文"})
    assert result == {"profile_mutation_this_turn": None, "relationship_mutation_this_turn": None}
    assert called == []


@pytest.mark.asyncio
async def test_profile_mutate_node_reports_nothing_when_llm_returns_empty_object():
    async def call_llm(_system, _user):
        return "{}"

    node = build_profile_mutate_node(1, call_llm, _identity_guard_text)
    result = await node({
        "event_log_entries_this_turn": [{"summary": "甲变身了"}], "final_text": "甲变身了。",
        "character_profile": {},
    })
    assert result == {"profile_mutation_this_turn": None, "relationship_mutation_this_turn": None}


@pytest.mark.asyncio
async def test_profile_mutate_node_soft_skips_on_unparseable_json():
    async def call_llm(_system, _user):
        return "不是JSON"

    node = build_profile_mutate_node(1, call_llm, _identity_guard_text)
    result = await node({
        "event_log_entries_this_turn": [{"summary": "甲变身了"}], "final_text": "甲变身了。",
        "character_profile": {},
    })
    assert result == {"profile_mutation_this_turn": None, "relationship_mutation_this_turn": None}


@pytest.mark.asyncio
async def test_profile_mutate_node_does_not_merge_this_round_mutation_into_character_profile(
    monkeypatch,
):
    """This round's own mutation must stay out of the confirmed character_profile overlay until
    a LATER round commits it (see _commit_previous_round) -- otherwise a rewrite of this same
    round could never undo it."""

    async def call_llm(_system, _user):
        return '{"甲": {"race": "精灵"}}'

    node = build_profile_mutate_node(0, call_llm, _identity_guard_text)
    result = await node({
        "event_log_entries_this_turn": [{"summary": "甲变成了精灵"}],
        "final_text": "甲的耳朵变尖了。",
        "character_profile": {"甲": {"personality": "外冷内热"}},
        "active_cast": {"甲": 0},
    })
    assert "character_profile" not in result
    assert result["profile_mutation_this_turn"] == {"甲": {"race": "精灵"}}


@pytest.mark.asyncio
async def test_profile_mutate_node_drops_characters_with_no_valid_fields(monkeypatch):

    async def call_llm(_system, _user):
        return '{"甲": {"psychology": "紧张"}, "乙": {"race": "精灵"}}'

    node = build_profile_mutate_node(0, call_llm, _identity_guard_text)
    result = await node({
        "event_log_entries_this_turn": [{"summary": "事件"}], "final_text": "正文",
        "character_profile": {}, "active_cast": {"乙": 0},
    })
    assert "甲" not in (result.get("profile_mutation_this_turn") or {})
    assert result["profile_mutation_this_turn"] == {"乙": {"race": "精灵"}}


@pytest.mark.asyncio
async def test_profile_mutate_node_drops_passerby_and_off_roster_characters(monkeypatch):
    async def call_llm(_system, _user):
        return json.dumps(
            {
                "路人甲": {"race": "精灵"},
                "甲": {"race": "恶魔"},
                "设定外角色": {"personality": "神秘"},
            },
            ensure_ascii=False,
        )

    node = build_profile_mutate_node(0, call_llm, _identity_guard_text)
    result = await node({
        "event_log_entries_this_turn": [{"summary": "事件"}], "final_text": "正文",
        "character_profile": {},
        "active_cast": {"甲": 0, "路人甲": 0},
        "passerby_names": ["路人甲"],
    })
    assert result["profile_mutation_this_turn"] == {"甲": {"race": "恶魔"}}


@pytest.mark.asyncio
async def test_profile_mutate_node_drops_characters_not_in_active_cast(monkeypatch):
    async def call_llm(_system, _user):
        return '{"王五": {"race": "精灵"}, "司马相如": {"race": "精灵"}}'

    node = build_profile_mutate_node(8, call_llm, _identity_guard_text)
    result = await node({
        "event_log_entries_this_turn": [{"summary": "事件"}], "final_text": "正文",
        "character_profile": {}, "instruction_this_turn": "继续",
    })
    assert result["profile_mutation_this_turn"] is None


@pytest.mark.asyncio
async def test_profile_mutate_node_keeps_formal_present_characters(monkeypatch):
    monkeypatch.setattr("engine.memory_recall.entity_index.scan_characters", lambda text: [])

    async def call_llm(_system, _user):
        return '{"王五": {"race": "精灵"}, "司马相如": {"race": "精灵"}}'

    node = build_profile_mutate_node(8, call_llm, _identity_guard_text)
    result = await node({
        "event_log_entries_this_turn": [{"summary": "事件"}], "final_text": "正文",
        "character_profile": {}, "instruction_this_turn": "继续",
        "active_cast": {"王五": 0, "司马相如": 0},
    })
    assert result["profile_mutation_this_turn"] == {
        "王五": {"race": "精灵"},
        "司马相如": {"race": "精灵"},
    }


@pytest.mark.asyncio
async def test_profile_mutate_node_forces_llm_call_on_tenth_round_even_without_event():
    """turns 已有 9 轮 -> 这是第 10 轮，即使 event_log 判"没事"也要强制跑一次判断。"""
    called = []

    async def call_llm(_system, _user):
        called.append(True)
        return "{}"

    node = build_profile_mutate_node(1, call_llm, _identity_guard_text)
    result = await node({
        "event_log_entries_this_turn": [], "final_text": "正文",
        "character_profile": {}, "turns": [{}] * 9,
    })
    assert called == [True]
    assert result == {"profile_mutation_this_turn": None, "relationship_mutation_this_turn": None}


@pytest.mark.asyncio
async def test_profile_mutate_node_does_not_force_on_ninth_round():
    """turns 已有 8 轮 -> 这是第 9 轮，不是 10 的倍数，event_log 没事就照常跳过。"""
    called = []

    async def call_llm(_system, _user):
        called.append(True)
        return "{}"

    node = build_profile_mutate_node(1, call_llm, _identity_guard_text)
    result = await node({
        "event_log_entries_this_turn": [], "final_text": "正文",
        "character_profile": {}, "turns": [{}] * 8,
    })
    assert called == []
    assert result == {"profile_mutation_this_turn": None, "relationship_mutation_this_turn": None}


@pytest.mark.asyncio
async def test_profile_mutate_node_forces_on_twentieth_round():
    """确认不是只硬编码判断"恰好第 10 轮"，第 20 轮同样强制。"""
    called = []

    async def call_llm(_system, _user):
        called.append(True)
        return "{}"

    node = build_profile_mutate_node(1, call_llm, _identity_guard_text)
    result = await node({
        "event_log_entries_this_turn": [], "final_text": "正文",
        "character_profile": {}, "turns": [{}] * 19,
    })
    assert called == [True]
    assert result == {"profile_mutation_this_turn": None, "relationship_mutation_this_turn": None}


@pytest.mark.asyncio
async def test_profile_mutate_node_forces_on_tenth_round_for_rewrite_variant():
    """rewrite 场景下 is_rewrite=True 时,轮数计算不 +1(重写的是 turns[-1] 那一轮本身,不是新追加
    的一轮)-- turns 已有 10 轮、正在重写其中第 10 轮时也要强制触发。"""
    called = []

    async def call_llm(_system, _user):
        called.append(True)
        return "{}"

    node = build_profile_mutate_node(1, call_llm, _identity_guard_text, is_rewrite=True)
    result = await node({
        "event_log_entries_this_turn": [], "final_text": "正文",
        "character_profile": {}, "turns": [{}] * 10,
    })
    assert called == [True]
    assert result == {"profile_mutation_this_turn": None, "relationship_mutation_this_turn": None}


@pytest.mark.asyncio
async def test_profile_mutate_node_guard_text_rewrites_physique_slots(monkeypatch):
    forbidden = "违规词"
    guard_calls: list[str] = []

    async def guard_text(text: str) -> str:
        guard_calls.append(text)
        return text.replace(forbidden, "安全词")

    async def call_llm(_system, _user):
        return json.dumps(
            {"甲": {"physique": {"horns": f"角上{forbidden}", "tail": ""}}},
            ensure_ascii=False,
        )

    node = build_profile_mutate_node(0, call_llm, guard_text)
    result = await node({
        "event_log_entries_this_turn": [{"summary": "事件"}],
        "final_text": "正文",
        "character_profile": {},
        "active_cast": {"甲": 0},
    })

    mutation = result["profile_mutation_this_turn"]["甲"]
    assert forbidden not in mutation["physique"]["horns"]
    assert "安全词" in mutation["physique"]["horns"]
    assert mutation["physique"]["tail"] == ""
    assert guard_calls == [f"角上{forbidden}"]


@pytest.mark.asyncio
async def test_profile_mutate_node_guard_text_rewrites_free_text_leaves_only(monkeypatch):
    forbidden = "违规词"
    guard_calls: list[str] = []

    monkeypatch.setattr("engine.story_sandbox.profile_mutate.character_rubrics", lambda _name: _RUBRICS)

    async def guard_text(text: str) -> str:
        guard_calls.append(text)
        return text.replace(forbidden, "安全词")

    async def call_llm(_system, _user):
        return json.dumps(
            {
                "甲": {
                    "sliders": {"侵蚀度": {"level": 2, "text": f"轴叙述含{forbidden}"}},
                    "identity_background": f"背景含{forbidden}",
                    "hobbies": [f"爱好含{forbidden}", "正常爱好"],
                    "gender": "xeno",
                    "race": "精灵",
                },
            },
            ensure_ascii=False,
        )

    node = build_profile_mutate_node(0, call_llm, guard_text)
    result = await node({
        "event_log_entries_this_turn": [{"summary": "事件"}],
        "final_text": "正文",
        "character_profile": {},
        "active_cast": {"甲": 0},
    })

    mutation = result["profile_mutation_this_turn"]["甲"]
    assert mutation["sliders"]["侵蚀度"]["level"] == 2
    assert forbidden not in mutation["sliders"]["侵蚀度"]["text"]
    assert "安全词" in mutation["sliders"]["侵蚀度"]["text"]
    assert forbidden not in mutation["identity_background"]
    assert "安全词" in mutation["identity_background"]
    assert forbidden not in mutation["hobbies"][0]
    assert "安全词" in mutation["hobbies"][0]
    assert mutation["hobbies"][1] == "正常爱好"
    assert mutation["gender"] == "xeno"
    assert mutation["race"] == "精灵"
    assert "xeno" not in guard_calls
    assert "精灵" not in guard_calls
    assert len(guard_calls) == 4


@pytest.mark.asyncio
async def test_profile_mutate_node_commits_previous_round_on_a_fresh_turn(monkeypatch):

    async def call_llm(_system, _user):
        return "{}"  # this (new) round itself produces nothing

    node = build_profile_mutate_node(1, call_llm, _identity_guard_text)
    result = await node({
        "event_log_entries_this_turn": [{"summary": "无关事件"}],
        "final_text": "正文",
        "character_profile": {"甲": {"personality": "外冷内热"}},
        "turns": [{"profile_mutation": {"甲": {"race": "精灵"}}}],
    })
    assert result["character_profile"] == {"甲": {"personality": "外冷内热", "race": "精灵"}}
    assert result["profile_mutation_this_turn"] is None


@pytest.mark.asyncio
async def test_profile_mutate_node_does_not_commit_on_rewrite(monkeypatch):
    """is_rewrite=True must never call _commit_previous_round -- the round being rewritten was
    never committed under the new deferred-commit design, so there's nothing to (re-)commit."""

    async def call_llm(_system, _user):
        return "{}"

    node = build_profile_mutate_node(1, call_llm, _identity_guard_text, is_rewrite=True)
    result = await node({
        "event_log_entries_this_turn": [{"summary": "无关事件"}],
        "final_text": "正文",
        "character_profile": {},
        "turns": [{"profile_mutation": {"甲": {"race": "精灵"}}}],
    })
    assert "character_profile" not in result


@pytest.mark.asyncio
async def test_profile_mutate_node_rewrite_then_next_round_only_commits_the_rewritten_mutation(
    monkeypatch,
):
    """Regression for the pre-fix bug: the old code merged a round's mutation into
    character_profile immediately, so a rewrite of that same round could never undo it. Under
    the deferred design, only whatever profile_mutation ends up on turns[-1] (i.e. survives any
    rewrite) is ever committed -- simulated here by turns[-1] already reflecting the post-rewrite
    result (race: 精灵), with no trace of a hypothetical earlier, since-discarded attempt."""

    async def call_llm(_system, _user):
        return "{}"

    node = build_profile_mutate_node(1, call_llm, _identity_guard_text)
    result = await node({
        "event_log_entries_this_turn": [], "final_text": "正文",
        "character_profile": {},
        "turns": [{"profile_mutation": {"甲": {"race": "精灵"}}}],
    })
    assert result["character_profile"] == {"甲": {"race": "精灵"}}


def test_render_user_omits_roster_hint_when_present_not_set():
    from engine.story_sandbox.profile_mutate import _render_user
    user = _render_user({"character_profile": {}, "final_text": "正文"}, 3)
    assert "在场角色" not in user


def test_render_user_includes_active_cast_roster_hint(monkeypatch):
    from engine.story_sandbox.profile_mutate import _render_user

    monkeypatch.setattr(
        "engine.story_sandbox.profile_mutate._resolve_baseline_profile",
        lambda name, chapter: {},
    )
    user = _render_user({
        "character_profile": {}, "final_text": "正文",
        "active_cast": {"高木柔柔": 0, "林昭然": 0},
    }, 3)
    assert "在场正式角色" in user
    assert "高木柔柔" in user and "林昭然" in user


def test_render_user_excludes_passerby_from_formal_roster(monkeypatch):
    from engine.story_sandbox.profile_mutate import _render_user

    monkeypatch.setattr(
        "engine.story_sandbox.profile_mutate._resolve_baseline_profile",
        lambda name, chapter: {},
    )
    user = _render_user({
        "character_profile": {}, "final_text": "正文",
        "active_cast": {"甲": 0, "路人甲": 0},
        "passerby_names": ["路人甲"],
    }, 3)
    assert "甲" in user
    assert "路人甲" not in user


def test_render_user_merges_baseline_with_session_overlay_for_active_cast(monkeypatch):
    from engine.story_sandbox.profile_mutate import _render_user

    monkeypatch.setattr(
        "engine.story_sandbox.profile_mutate._resolve_baseline_profile",
        lambda name, chapter: (
            {"race": "人类", "personality": "沉稳"} if name == "高木柔柔" else {}
        ),
    )
    user = _render_user({
        "character_profile": {"高木柔柔": {"personality": "外冷内热"}},
        "final_text": "正文", "active_cast": {"高木柔柔": 0},
    }, 3)
    assert '"race": "人类"' in user
    assert '"personality": "外冷内热"' in user
    assert "沉稳" not in user


def test_render_user_shows_baseline_alone_when_no_session_overlay_yet(monkeypatch):
    from engine.story_sandbox.profile_mutate import _render_user

    monkeypatch.setattr(
        "engine.story_sandbox.profile_mutate._resolve_baseline_profile",
        lambda name, chapter: {"race": "精灵"},
    )
    user = _render_user({
        "character_profile": {}, "final_text": "正文", "active_cast": {"林昭然": 0},
    }, 3)
    assert '"race": "精灵"' in user


def test_render_user_falls_back_to_overlay_only_when_active_cast_empty(monkeypatch):
    from engine.story_sandbox.profile_mutate import _render_user

    calls: list[str] = []
    monkeypatch.setattr(
        "engine.story_sandbox.profile_mutate._resolve_baseline_profile",
        lambda name, chapter: calls.append(name) or {},
    )
    user = _render_user(
        {"character_profile": {"甲": {"race": "精灵"}}, "final_text": "正文", "active_cast": {}}, 3,
    )
    assert calls == []
    assert "角色此前的档案突变记录" in user


def test_resolve_baseline_profile_filters_to_allowed_fields_and_normalizes_sliders(monkeypatch):
    from engine.story_sandbox.profile_mutate import _resolve_baseline_profile

    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.chapter_state.resolve_card_state",
        lambda name, chapter, stage: {
            "role": "同质堕落型", "location": "王都",
            "personality": "外冷内热", "gender": "female", "race": "精灵",
            "identity_background": "没落贵族", "verbal_tic": "呢",
            "physique": {"horns": "有一对小角"},
            "hobbies": ["炼金"],
            "sliders": {"侵蚀度": {"level": 1, "text": "开始动摇"}, "抗拒度": 2},
        },
    )
    monkeypatch.setattr("engine.story_sandbox.profile_mutate.character_rubrics", lambda _name: _RUBRICS)

    out = _resolve_baseline_profile("甲", 3)

    assert out == {
        "personality": "外冷内热", "gender": "female", "race": "精灵",
        "identity_background": "没落贵族", "verbal_tic": "呢",
        "physique": {"horns": "有一对小角"}, "hobbies": ["炼金"],
        "sliders": {
            "侵蚀度": {"level": 1, "text": "开始动摇"},
            "抗拒度": {"level": 2, "text": "抗拒度:2"},
        },
    }
    assert "role" not in out and "location" not in out


def test_resolve_baseline_profile_returns_empty_dict_when_no_lore_record(monkeypatch):
    from engine.story_sandbox.profile_mutate import _resolve_baseline_profile

    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.chapter_state.resolve_card_state",
        lambda name, chapter, stage: {},
    )
    assert _resolve_baseline_profile("甲", 3) == {}


_EDGE_甲乙 = {
    "from": "甲", "to": "乙", "nature": "结拜", "relationship_anchor": "",
    "from_ref_terms": [], "to_ref_terms": [],
}


def test_extract_relationship_edges_pops_key_and_keeps_rest_of_parsed_intact():
    from engine.story_sandbox.profile_mutate import _extract_relationship_edges

    parsed = {"甲": {"race": "精灵"}, "$relationships": [_EDGE_甲乙]}
    edges = _extract_relationship_edges(parsed, {"甲", "乙"})
    assert edges == {"甲→乙": _EDGE_甲乙}
    assert parsed == {"甲": {"race": "精灵"}}  # $relationships popped out, profile keys untouched


def test_extract_relationship_edges_returns_empty_when_key_absent():
    from engine.story_sandbox.profile_mutate import _extract_relationship_edges

    assert _extract_relationship_edges({"甲": {"race": "精灵"}}, {"甲"}) == {}


def test_extract_relationship_edges_drops_edge_naming_a_non_present_character():
    """The scope-guard this whole feature exists to uphold: from/to must both be this turn's
    active_cast (present) characters -- an edge naming anyone else is discarded, never reaching
    relationship_mutation_this_turn (mirrors the present-vs-related cast redesign's off-outline
    leak fix)."""
    from engine.story_sandbox.profile_mutate import _extract_relationship_edges

    edge = {**_EDGE_甲乙, "to": "路人"}
    assert _extract_relationship_edges({"$relationships": [edge]}, {"甲", "乙"}) == {}


def test_extract_relationship_edges_drops_malformed_entries():
    from engine.story_sandbox.profile_mutate import _extract_relationship_edges

    assert _extract_relationship_edges({"$relationships": ["不是字典", _EDGE_甲乙]}, {"甲", "乙"}) == {
        "甲→乙": _EDGE_甲乙,
    }


@pytest.mark.asyncio
async def test_guard_relationship_edges_rewrites_relationship_anchor_only():
    from engine.story_sandbox.profile_mutate import _guard_relationship_edges

    forbidden = "违规词"
    guard_calls: list[str] = []

    async def guard_text(text: str) -> str:
        guard_calls.append(text)
        return text.replace(forbidden, "安全词")

    edges = {"甲→乙": {**_EDGE_甲乙, "relationship_anchor": f"执念含{forbidden}"}}
    out = await _guard_relationship_edges(edges, guard_text)
    assert forbidden not in out["甲→乙"]["relationship_anchor"]
    assert "安全词" in out["甲→乙"]["relationship_anchor"]
    assert guard_calls == [f"执念含{forbidden}"]


@pytest.mark.asyncio
async def test_guard_relationship_edges_skips_guard_when_anchor_empty():
    from engine.story_sandbox.profile_mutate import _guard_relationship_edges

    called = []

    async def guard_text(text: str) -> str:
        called.append(text)
        return text

    out = await _guard_relationship_edges({"甲→乙": _EDGE_甲乙}, guard_text)
    assert out == {"甲→乙": _EDGE_甲乙}
    assert called == []


def test_commit_previous_round_relationships_merges_prior_rounds_mutation_into_overlay():
    from engine.story_sandbox.profile_mutate import _commit_previous_round_relationships

    committed = _commit_previous_round_relationships({
        "turns": [{"relationship_mutation": {"甲→乙": _EDGE_甲乙}}],
        "relationship_overlay": {"丙→丁": {"from": "丙", "to": "丁", "nature": "世仇", "relationship_anchor": "", "from_ref_terms": [], "to_ref_terms": []}},
    })
    assert set(committed) == {"甲→乙", "丙→丁"}


def test_commit_previous_round_relationships_returns_none_when_no_turns_yet():
    from engine.story_sandbox.profile_mutate import _commit_previous_round_relationships

    assert _commit_previous_round_relationships({"relationship_overlay": {}}) is None


def test_commit_previous_round_relationships_returns_none_when_previous_round_had_none():
    from engine.story_sandbox.profile_mutate import _commit_previous_round_relationships

    assert _commit_previous_round_relationships({
        "turns": [{"relationship_mutation": None}], "relationship_overlay": {},
    }) is None


@pytest.mark.asyncio
async def test_profile_mutate_node_drops_relationship_edge_involving_passerby():
    async def call_llm(_system, _user):
        return json.dumps({"$relationships": [_EDGE_甲乙]}, ensure_ascii=False)

    node = build_profile_mutate_node(0, call_llm, _identity_guard_text)
    result = await node({
        "event_log_entries_this_turn": [{"summary": "事件"}], "final_text": "正文",
        "character_profile": {},
        "active_cast": {"甲": 0, "乙": 0},
        "passerby_names": ["乙"],
    })
    assert result["relationship_mutation_this_turn"] is None


@pytest.mark.asyncio
async def test_profile_mutate_node_reports_relationship_edge_between_present_characters(
    monkeypatch,
):

    async def call_llm(_system, _user):
        return json.dumps({"$relationships": [_EDGE_甲乙]}, ensure_ascii=False)

    node = build_profile_mutate_node(0, call_llm, _identity_guard_text)
    result = await node({
        "event_log_entries_this_turn": [{"summary": "甲乙结拜"}], "final_text": "正文",
        "character_profile": {}, "active_cast": {"甲": 0, "乙": 0},
    })
    assert result["relationship_mutation_this_turn"] == {"甲→乙": _EDGE_甲乙}
    assert result["profile_mutation_this_turn"] is None


@pytest.mark.asyncio
async def test_profile_mutate_node_drops_relationship_edge_naming_a_non_present_character(
    monkeypatch,
):

    async def call_llm(_system, _user):
        return json.dumps(
            {"$relationships": [{**_EDGE_甲乙, "to": "路人"}]}, ensure_ascii=False,
        )

    node = build_profile_mutate_node(0, call_llm, _identity_guard_text)
    result = await node({
        "event_log_entries_this_turn": [{"summary": "事件"}], "final_text": "正文",
        "character_profile": {}, "active_cast": {"甲": 0},
    })
    assert result["relationship_mutation_this_turn"] is None


@pytest.mark.asyncio
async def test_profile_mutate_node_relationship_mutation_deferred_by_one_round(monkeypatch):
    """Same deferred-commit lifecycle as character_profile: this round's own relationship
    proposal must not enter relationship_overlay until a LATER round commits it."""

    async def call_llm(_system, _user):
        return json.dumps({"$relationships": [_EDGE_甲乙]}, ensure_ascii=False)

    node = build_profile_mutate_node(0, call_llm, _identity_guard_text)
    result = await node({
        "event_log_entries_this_turn": [{"summary": "甲乙结拜"}], "final_text": "正文",
        "character_profile": {}, "relationship_overlay": {},
        "active_cast": {"甲": 0, "乙": 0},
    })
    assert "relationship_overlay" not in result
    assert result["relationship_mutation_this_turn"] == {"甲→乙": _EDGE_甲乙}


@pytest.mark.asyncio
async def test_profile_mutate_node_commits_previous_round_relationship_on_a_fresh_turn(
    monkeypatch,
):

    async def call_llm(_system, _user):
        return "{}"

    node = build_profile_mutate_node(1, call_llm, _identity_guard_text)
    result = await node({
        "event_log_entries_this_turn": [{"summary": "无关事件"}], "final_text": "正文",
        "character_profile": {}, "relationship_overlay": {},
        "turns": [{"relationship_mutation": {"甲→乙": _EDGE_甲乙}}],
    })
    assert result["relationship_overlay"] == {"甲→乙": _EDGE_甲乙}
    assert result["relationship_mutation_this_turn"] is None


@pytest.mark.asyncio
async def test_profile_mutate_node_does_not_commit_relationship_on_rewrite(monkeypatch):

    async def call_llm(_system, _user):
        return "{}"

    node = build_profile_mutate_node(1, call_llm, _identity_guard_text, is_rewrite=True)
    result = await node({
        "event_log_entries_this_turn": [{"summary": "无关事件"}], "final_text": "正文",
        "character_profile": {}, "relationship_overlay": {},
        "turns": [{"relationship_mutation": {"甲→乙": _EDGE_甲乙}}],
    })
    assert "relationship_overlay" not in result


@pytest.mark.asyncio
async def test_profile_mutate_node_includes_current_mutation_on_directed_rewrite():
    calls: list[tuple[str, str]] = []

    async def call_llm(system, user):
        calls.append((system, user))
        return "{}"

    node = build_profile_mutate_node(1, call_llm, _identity_guard_text, is_rewrite=True)
    await node({
        "final_text": "正文", "character_profile": {}, "relationship_overlay": {},
        "active_cast": {"甲": 0, "乙": 0}, "profile_mutate_directed_rewrite": True,
        "profile_mutate_feedback": "将甲的种族改为恶魔",
        "turns": [{
            "prose": "正文", "instruction": "继续", "character_states": {}, "suggestions": [],
            "profile_mutation": {"甲": {"race": "精灵"}},
            "relationship_mutation": {"甲→乙": _EDGE_甲乙},
        }],
    })
    assert len(calls) == 1
    assert "定向重写" in calls[0][0]
    assert "本轮当前已确认的档案突变" in calls[0][1]
    assert '"race": "精灵"' in calls[0][1]
    assert "本轮当前已确认的关系突变" in calls[0][1]
    assert "结拜" in calls[0][1]


@pytest.mark.asyncio
async def test_profile_mutate_node_includes_recall_block_in_user():
    calls: list[tuple[str, str]] = []

    async def call_llm(system, user):
        calls.append((system, user))
        return "{}"

    node = build_profile_mutate_node(1, call_llm, _identity_guard_text)
    await node({
        "final_text": "正文", "character_profile": {}, "relationship_overlay": {},
        "active_cast": {"甲": 0}, "event_log_entries_this_turn": [{"summary": "事件"}],
        "recall_context_this_turn": "## 相关历史/设定回收\n- 【元气】气血流动力量",
        "turns": [{"prose": "正文", "instruction": "继续", "character_states": {}, "suggestions": []}],
    })
    assert "## 相关历史/设定回收" in calls[0][1]
    assert "【元气】" in calls[0][1]


@pytest.mark.asyncio
async def test_profile_mutate_node_runs_llm_on_directed_rewrite_without_feedback_or_event():
    calls: list[tuple[str, str]] = []

    async def call_llm(system, user):
        calls.append((system, user))
        return "{}"

    node = build_profile_mutate_node(1, call_llm, _identity_guard_text, is_rewrite=True)
    await node({
        "final_text": "正文", "character_profile": {}, "relationship_overlay": {},
        "active_cast": {"甲": 0}, "profile_mutate_directed_rewrite": True,
        "turns": [{"prose": "正文", "instruction": "继续", "character_states": {}, "suggestions": []}],
    })
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_profile_mutate_node_runs_llm_when_feedback_present_without_event_log():
    calls: list[tuple[str, str]] = []

    async def call_llm(system, user):
        calls.append((system, user))
        return "{}"

    node = build_profile_mutate_node(1, call_llm, _identity_guard_text, is_rewrite=True)
    await node({
        "final_text": "正文", "character_profile": {}, "relationship_overlay": {},
        "active_cast": {"甲": 0}, "profile_mutate_feedback": "将种族修正为恶魔",
        "turns": [{"prose": "正文", "instruction": "继续", "character_states": {}, "suggestions": []}],
    })
    assert len(calls) == 1
    assert "将种族修正为恶魔" in calls[0][0]
    assert "【用户指导意见】：将种族修正为恶魔" in calls[0][1]
