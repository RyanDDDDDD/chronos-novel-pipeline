import pytest


def test_resolve_character_cards_renders_only_requested_names(monkeypatch):
    from engine.story_sandbox.cast import resolve_character_cards

    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.cards.render_character_card",
        lambda name, chapter, stage, *, include_persona=True: f"角色：{name}",
    )
    cards = resolve_character_cards(1, ["乙"])
    assert [c["name"] for c in cards] == ["乙"]


def test_resolve_character_cards_empty_names_returns_empty_list():
    from engine.story_sandbox.cast import resolve_character_cards

    assert resolve_character_cards(1, []) == []


def test_resolve_character_cards_deduplicates_repeated_names(monkeypatch):
    from engine.story_sandbox.cast import resolve_character_cards

    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.cards.render_character_card",
        lambda name, chapter, stage, *, include_persona=True: f"角色：{name}",
    )
    cards = resolve_character_cards(1, ["甲", "甲", "乙"])
    assert [c["name"] for c in cards] == ["甲", "乙"]


def test_render_dynamic_cast_block_renders_each_active_member(monkeypatch):
    from engine.story_sandbox.cast import render_dynamic_cast_block

    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.cards.render_character_card",
        lambda name, chapter, stage, *, include_persona=True: f"角色：{name}（章{chapter}·幕{stage}）",
    )
    block = render_dynamic_cast_block({"甲": 1, "乙": 2}, chapter=3)
    assert "## 在场角色档案" in block
    assert "角色：甲（章3·幕1）" in block
    assert "角色：乙（章3·幕1）" in block


def test_render_dynamic_cast_block_free_mode_anchors_at_chapter_zero_stage_zero(monkeypatch):
    from engine.story_sandbox.cast import render_dynamic_cast_block

    seen = []

    def _fake(name, chapter, stage, *, include_persona=True):
        seen.append((name, chapter, stage))
        return f"角色：{name}"

    monkeypatch.setattr("engine.author_loop.dialogue_mode.cards.render_character_card", _fake)
    render_dynamic_cast_block({"甲": 0}, chapter=0)
    assert seen == [("甲", 0, 0)]


def test_render_dynamic_cast_block_excludes_given_names(monkeypatch):
    from engine.story_sandbox.cast import render_dynamic_cast_block

    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.cards.render_character_card",
        lambda name, chapter, stage, *, include_persona=True: f"角色：{name}",
    )
    block = render_dynamic_cast_block({"甲": 1, "乙": 1}, chapter=1, exclude={"甲"})
    assert "角色：甲" not in block
    assert "角色：乙" in block


def test_render_dynamic_cast_block_empty_active_cast_is_empty_string():
    from engine.story_sandbox.cast import render_dynamic_cast_block

    assert render_dynamic_cast_block({}, chapter=1) == ""


def test_render_dynamic_cast_block_all_excluded_is_empty_string(monkeypatch):
    from engine.story_sandbox.cast import render_dynamic_cast_block

    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.cards.render_character_card",
        lambda name, chapter, stage, *, include_persona=True: f"角色：{name}",
    )
    assert render_dynamic_cast_block({"甲": 1}, chapter=1, exclude={"甲"}) == ""


def test_resolve_related_cast_returns_relationship_graph_neighbors(monkeypatch):
    from engine.story_sandbox.cast import resolve_related_cast

    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": {"小明→司马相如": {
            "from": "小明", "to": "司马相如", "nature": "主人/奴隶", "relationship_anchor": "",
            "from_ref_terms": [], "to_ref_terms": ["对手"],
        }}},
    )
    assert resolve_related_cast({"小明"}) == ["司马相如"]


def test_resolve_related_cast_excludes_already_present_names(monkeypatch):
    from engine.story_sandbox.cast import resolve_related_cast

    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": {"小明→王五": {
            "from": "小明", "to": "王五", "nature": "主人/奴滤", "relationship_anchor": "",
            "from_ref_terms": [], "to_ref_terms": [],
        }}},
    )
    assert resolve_related_cast({"小明", "王五"}) == []


