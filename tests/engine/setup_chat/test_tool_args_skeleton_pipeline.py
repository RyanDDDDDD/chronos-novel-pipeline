import pytest
from engine.setup_chat.tool_args import (
    SetChapterDirectionArgs,
    SetStageExtensionsArgs,
    SetStageLensArgs,
)
from pydantic import ValidationError


def test_set_chapter_direction_args_requires_nonempty_direction():
    args = SetChapterDirectionArgs(chapter=2, direction="甲线：信任到崩解")
    assert args.chapter == 2 and args.direction == "甲线：信任到崩解"
    with pytest.raises(ValidationError):
        SetChapterDirectionArgs(chapter=2, direction="")


def test_set_stage_lens_args_requires_at_least_one_angle():
    args = SetStageLensArgs(chapter=2, stage_num=1, angles=["压迫感", "信息差"])
    assert args.angles == ["压迫感", "信息差"]
    with pytest.raises(ValidationError):
        SetStageLensArgs(chapter=2, stage_num=1, angles=[])


def test_set_stage_extensions_args_allows_empty_list():
    args = SetStageExtensionsArgs(chapter=2, stage_num=1, extensions=[])
    assert args.extensions == []
    args2 = SetStageExtensionsArgs(chapter=2, stage_num=1, extensions=["情景1"])
    assert args2.extensions == ["情景1"]
