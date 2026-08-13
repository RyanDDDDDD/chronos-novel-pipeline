"""Beat 数据模型 / replace_beat op / 声线查询参数的形状测试。"""
import pytest
from engine.setup_chat.tool_args import (
    BeatArgs,
    PatchChapterOpArgs,
    PatchOp,
    QueryCharacterVoiceArgs,
    SkeletonStageArgs,
    StagePatchFields,
)
from pydantic import ValidationError


def test_beat_args_text_required():
    with pytest.raises(ValidationError):
        BeatArgs.model_validate({"text": ""})


def test_skeleton_stage_args_overview_shape():
    s = SkeletonStageArgs.model_validate({"stage_num": 1, "overview": "本段概述"})
    assert s.stage_num == 1
    assert s.overview == "本段概述"


def test_skeleton_stage_args_overview_defaults_to_empty():
    s = SkeletonStageArgs.model_validate({"stage_num": 1})
    assert s.overview == ""


def test_stage_patch_fields_beats_applied():
    f = StagePatchFields.model_validate({"beats": [{"text": "拍一"}]})
    applied = f.applied()
    assert applied["beats"][0]["text"] == "拍一"
    assert "skeleton" not in StagePatchFields.model_fields


def test_replace_beat_op_requires_locator_and_beat():
    op = PatchChapterOpArgs.model_validate({
        "op": "replace_beat", "stage_num": 2, "beat_idx": 0, "beat": {"text": "新拍"},
    })
    assert op.op == PatchOp.REPLACE_BEAT
    with pytest.raises(ValidationError):
        PatchChapterOpArgs.model_validate({"op": "replace_beat", "stage_num": 2})
    with pytest.raises(ValidationError):
        PatchChapterOpArgs.model_validate({"op": "replace_beat", "stage_num": 2, "beat_idx": 0})


def test_query_character_voice_args():
    a = QueryCharacterVoiceArgs.model_validate(
        {"character": "甲", "chapter": 1, "stage_num": 2})
    assert a.character == "甲" and a.chapter == 1 and a.stage_num == 2
    with pytest.raises(ValidationError):
        QueryCharacterVoiceArgs.model_validate({"character": "", "chapter": 1, "stage_num": 2})


def test_beat_args_dialogue_draft_defaults_empty():
    b = BeatArgs.model_validate({"text": "拍正文"})
    assert b.dialogue_draft == ""


def test_set_beat_dialogue_op_requires_locator_and_dialogue_draft():
    op = PatchChapterOpArgs.model_validate({
        "op": "set_beat_dialogue", "stage_num": 1, "beat_idx": 0, "dialogue_draft": "台词草稿",
    })
    assert op.op == PatchOp.SET_BEAT_DIALOGUE
    assert op.dialogue_draft == "台词草稿"
    with pytest.raises(ValidationError):
        PatchChapterOpArgs.model_validate({"op": "set_beat_dialogue", "stage_num": 1})
    with pytest.raises(ValidationError):
        PatchChapterOpArgs.model_validate(
            {"op": "set_beat_dialogue", "stage_num": 1, "beat_idx": 0},
        )


def test_set_beat_dialogue_op_allows_empty_string():
    op = PatchChapterOpArgs.model_validate({
        "op": "set_beat_dialogue", "stage_num": 1, "beat_idx": 0, "dialogue_draft": "",
    })
    assert op.dialogue_draft == ""