def test_resolve_related_cast_surfaces_a_session_overlay_edge(monkeypatch):
    """A relationship this session's own profile_mutate proposed (see profile_mutate.py) --
    never written to relationship_edges.jsonl, only merged in from state -- must still surface a
    related character, same as a base-graph edge would."""
    from engine.story_sandbox.cast import resolve_related_cast

    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": {}},
    )
    overlay = {"小明→司马相如": {
        "from": "小明", "to": "司马相如", "nature": "宿敌", "relationship_anchor": "",
        "from_ref_terms": [], "to_ref_terms": [],
    }}
    assert resolve_related_cast({"小明"}, overlay) == ["司马相如"]


def test_resolve_related_cast_overlay_defaults_to_empty_when_omitted(monkeypatch):
    from engine.story_sandbox.cast import resolve_related_cast

    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": {}},
    )
    assert resolve_related_cast({"小明"}) == []


def test_resolve_related_cast_ranks_by_present_edge_count_and_caps_at_five(monkeypatch):
    """Seven candidates connected to the present cast; only the top 5 by how many present
    characters they're each tied to should survive, alphabetical among ties."""
    from engine.story_sandbox.cast import resolve_related_cast

    def _edge(frm, to):
        return {"from": frm, "to": to, "nature": "", "relationship_anchor": "",
                "from_ref_terms": [], "to_ref_terms": []}

    edges = {}
    # 丙: 3 edges to present (甲, 乙, 丁) -> highest count, should survive.
    for present_name in ("甲", "乙", "丁"):
        edges[f"{present_name}→丙"] = _edge(present_name, "丙")
    # 丁 also present, tied to 甲 -- excluded from candidates since 丁 is present.
    edges["甲→丁"] = _edge("甲", "丁")
    # 戊, 己: 2 edges each -> next tier.
    for present_name in ("甲", "乙"):
        edges[f"{present_name}→戊"] = _edge(present_name, "戊")
        edges[f"{present_name}→己"] = _edge(present_name, "己")
    # 庚, 辛, 壬, 癸: 1 edge each -> lowest tier, only some fit in the remaining slots.
    for name in ("庚", "辛", "壬", "癸"):
        edges[f"甲→{name}"] = _edge("甲", name)

    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": edges},
    )
    result = resolve_related_cast({"甲", "乙", "丁"})
    assert len(result) == 5
    assert "丙" in result  # count=3, must survive
    assert "戊" in result and "己" in result  # count=2, must survive
    assert result == sorted(result)  # final order is alphabetical, not by score


def test_render_related_cast_block_forbids_dialogue_and_actions(monkeypatch):
    from engine.story_sandbox.cast import render_related_cast_block

    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.cards.render_related_character_brief",
        lambda name, chapter, stage, **kw: f"【{name}】极简卡",
    )
    block = render_related_cast_block(["司马相如"], chapter=8, anchor_names={"甲"})
    assert "## 相关角色档案" in block
    assert "禁止让他们说话、登场或采取任何行动" in block
    assert "【司马相如】极简卡" in block


def test_render_related_cast_block_excludes_given_names(monkeypatch):
    from engine.story_sandbox.cast import render_related_cast_block

    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.cards.render_related_character_brief",
        lambda name, chapter, stage, **kw: f"【{name}】",
    )
    block = render_related_cast_block(["甲", "乙"], chapter=1, exclude={"甲"})
    assert "【甲】" not in block
    assert "【乙】" in block


def test_render_related_cast_block_uses_exclude_as_anchor_names(monkeypatch):
    from engine.story_sandbox.cast import render_related_cast_block

    seen: list[set[str] | None] = []

    def _fake(name, chapter, stage, *, anchor_names=None, overlay=None):
        seen.append(anchor_names)
        return f"【{name}】"

    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.cards.render_related_character_brief", _fake,
    )
    render_related_cast_block(["乙"], chapter=1, exclude={"甲"})
    assert seen == [{"甲"}]


def test_render_related_cast_block_empty_names_is_empty_string():
    from engine.story_sandbox.cast import render_related_cast_block

    assert render_related_cast_block([], chapter=1) == ""


def test_render_related_cast_block_all_excluded_is_empty_string(monkeypatch):
    from engine.story_sandbox.cast import render_related_cast_block

    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.cards.render_related_character_brief",
        lambda name, chapter, stage, **kw: f"【{name}】",
    )
    assert render_related_cast_block(["甲"], chapter=1, exclude={"甲"}) == ""


