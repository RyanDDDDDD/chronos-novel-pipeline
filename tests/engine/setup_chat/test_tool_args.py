from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_rename_novel_title_args_requires_new_title():
    from engine.setup_chat.tool_args import RenameNovelTitleArgs

    args = RenameNovelTitleArgs(new_title="星海彼岸的旅人")
    assert args.new_title == "星海彼岸的旅人"

    with pytest.raises(ValidationError):
        RenameNovelTitleArgs()


def test_gender_field_description_reflects_content_packs(monkeypatch):
    from engine.setup_chat import tool_args as ta

    monkeypatch.setattr(
        "context.content_packs.get_gender_values", lambda: ["male", "female"]
    )
    desc = ta._gender_field_description()
    assert "male" in desc and "female" in desc and "xeno" not in desc


def test_gender_field_description_includes_extra_genders(monkeypatch):
    from engine.setup_chat import tool_args as ta

    monkeypatch.setattr(
        "context.content_packs.get_gender_values", lambda: ["male", "female", "xeno"]
    )
    assert "xeno" in ta._gender_field_description()


def test_world_named_item_args_keywords_defaults_to_empty_list():
    from engine.setup_chat.tool_args import WorldNamedItemArgs

    item = WorldNamedItemArgs(name="信仰丧失", desc="不再信任神明")
    assert item.keywords == []


def test_world_named_item_args_keywords_round_trips():
    from engine.setup_chat.tool_args import WorldNamedItemArgs

    item = WorldNamedItemArgs(name="信仰丧失", desc="d", keywords=["神像崩塌", "停止祷告"])
    assert item.keywords == ["神像崩塌", "停止祷告"]


def test_world_bible_args_to_bible_includes_keywords():
    from engine.setup_chat.tool_args import WorldBibleArgs, WorldNamedItemArgs

    stub = WorldNamedItemArgs(name="x", desc="d")
    args = WorldBibleArgs(
        tone="t", background="b",
        factions=[stub], geography=[stub], races=[stub],
        power_system=[WorldNamedItemArgs(name="信仰丧失", desc="d", keywords=["神像崩塌"])],
        core_themes=[stub],
    )
    bible = args.to_bible()
    assert bible["power_system"] == [{"name": "信仰丧失", "desc": "d", "keywords": ["神像崩塌"]}]


def test_world_named_item_args_keywords_drops_single_char_entries():
    from engine.setup_chat.tool_args import WorldNamedItemArgs

    item = WorldNamedItemArgs(
        name="信仰丧失", desc="d", keywords=["神", "神像崩塌", "杀", "祷告"]
    )
    assert item.keywords == ["神像崩塌", "祷告"]


def test_world_named_item_args_keywords_strips_and_dedupes():
    from engine.setup_chat.tool_args import WorldNamedItemArgs

    item = WorldNamedItemArgs(
        name="信仰丧失", desc="d", keywords=[" 神像崩塌 ", "神像崩塌", "  ", "祷告"]
    )
    assert item.keywords == ["神像崩塌", "祷告"]


def test_world_named_item_args_keywords_all_invalid_becomes_empty_list():
    from engine.setup_chat.tool_args import WorldNamedItemArgs

    item = WorldNamedItemArgs(name="信仰丧失", desc="d", keywords=["神", "杀", " "])
    assert item.keywords == []
