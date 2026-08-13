"""world_bible summary rendering (common to cast/plot)."""
from engine.setup.world.summary import render_world_summary


def test_renders_scalars_and_named_lists():
    wb = {
        "tone": "暗黑", "background": "乱世",
        "factions": [{"name": "甲帮", "desc": "x"}, {"name": "乙门", "desc": "y"}],
        "geography": [{"name": "乌城", "desc": "z"}],
        "power_system": [{"name": "蛊术", "desc": "寄生驱动"}],
        "core_themes": [{"name": "支配", "desc": "d1"}, {"name": "堕落", "desc": "d2"}],
    }
    out = render_world_summary(wb)
    assert "暗黑" in out and "乱世" in out
    assert "甲帮" in out and "乙门" in out and "乌城" in out
    assert "支配" in out and "堕落" in out
    #The desc of power/geography is also spelled into the abstract (name: desc)
    assert "甲帮：x" in out and "乌城：z" in out
    assert "蛊术：寄生驱动" in out


def test_named_list_without_desc_keeps_name():
    out = render_world_summary({"factions": [{"name": "孤帮"}]})
    assert "孤帮" in out and "孤帮：" not in out  #None desc without colon


def test_empty_returns_empty_string():
    assert render_world_summary({}) == ""
    assert render_world_summary(None) == ""


def test_sparse_skips_missing():
    out = render_world_summary({"tone": "暗黑"})
    assert "暗黑" in out and "logline" not in out
