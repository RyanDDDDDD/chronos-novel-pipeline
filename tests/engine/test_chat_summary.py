from engine.setup.chat_summary import (
    render_cast_chat,
    render_world_chat,
)


def test_render_world_chat_uses_chinese_labels():
    out = render_world_chat({"background": "X", "tone": "冷峻"})
    assert "世界背景" in out and "X" in out
    assert "基调" in out and "冷峻" in out
    assert "logline" not in out
    assert "{" not in out


def test_render_world_chat_renders_power_system_and_core_themes_as_named_lists():
    wb = {
        "power_system": [{"name": "蛊虫", "desc": "寄生方式驱动力量"}],
        "core_themes": [{"name": "复仇", "desc": "主角因灭门而踏上复仇路"}],
    }
    out = render_world_chat(wb)
    assert "力量体系" in out and "蛊虫：寄生方式驱动力量" in out
    assert "核心主题" in out and "复仇：主角因灭门而踏上复仇路" in out


def test_render_cast_chat_lists_characters():
    roster = [{"given_name": "甲", "role": "lead", "gender": "女"}]
    out = render_cast_chat(roster)
    assert "甲" in out and "角色位 lead" in out
    assert "role=" not in out
    assert "{" not in out


def test_render_character_chat_shows_identity_background_and_hobbies():
    from engine.setup.chat_summary import render_character_chat

    char = {
        "given_name": "柳如烟", "role": "乙型", "gender": "female",
        "identity_background": "没落贵族之女，寄人篱下",
        "hobbies": ["爱吃甜食", "喜欢刺绣"],
    }
    out = render_character_chat(char)
    assert "身份背景：没落贵族之女，寄人篱下" in out
    assert "爱好：爱吃甜食、喜欢刺绣" in out


def test_render_character_chat_omits_empty_identity_fields():
    from engine.setup.chat_summary import render_character_chat

    char = {"given_name": "甲", "role": "乙型", "gender": "female"}
    out = render_character_chat(char)
    assert "身份背景" not in out
    assert "爱好" not in out


def test_render_character_chat_shows_physique_and_sliders():
    from engine.setup.chat_summary import render_character_chat

    char = {
        "given_name": "柳如烟", "role": "乙型", "gender": "female",
        "physique": {"面容": "冷峻", "胸部": "结实"},
        "sliders": {"侵蚀度": {"level": 1, "text": "已有轻微裂痕"}},
    }
    out = render_character_chat(char)
    assert "体质(physique)：" in out
    assert "  面容：冷峻" in out
    assert "  胸部：结实" in out
    assert "登场初始滑块：侵蚀度：档位1·已有轻微裂痕" in out


def test_render_character_chat_omits_empty_physique_and_sliders():
    from engine.setup.chat_summary import render_character_chat

    char = {"given_name": "甲", "role": "乙型", "gender": "female"}
    out = render_character_chat(char)
    assert "physique" not in out
    assert "登场初始滑块" not in out


def test_render_character_chat_shows_verbal_tic():
    from engine.setup.chat_summary import render_character_chat

    char = {
        "given_name": "柳如烟", "role": "乙型", "gender": "female",
        "verbal_tic": "句尾爱加「呢」，紧张时会重复最后两个字",
    }
    out = render_character_chat(char)
    assert "口癖：句尾爱加「呢」，紧张时会重复最后两个字" in out


def test_render_character_chat_shows_portrait_tags_non_brief_only():
    from engine.setup.chat_summary import render_character_chat

    char = {
        "given_name": "白洲梓", "role": "主角", "gender": "female",
        "portrait_identity_tags": "shiroko (blue archive), blue archive",
        "portrait_visual_tags": "1girl, blue hair",
    }
    full = render_character_chat(char, brief=False)
    assert "形象锚定（立绘）：shiroko (blue archive), blue archive" in full
    assert "生图提示词（立绘外观）：1girl, blue hair" in full

    assert "形象锚定" not in render_character_chat(char, brief=True)


def test_render_character_chat_omits_empty_portrait_tags():
    from engine.setup.chat_summary import render_character_chat

    out = render_character_chat({"given_name": "甲", "role": "x", "gender": "female"})
    assert "形象锚定" not in out
    assert "生图提示词" not in out


def test_render_character_chat_omits_empty_verbal_tic():
    from engine.setup.chat_summary import render_character_chat

    char = {"given_name": "甲", "role": "乙型", "gender": "female"}
    out = render_character_chat(char)
    assert "口癖" not in out


def test_render_character_chat_includes_custom_fields(monkeypatch):
    from engine.setup import chat_summary as cs
    import context.content_packs as cp

    monkeypatch.setattr(
        cp, "custom_fields",
        lambda: [cp.CustomFieldSpec(name="武器")],
    )
    char = {"name": "甲", "role": "女主", "gender": "female", "武器": "长枪"}
    out = cs.render_character_chat(char)
    assert "武器：长枪" in out


def test_render_chapter_chat_appends_recognized_characters(monkeypatch):
    from engine.setup.chat_summary import render_chapter_chat

    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters",
        lambda text: ["甲", "乙"] if "甲" in text and "乙" in text else [],
    )
    chapter = {"title": "对峙", "stages": [
        {"title": "书房", "location": "书房", "description": "甲和乙在书房对峙"},
    ]}
    out = render_chapter_chat(chapter, 1)
    assert "（识别角色：甲、乙）" in out


def test_render_chapter_chat_warns_when_description_matches_nobody(monkeypatch):
    from engine.setup.chat_summary import render_chapter_chat

    monkeypatch.setattr("engine.memory_recall.entity_index.scan_characters", lambda text: [])
    chapter = {"title": "对峙", "stages": [
        {"title": "书房", "location": "书房", "description": "他和她在书房对峙"},
    ]}
    out = render_chapter_chat(chapter, 1)
    assert "（识别角色：无——请检查是否用了人称代词而非人物全名）" in out


def test_render_chapter_chat_omits_recognition_feedback_when_description_empty(monkeypatch):
    from engine.setup.chat_summary import render_chapter_chat

    called = []
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters",
        lambda text: called.append(text) or [],
    )
    chapter = {"title": "过渡", "stages": [
        {"title": "空镜", "location": "", "description": ""},
    ]}
    out = render_chapter_chat(chapter, 1)
    assert "识别角色" not in out
    assert called == []


def test_geography_names_extracts_named_entries():
    from engine.setup.chat_summary import geography_names

    wb = {"geography": [
        {"name": "废弃车站", "desc": "城郊，久无人至"},
        {"name": "青云观", "desc": "山顶道观"},
    ]}
    assert geography_names(wb) == ["废弃车站", "青云观"]


def test_geography_names_skips_entries_without_name():
    from engine.setup.chat_summary import geography_names

    wb = {"geography": [{"desc": "没有名字"}, {"name": "青云观", "desc": ""}]}
    assert geography_names(wb) == ["青云观"]


def test_geography_names_dedupes_preserving_order():
    from engine.setup.chat_summary import geography_names

    wb = {"geography": [{"name": "青云观"}, {"name": "废弃车站"}, {"name": "青云观"}]}
    assert geography_names(wb) == ["青云观", "废弃车站"]


def test_geography_names_returns_empty_for_missing_or_malformed_input():
    from engine.setup.chat_summary import geography_names

    assert geography_names(None) == []
    assert geography_names({}) == []
    assert geography_names({"geography": "不是列表"}) == []
    assert geography_names({"geography": ["不是dict"]}) == []
