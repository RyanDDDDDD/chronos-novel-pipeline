import engine.author_loop.dialogue_mode.cards as c


def test_card_renders_causal_anchors(monkeypatch):
    monkeypatch.setattr(
        c, "resolve_card_state",
        lambda _n, _c, _s: {
            "role": "主角",
            "causal_anchors": {"执念": "夺回失去的一切", "创伤": "被至亲背叛"},
        },
    )
    out = c.render_character_card("甲", 1, 1)
    assert "因果锚点：" in out
    assert "  - 执念：夺回失去的一切" in out
    assert "  - 创伤：被至亲背叛" in out


def test_card_omits_empty_causal_anchors(monkeypatch):
    monkeypatch.setattr(
        c, "resolve_card_state",
        lambda _n, _c, _s: {"role": "主角", "causal_anchors": {}},
    )
    out = c.render_character_card("甲", 1, 1)
    assert "因果锚点" not in out


def test_card_renders_five_dynamic_fields(monkeypatch):
    monkeypatch.setattr(c, "resolve_card_state", lambda _n, _c, _s: {"role": "主角"})
    out = c.render_character_card(
        "甲", 1, 1,
        dynamic_state={"psychology": "稳", "posture": "站立", "clothing": "便装",
                       "action": "叉腰", "demeanor": "平静"},
    )
    assert "当前心理：稳" in out
    assert "当前体态：站立" in out
    assert "当前着装：便装" in out
    assert "当前动作：叉腰" in out
    assert "当前神态：平静" in out


def test_card_omits_dynamic_fields_when_none_given(monkeypatch):
    monkeypatch.setattr(c, "resolve_card_state", lambda _n, _c, _s: {"role": "主角"})
    out = c.render_character_card("甲", 1, 1)
    assert "当前心理" not in out and "当前着装" not in out


def test_card_renders_physique_slots(monkeypatch):
    monkeypatch.setattr(
        c, "resolve_card_state",
        lambda _n, _c, _s: {
            "role": "主角",
            "physique": {"体型": "高挑丰腴，腰肢纤细", "胸部": "饱满挺翘"},
        },
    )
    out = c.render_character_card("甲", 1, 1)
    assert "体型：高挑丰腴，腰肢纤细" in out
    assert "胸部：饱满挺翘" in out


def test_card_omits_physique_when_absent(monkeypatch):
    monkeypatch.setattr(
        c, "resolve_card_state",
        lambda _n, _c, _s: {"role": "主角"},
    )
    out = c.render_character_card("甲", 1, 1)
    assert "体貌" not in out


def test_card_renders_physique_even_when_persona_disabled(monkeypatch):
    monkeypatch.setattr(
        c, "resolve_card_state",
        lambda _n, _c, _s: {
            "role": "主角",
            "physique": {"体型": "高挑丰腴"},
        },
    )
    slim = c.render_character_card("甲", 1, 1, include_persona=False)
    assert "体型：高挑丰腴" in slim


def test_render_card_uses_personality_field(monkeypatch):
    import engine.author_loop.dialogue_mode.cards as cards
    monkeypatch.setattr(cards, "resolve_card_state", lambda n, c, s: {
        "role": "主",
        "personality": "外冷内热，嘴硬心软", "self_ref": {"_default": ["我"]},
    })
    out = cards.render_character_card("甲", 1, 1)
    assert "人格：外冷内热，嘴硬心软" in out


def test_render_card_normalizes_legacy_scalar_self_ref(monkeypatch):
    import engine.author_loop.dialogue_mode.cards as cards
    monkeypatch.setattr(cards, "resolve_card_state", lambda n, c, s: {
        "role": "主",
        "archetype": "倔强型", "self_ref": "我",
    })
    out = cards.render_character_card("甲", 1, 1)
    assert "自称：我" in out


def test_card_renders_verbal_tic_identity_background_and_hobbies(monkeypatch):
    import engine.author_loop.dialogue_mode.cards as cards
    monkeypatch.setattr(cards, "resolve_card_state", lambda n, c, s: {
        "role": "乙型",
        "archetype": "温婉克制型", "self_ref": {"_default": ["奴家", "妾身"]},
        "verbal_tic": "句尾爱加「呢」，紧张时会重复最后两个字",
        "identity_background": "没落贵族之女，寄人篱下",
        "hobbies": ["爱吃甜食", "喜欢刺绣"],
    })
    full = cards.render_character_card("甲", 1, 1)
    assert "口癖：句尾爱加「呢」，紧张时会重复最后两个字" in full
    assert "身份背景：没落贵族之女，寄人篱下" in full
    assert "爱好：爱吃甜食、喜欢刺绣" in full
    assert full.index("自称：") < full.index("口癖：") < full.index("身份背景：") < full.index("爱好：")


def test_card_omits_verbal_tic_identity_background_and_hobbies_when_disabled(monkeypatch):
    import engine.author_loop.dialogue_mode.cards as cards
    monkeypatch.setattr(cards, "resolve_card_state", lambda n, c, s: {
        "role": "乙型",
        "archetype": "温婉克制型", "self_ref": {"_default": ["奴家"]},
        "verbal_tic": "句尾爱加「呢」",
        "identity_background": "没落贵族之女",
        "hobbies": ["爱吃甜食"],
    })
    slim = cards.render_character_card("甲", 1, 1, include_persona=False)
    assert "口癖" not in slim
    assert "身份背景" not in slim
    assert "爱好" not in slim