def test_resolve_instruction_grounding_names_from_protagonist_family(monkeypatch):
    from engine.story_sandbox.cast import resolve_instruction_grounding_names

    monkeypatch.setattr(
        "engine.story_sandbox.cast._protagonist_names", lambda: {"甲"},
    )
    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {"g0": {"members": ["甲", "乙", "丙"], "type": "家人", "priority": 1}},
                 "edges": {}},
    )
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters", lambda _t: set(),
    )
    names = resolve_instruction_grounding_names("描述主角一家的日常生活")
    assert names == {"甲", "乙", "丙"}


def test_resolve_instruction_grounding_names_from_ref_terms(monkeypatch):
    from engine.story_sandbox.cast import resolve_instruction_grounding_names

    monkeypatch.setattr("engine.story_sandbox.cast._protagonist_names", lambda: set())
    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": {"甲→乙": {
            "from": "甲", "to": "乙", "nature": "师徒",
            "relationship_anchor": "", "from_ref_terms": [], "to_ref_terms": ["师傅"],
        }}},
    )
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters", lambda _t: set(),
    )
    names = resolve_instruction_grounding_names("写一段师傅教导弟子的日常")
    assert names == {"甲", "乙"}


def test_resolve_instruction_grounding_names_empty_when_no_cues(monkeypatch):
    from engine.story_sandbox.cast import resolve_instruction_grounding_names

    monkeypatch.setattr("engine.story_sandbox.cast._protagonist_names", lambda: set())
    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": {}},
    )
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters", lambda _t: set(),
    )
    assert resolve_instruction_grounding_names("随便写个开场") == set()


def test_render_instruction_grounding_blocks_renders_graph_and_briefs(monkeypatch):
    from engine.story_sandbox.cast import render_instruction_grounding_blocks

    monkeypatch.setattr(
        "engine.story_sandbox.cast.resolve_instruction_grounding_names",
        lambda _i: {"甲", "乙"},
    )
    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": {"甲→乙": {
            "from": "甲", "to": "乙", "nature": "兄妹",
            "relationship_anchor": "", "from_ref_terms": [], "to_ref_terms": [],
        }}},
    )
    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.render_overview",
        lambda g, names=None: "## 角色关系\n- 甲→乙",
    )
    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.cards.render_related_character_brief",
        lambda name, chapter, stage, **kw: f"【{name}】简卡",
    )
    graph_block, briefs_block = render_instruction_grounding_blocks("主角一家", chapter=0)
    assert "角色关系" in graph_block
    assert "关联角色简卡" in briefs_block
    assert "【甲】简卡" in briefs_block and "【乙】简卡" in briefs_block


def test_merge_profile_overlay_merges_sliders_per_axis():
    from engine.story_sandbox.profile_mutate import merge_profile_fields

    arc = {"sliders": {"侵蚀度": {"level": 1, "text": "动摇"}, "抗拒度": 2}}
    merged = merge_profile_fields(arc, {"sliders": {"侵蚀度": {"level": 3, "text": "沦陷"}}})
    assert merged["sliders"] == {"侵蚀度": {"level": 3, "text": "沦陷"}, "抗拒度": 2}


def test_merge_profile_overlay_merges_physique_per_slot():
    from engine.story_sandbox.profile_mutate import merge_profile_fields

    arc = {"physique": {"horns": "有一对小角", "tail": "无"}}
    merged = merge_profile_fields(arc, {"physique": {"tail": "长出了尾巴"}})
    assert merged["physique"] == {"horns": "有一对小角", "tail": "长出了尾巴"}


def test_merge_profile_overlay_replaces_scalar_fields_wholesale():
    from engine.story_sandbox.profile_mutate import merge_profile_fields

    arc = {"race": "人类"}
    merged = merge_profile_fields(arc, {"race": "精灵"})
    assert merged["race"] == "精灵"


def test_merge_profile_overlay_merges_hobbies_as_union_not_wholesale():
    """Regression: reporting a newly-discovered hobby must not wipe out the character's
    already-established baseline hobbies (this merge also runs at archive-display time, not
    just session-overlay accumulation -- see resolve_active_cast_archives)."""
    from engine.story_sandbox.profile_mutate import merge_profile_fields

    arc = {"hobbies": ["炼金"]}
    merged = merge_profile_fields(arc, {"hobbies": ["剑术", "占卜"]})
    assert merged["hobbies"] == ["炼金", "剑术", "占卜"]


