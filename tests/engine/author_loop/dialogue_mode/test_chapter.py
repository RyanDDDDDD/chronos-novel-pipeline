import pytest
from engine.author_loop.dialogue_mode.chapter import extract_entry_points, extract_stages
from engine.author_loop.dialogue_mode.state import BeatInput, StageInput


def test_extract_stages_groups_beats_by_stage():
    skeleton = [
        {"beats": [{"text": "拍甲"}, {"text": "拍乙"}],
         "characters": ["甲", "乙"], "stage_num": 1},
        {"beats": [{"text": "拍丙"}], "characters": ["丙"], "stage_num": 2},
    ]
    stages = extract_stages(skeleton, chapter=3)
    assert [s.stage for s in stages] == [1, 2]
    assert [b.beat_intent for b in stages[0].beats] == ["拍甲", "拍乙"]
    assert stages[0].characters == ["甲", "乙"] and stages[0].chapter == 3
    assert stages[1].characters == ["丙"] and stages[1].stage == 2
    assert [b.beat_intent for b in stages[1].beats] == ["拍丙"]


def test_extract_stages_reads_stage_num():
    """真实骨架 key 是 stage_num,不是 stage——读错会让每 stage 默认 1。"""
    skeleton = [{"beats": [{"text": "第三场"}], "characters": ["甲"], "stage_num": 3}]
    stages = extract_stages(skeleton, chapter=1)
    assert stages[0].stage == 3
    assert stages[0].beats[0].stage == 3


def test_extract_stages_skips_blank_beat_text():
    skeleton = [
        {"beats": [{"text": "  "}, {"text": "有效拍"}, "非法条目"],
         "characters": ["甲"], "stage_num": 1},
    ]
    stages = extract_stages(skeleton, chapter=1)
    assert [b.beat_intent for b in stages[0].beats] == ["有效拍"]


def test_extract_stages_skips_segment_with_no_valid_beats():
    """一个 stage 内 beats 全部为空文本 → 该 stage 不产出(没有可写的内容)。"""
    skeleton = [
        {"beats": [{"text": "  "}], "characters": ["甲"], "stage_num": 1},
        {"beats": [{"text": "有效拍"}], "characters": ["乙"], "stage_num": 2},
    ]
    stages = extract_stages(skeleton, chapter=1)
    assert [s.stage for s in stages] == [2]


def test_extract_stages_empty_skeleton():
    assert extract_stages([], chapter=1) == []


def test_extract_stages_carries_sensation_notes():
    skeleton = [{
        "stage_num": 1, "characters": ["甲"],
        "beats": [{"text": "拍甲", "sensation_notes": ["小腹发烫"]}],
    }]
    stages = extract_stages(skeleton, chapter=1)
    assert stages[0].beats[0].sensation_notes == ["小腹发烫"]


def test_extract_stages_sensation_notes_defaults_empty():
    skeleton = [{"stage_num": 1, "characters": ["甲"], "beats": [{"text": "拍甲"}]}]
    stages = extract_stages(skeleton, chapter=1)
    assert stages[0].beats[0].sensation_notes == []


def test_extract_stages_carries_dialogue_draft():
    skeleton = [{
        "stage_num": 1, "characters": ["甲"],
        "beats": [{"text": "拍甲", "dialogue_draft": "甲：你好。"}],
    }]
    stages = extract_stages(skeleton, chapter=1)
    assert stages[0].beats[0].dialogue_draft == "甲：你好。"


def test_extract_stages_dialogue_draft_defaults_empty():
    skeleton = [{"stage_num": 1, "characters": ["甲"], "beats": [{"text": "拍甲"}]}]
    stages = extract_stages(skeleton, chapter=1)
    assert stages[0].beats[0].dialogue_draft == ""


def test_extract_entry_points_first_appearance_per_character():
    stages = [
        StageInput(chapter=1, stage=2, characters=["甲", "乙"],
                   beats=[BeatInput(beat_intent="拍", characters=["甲", "乙"], chapter=1, stage=2)]),
        StageInput(chapter=1, stage=3, characters=["甲", "乙"],  #甲乙已在 stage2 出现,不再重算
                   beats=[BeatInput(beat_intent="拍", characters=["甲", "乙"], chapter=1, stage=3)]),
        StageInput(chapter=1, stage=4, characters=["丙"],  #丙首次出现在 stage4
                   beats=[BeatInput(beat_intent="拍", characters=["丙"], chapter=1, stage=4)]),
    ]
    assert extract_entry_points(stages) == {"甲": 2, "乙": 2, "丙": 4}


def test_extract_entry_points_empty_stages():
    assert extract_entry_points([]) == {}


@pytest.mark.asyncio
async def test_run_dialogue_chapter_reads_prebuilt(monkeypatch):
    monkeypatch.setattr("engine.author_loop.build.load_prebuilt_skeleton",
                        lambda ch: [{"beats": [{"text": "细骨架拍"}], "characters": ["甲"], "stage_num": 1}])

    captured = {}

    async def fake_persisted(stages, author_turns, call_llm, emit=None, **kw):  # noqa: ANN001
        captured["stages"] = stages
        captured["author_turns"] = author_turns
        captured["prose_style"] = kw.get("prose_style")
        captured["thread_id"] = kw.get("thread_id")
        return "章正文"

    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.react_graph.run_react_chapter_persisted",
        fake_persisted,
    )

    async def fake_llm(s, u, *a, **k):
        return ("x", 1, 1)

    class FakeTurns:
        async def prose_turn(self, messages, *, step):
            return "正文"

    turns = FakeTurns()
    from engine.author_loop.dialogue_mode.chapter import run_dialogue_chapter
    out = await run_dialogue_chapter(
        1, fake_llm, "plain-explicit", author_turns=turns,
    )
    assert out == "章正文"
    assert captured["stages"][0].beats[0].beat_intent == "细骨架拍"
    assert captured["thread_id"] == "ch1"
    assert captured["prose_style"] == "plain-explicit" and captured["author_turns"] is turns