def test_card_omits_empty_verbal_tic_identity_background_and_hobbies(monkeypatch):
    import engine.author_loop.dialogue_mode.cards as cards
    monkeypatch.setattr(cards, "resolve_card_state", lambda n, c, s: {
        "role": "乙型",
        "archetype": "温婉克制型", "self_ref": {"_default": ["我"]},
    })
    out = cards.render_character_card("甲", 1, 1)
    assert "口癖" not in out
    assert "身份背景" not in out
    assert "爱好" not in out


def test_card_renders_clothing_dna_baseline(monkeypatch):
    import engine.author_loop.dialogue_mode.cards as cards

    monkeypatch.setattr(cards, "resolve_card_state", lambda n, c, s: {
        "role": "主",
        "clothing_dna": {
            "color_palette": ["白"],
            "materials_preference": ["棉"],
            "signature_outfit": "及膝白裙配浅灰开衫",
            "accessories": ["银链"],
        },
    })
    out = cards.render_character_card("甲", 1, 1)
    assert "招牌常服=及膝白裙配浅灰开衫" in out
    assert "配饰=银链" in out


def test_card_renders_custom_fields_from_content_packs(monkeypatch):
    import engine.author_loop.dialogue_mode.cards as cards
    import context.content_packs as cp

    monkeypatch.setattr(
        cp, "custom_fields",
        lambda: [cp.CustomFieldSpec(name="武器")],
    )
    monkeypatch.setattr(cards, "resolve_card_state", lambda n, c, s: {
        "role": "主", "武器": "长枪",
    })
    out = cards.render_character_card("甲", 1, 1)
    assert "武器：长枪" in out


def test_related_brief_renders_identity_relationship_and_bond(monkeypatch):
    import engine.author_loop.dialogue_mode.cards as cards

    monkeypatch.setattr(
        cards, "resolve_card_state",
        lambda _n, _c, _s: {
            "role": "配角",
            "identity_background": "华山派执法长老，嫉恶如仇",
        },
    )
    graph = {"groups": {}, "edges": {"主角→徐长老": {
        "from": "主角", "to": "徐长老", "nature": "师叔侄",
        "relationship_anchor": "嫉恶如仇的师叔",
        "from_ref_terms": [], "to_ref_terms": ["二师叔"],
    }}}
    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph", lambda: graph,
    )
    out = cards.render_related_character_brief(
        "徐长老", 1, 1, anchor_names={"主角"},
    )
    assert out.startswith("【徐长老】")
    assert "华山派执法长老" in out
    assert "主角的二师叔" in out
    assert "羁绊：嫉恶如仇的师叔" in out
    assert "口癖" not in out and "体貌" not in out


def test_related_brief_omits_bond_when_anchor_missing(monkeypatch):
    import engine.author_loop.dialogue_mode.cards as cards

    monkeypatch.setattr(
        cards, "resolve_card_state",
        lambda _n, _c, _s: {"role": "配角", "identity_background": "没落贵族"},
    )
    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": {}},
    )
    out = cards.render_related_character_brief("乙", 1, 1, anchor_names={"甲"})
    assert out == "【乙】没落贵族"


def test_related_brief_falls_back_for_unregistered_name(monkeypatch):
    import engine.author_loop.dialogue_mode.cards as cards

    monkeypatch.setattr(cards, "resolve_card_state", lambda _n, _c, _s: {})
    out = cards.render_related_character_brief("路人", 1, 1)
    assert out == "【路人】（无档案，按名字最简扮演）"


def test_related_brief_is_much_shorter_than_full_card(monkeypatch):
    import engine.author_loop.dialogue_mode.cards as cards

    monkeypatch.setattr(
        cards, "resolve_card_state",
        lambda _n, _c, _s: {
            "role": "配角",
            "identity_background": "华山派执法长老，嫉恶如仇，在门中威望极高",
            "personality": "刚正不阿，眼里揉不得沙子",
            "verbal_tic": "句尾爱加「也」",
            "hobbies": ["练剑", "下棋"],
            "physique": {"体型": "魁梧", "面容": "须眉皆白"},
            "causal_anchors": {"执念": "守护华山清誉", "创伤": "曾目睹同门叛变"},
            "self_ref": {"_default": ["老夫", "本座"]},
        },
    )
    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": {"主角→徐长老": {
            "from": "主角", "to": "徐长老", "nature": "师叔侄",
            "relationship_anchor": "嫉恶如仇的师叔",
            "from_ref_terms": [], "to_ref_terms": ["二师叔"],
        }}},
    )
    full = cards.render_character_card("徐长老", 1, 1)
    brief = cards.render_related_character_brief("徐长老", 1, 1, anchor_names={"主角"})
    assert len(brief) < len(full) * 0.3


def test_card_omits_custom_field_when_empty(monkeypatch):
    import engine.author_loop.dialogue_mode.cards as cards
    import context.content_packs as cp

    monkeypatch.setattr(
        cp, "custom_fields",
        lambda: [cp.CustomFieldSpec(name="武器")],
    )
    monkeypatch.setattr(cards, "resolve_card_state", lambda n, c, s: {"role": "主"})
    out = cards.render_character_card("甲", 1, 1)
    assert "武器" not in out
