"""world_summary render races + character race desc parse."""
from __future__ import annotations

from engine.setup.world.summary import render_world_summary, resolve_race_desc

_WB = {
    "background": "L",
    "factions": [{"name": "教会", "desc": "d"}],
    "races": [{"name": "魔族", "desc": "生有角与尾，皮肤微凉"}, {"name": "人族", "desc": "凡躯"}],
}


def test_summary_includes_races():
    out = render_world_summary(_WB)
    assert "races" in out
    assert "魔族" in out and "生有角与尾" in out


def test_summary_no_races_ok():
    assert render_world_summary({"background": "L"}) == "background：L"


def test_resolve_exact():
    assert resolve_race_desc(_WB, "魔族") == "生有角与尾，皮肤微凉"


def test_resolve_normalizes_case_and_space():
    assert resolve_race_desc({"races": [{"name": "Elf", "desc": "长耳"}]}, "  elf ") == "长耳"


def test_resolve_miss_and_empty():
    assert resolve_race_desc(_WB, "精灵") == ""
    assert resolve_race_desc(_WB, "") == ""
    assert resolve_race_desc(None, "魔族") == ""
    assert resolve_race_desc({"races": "坏类型"}, "魔族") == ""