def test_merge_profile_overlay_does_not_mutate_the_input_arc():
    from engine.story_sandbox.profile_mutate import merge_profile_fields

    arc = {"race": "人类"}
    merge_profile_fields(arc, {"race": "精灵"})
    assert arc == {"race": "人类"}


async def _empty_overlay_state(novel_id: str, chapter: int) -> dict:
    return {"character_profile": {}}


@pytest.mark.asyncio
async def test_resolve_active_cast_archives_chapter_mode_uses_stage_one(monkeypatch):
    from engine.story_sandbox.cast import resolve_active_cast_archives

    seen: list[tuple[str, int, int]] = []

    def _fake_resolve(name: str, chapter: int, stage: int) -> dict:
        seen.append((name, chapter, stage))
        return {"role": f"role-{name}"}

    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.chapter_state.resolve_card_state", _fake_resolve,
    )
    monkeypatch.setattr(
        "engine.archive.archive_view.render_character_profile",
        lambda name, arc: {"name": name, "role": arc.get("role", "")},
    )
    monkeypatch.setattr("engine.story_sandbox.graph.peek_state", _empty_overlay_state)

    result = await resolve_active_cast_archives(3, ["甲", "乙"], "novel-a")
    assert seen == [("乙", 3, 1), ("甲", 3, 1)]
    assert [entry["name"] for entry in result] == ["乙", "甲"]
    assert all("role" in entry for entry in result)


@pytest.mark.asyncio
async def test_resolve_active_cast_archives_free_mode_uses_stage_zero(monkeypatch):
    from engine.story_sandbox.cast import resolve_active_cast_archives

    seen: list[tuple[str, int, int]] = []

    def _fake_resolve(name: str, chapter: int, stage: int) -> dict:
        seen.append((name, chapter, stage))
        return {"role": "baseline"}

    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.chapter_state.resolve_card_state", _fake_resolve,
    )
    monkeypatch.setattr(
        "engine.archive.archive_view.render_character_profile",
        lambda name, arc: {"name": name, "role": arc.get("role", "")},
    )
    monkeypatch.setattr("engine.story_sandbox.graph.peek_state", _empty_overlay_state)

    await resolve_active_cast_archives(0, ["甲"], "novel-a")
    assert seen == [("甲", 0, 0)]


@pytest.mark.asyncio
async def test_resolve_active_cast_archives_skips_empty_arc(monkeypatch):
    from engine.story_sandbox.cast import resolve_active_cast_archives

    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.chapter_state.resolve_card_state",
        lambda name, chapter, stage: {} if name == "missing" else {"role": "present"},
    )
    monkeypatch.setattr(
        "engine.archive.archive_view.render_character_profile",
        lambda name, arc: {"name": name, "role": arc.get("role", "")},
    )
    monkeypatch.setattr("engine.story_sandbox.graph.peek_state", _empty_overlay_state)

    result = await resolve_active_cast_archives(1, ["missing", "甲"], "novel-a")
    assert [entry["name"] for entry in result] == ["甲"]


@pytest.mark.asyncio
async def test_resolve_active_cast_archives_empty_names_returns_empty_list():
    from engine.story_sandbox.cast import resolve_active_cast_archives

    assert await resolve_active_cast_archives(1, [], "novel-a") == []


@pytest.mark.asyncio
async def test_resolve_active_cast_archives_applies_session_profile_overlay(monkeypatch):
    from engine.story_sandbox.cast import resolve_active_cast_archives

    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.chapter_state.resolve_card_state",
        lambda name, chapter, stage: {"race": "人类", "role": f"role-{name}"},
    )
    monkeypatch.setattr(
        "engine.archive.archive_view.render_character_profile",
        lambda name, arc: {"name": name, "race": arc.get("race", "")},
    )

    async def _state(novel_id: str, chapter: int) -> dict:
        assert (novel_id, chapter) == ("novel-a", 3)
        return {"character_profile": {"甲": {"race": "精灵"}}}

    monkeypatch.setattr("engine.story_sandbox.graph.peek_state", _state)

    result = await resolve_active_cast_archives(3, ["甲"], "novel-a")
    assert result == [{"name": "甲", "race": "精灵"}]


