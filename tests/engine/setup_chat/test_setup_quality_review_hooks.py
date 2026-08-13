from engine.author_loop.review.review_hook import ReviewContext
from engine.author_loop.review.review_loader import discover_review_hooks
from utils.paths import REVIEW_HOOKS_DIR


def _hook(name: str):
    return {h.name: h for h in discover_review_hooks(REVIEW_HOOKS_DIR)}[name]


def _ctx(bible: dict) -> ReviewContext:
    return ReviewContext(
        beat_intent="",
        base_draft="",
        refined="",
        prev_beat_text=None,
        directive="",
        world_text="测试世界观自然语言渲染",
        world_bible=bible,
    )


def _valid_bible(**overrides: object) -> dict:
    base = {
        "tone": "这是一段足够长的世界观基调描述文字",
        "background": "这是一段足够长的世界观背景设定描述文字",
        "factions": [{"name": "甲帮", "desc": "这是一个足够长的派系描述内容"}],
        "geography": [{"name": "乌城", "desc": "这是一个足够长的地理描述内容"}],
        "races": [
            {
                "name": "人类",
                "desc": "人类社会结构复杂，文化习俗丰富，与各方势力紧密关联的日常差异明显",
            }
        ],
        "power_system": [{"name": "机制", "desc": "这是一个足够长的力量体系描述"}],
        "core_themes": [{"name": "支配", "desc": "这是一个足够长的核心主题描述"}],
    }
    base.update(overrides)
    return base


def test_setup_world_completeness_is_discoverable():
    hook = _hook("setup_world_completeness")
    assert hook.consumes == ["world_text", "world_bible"]
    assert hook.display_name == "设定完整度"
    assert hook.floor == 60
    assert hook.weight == 1.0


def test_completeness_single_human_race_long_desc_passes_precheck():
    bible = _valid_bible()
    assert _hook("setup_world_completeness").evaluate(_ctx(bible)) is None


def test_completeness_race_desc_too_short_fails_precheck():
    bible = _valid_bible()
    bible["races"] = [{"name": "人类", "desc": "太短"}]
    result = _hook("setup_world_completeness").evaluate(_ctx(bible))
    assert result is not None
    assert result.score == 45
    assert result.score < _hook("setup_world_completeness").floor
    assert "人类" in result.feedback


def test_completeness_empty_list_fails_precheck():
    bible = _valid_bible()
    bible["factions"] = []
    result = _hook("setup_world_completeness").evaluate(_ctx(bible))
    assert result is not None
    assert result.score == 30


def test_completeness_parse_clamps_score_0_100():
    hook = _hook("setup_world_completeness")
    assert hook.parse('{"score": 150, "feedback": ""}').score == 100
    assert hook.parse('{"score": -5, "feedback": ""}').score == 0


def _cast_ctx(char: dict, **kwargs: object) -> ReviewContext:
    return ReviewContext(
        beat_intent="",
        base_draft="",
        refined="",
        prev_beat_text=None,
        directive="",
        character_card=str(kwargs.get("character_card", "测试角色卡")),
        character=char,
        world_text=str(kwargs.get("world_text", "测试世界观")),
    )


def test_anchors_too_few_fails_precheck():
    char = {"causal_anchors": {"创伤": "abc"}}
    r = _hook("setup_cast_anchors").evaluate(_cast_ctx(char))
    assert r is not None and r.score < 60


def test_anchors_too_short_fails_precheck():
    char = {
        "causal_anchors": {
            "创伤": "这是一段足够长的创伤锚点描述文字",
            "执念": "太短",
        }
    }
    r = _hook("setup_cast_anchors").evaluate(_cast_ctx(char))
    assert r is not None
    assert r.score == 40
    assert "执念" in r.feedback


def test_vividness_too_few_slots_fails_precheck():
    char = {"physique": {"face": "这是一段足够长的面部描写内容", "hair": "短"}}
    r = _hook("setup_cast_vividness").evaluate(_cast_ctx(char))
    assert r is not None and r.score == 45


def test_signature_no_marks_fails_precheck():
    char = {
        "verbal_tic": "",
        "hobbies": [],
        "clothing_dna": {
            "color_palette": ["黑"],
            "materials_preference": [],
        },
    }
    r = _hook("setup_cast_signature").evaluate(_cast_ctx(char))
    assert r is not None and r.score == 50


def test_all_setup_review_hooks_discoverable():
    from engine.author_loop.review.review_loader import REVIEW_HOOKS

    names = {h.name for h in REVIEW_HOOKS}
    expected = {
        "setup_world_completeness",
        "setup_world_tension",
        "setup_world_distinctiveness",
        "setup_cast_anchors",
        "setup_cast_contradiction",
        "setup_cast_vividness",
        "setup_cast_signature",
    }
    assert expected <= names
