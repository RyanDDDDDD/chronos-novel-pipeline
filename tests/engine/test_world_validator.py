"""world_bible schema integrity hard verification test."""
from engine.setup.world.validator import validate_world_bible


def _ok():
    return {
        "tone": "暗黑", "background": "乱世",
        "factions": [{"name": "甲帮", "desc": "x"}],
        "geography": [{"name": "乌城", "desc": "y"}],
        "races": [{"name": "人族", "desc": "凡躯"}],
        "power_system": [{"name": "机制", "desc": "驱动"}],
        "core_themes": [{"name": "支配", "desc": "d"}],
    }


def test_valid_passes():
    assert validate_world_bible(_ok()) == []


def test_missing_scalar_flagged():
    b = _ok(); b["background"] = ""
    assert any("background" in e for e in validate_world_bible(b))


def test_empty_list_flagged():
    b = _ok(); b["factions"] = []
    assert any("factions" in e for e in validate_world_bible(b))


def test_list_item_missing_name_flagged():
    b = _ok(); b["geography"] = [{"desc": "无名"}]
    assert any("geography" in e for e in validate_world_bible(b))


def test_core_themes_item_missing_name_desc_flagged():
    b = _ok(); b["core_themes"] = [{"x": 1}]
    assert any("core_themes" in e for e in validate_world_bible(b))


def test_races_required():
    b = _ok()
    del b["races"]
    assert any("races" in e for e in validate_world_bible(b))


def test_races_item_needs_name_desc():
    b = _ok()
    b["races"] = [{"name": "人族"}]
    assert any("races" in e for e in validate_world_bible(b))


def test_valid_bible_with_races_passes():
    assert validate_world_bible(_ok()) == []


def test_power_system_empty_list_flagged():
    b = _ok(); b["power_system"] = []
    assert any("power_system" in e for e in validate_world_bible(b))


def test_power_system_item_missing_desc_flagged():
    b = _ok(); b["power_system"] = [{"name": "蛊虫"}]
    assert any("power_system" in e for e in validate_world_bible(b))


def test_core_themes_empty_list_flagged():
    b = _ok(); b["core_themes"] = []
    assert any("core_themes" in e for e in validate_world_bible(b))