@pytest.mark.asyncio
async def test_resolve_active_cast_archives_leaves_baseline_untouched_when_no_overlay_entry(
    monkeypatch,
):
    from engine.story_sandbox.cast import resolve_active_cast_archives

    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.chapter_state.resolve_card_state",
        lambda name, chapter, stage: {"race": "人类"},
    )
    monkeypatch.setattr(
        "engine.archive.archive_view.render_character_profile",
        lambda name, arc: {"name": name, "race": arc.get("race", "")},
    )

    async def _state(novel_id: str, chapter: int) -> dict:
        return {"character_profile": {"乙": {"race": "精灵"}}}  # overlay for a different character

    monkeypatch.setattr("engine.story_sandbox.graph.peek_state", _state)

    result = await resolve_active_cast_archives(3, ["甲"], "novel-a")
    assert result == [{"name": "甲", "race": "人类"}]


@pytest.mark.asyncio
async def test_resolve_active_cast_archives_uses_passed_in_state_without_repeeking(monkeypatch):
    from engine.story_sandbox.cast import resolve_active_cast_archives

    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.chapter_state.resolve_card_state",
        lambda name, chapter, stage: {"race": "人类", "role": f"role-{name}"},
    )
    monkeypatch.setattr(
        "engine.archive.archive_view.render_character_profile",
        lambda name, arc: {"name": name, "race": arc.get("race", "")},
    )

    async def _peek_state_should_not_be_called(novel_id: str, chapter: int) -> dict:
        raise AssertionError("peek_state must not be called when state is passed in")

    monkeypatch.setattr("engine.story_sandbox.graph.peek_state", _peek_state_should_not_be_called)

    result = await resolve_active_cast_archives(
        3, ["甲"], "novel-a", state={"character_profile": {"甲": {"race": "精灵"}}},
    )
    assert result == [{"name": "甲", "race": "精灵"}]


@pytest.mark.asyncio
async def test_resolve_related_cast_archives_empty_present_returns_empty_list():
    from engine.story_sandbox.cast import resolve_related_cast_archives

    assert await resolve_related_cast_archives(3, [], "novel-a") == []


@pytest.mark.asyncio
async def test_resolve_related_cast_archives_resolves_via_relationship_graph(monkeypatch):
    from engine.story_sandbox.cast import resolve_related_cast_archives

    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": {"角色甲→角色乙": {
            "from": "角色甲", "to": "角色乙", "nature": "主人/奴隶", "relationship_anchor": "",
            "from_ref_terms": [], "to_ref_terms": [],
        }}},
    )
    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.chapter_state.resolve_card_state",
        lambda name, chapter, stage: {"role": f"role-{name}"},
    )
    monkeypatch.setattr(
        "engine.archive.archive_view.render_character_profile",
        lambda name, arc: {"name": name, "role": arc.get("role", "")},
    )

    async def _state(novel_id: str, chapter: int) -> dict:
        assert (novel_id, chapter) == ("novel-a", 3)
        return {"relationship_overlay": {}, "character_profile": {}}

    monkeypatch.setattr("engine.story_sandbox.graph.peek_state", _state)

    result = await resolve_related_cast_archives(3, ["角色甲"], "novel-a")
    assert result == [{"name": "角色乙", "role": "role-角色乙"}]


@pytest.mark.asyncio
async def test_resolve_related_cast_archives_uses_session_relationship_overlay(monkeypatch):
    """A relationship this session's own profile_mutate proposed (relationship_overlay, never
    written to relationship_edges.jsonl) must still surface a related character card."""
    from engine.story_sandbox.cast import resolve_related_cast_archives

    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": {}},
    )
    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.chapter_state.resolve_card_state",
        lambda name, chapter, stage: {"role": f"role-{name}"},
    )
    monkeypatch.setattr(
        "engine.archive.archive_view.render_character_profile",
        lambda name, arc: {"name": name, "role": arc.get("role", "")},
    )

    overlay_edge = {"角色甲→角色乙": {
        "from": "角色甲", "to": "角色乙", "nature": "宿敌", "relationship_anchor": "",
        "from_ref_terms": [], "to_ref_terms": [],
    }}

    async def _state(novel_id: str, chapter: int) -> dict:
        return {"relationship_overlay": overlay_edge, "character_profile": {}}

    monkeypatch.setattr("engine.story_sandbox.graph.peek_state", _state)

    result = await resolve_related_cast_archives(3, ["角色甲"], "novel-a")
    assert [c["name"] for c in result] == ["角色乙"]
