from engine.author_loop.dialogue_mode.state import BeatInput, StageInput


def test_stage_input_holds_beats_and_characters():
    beats = [
        BeatInput(beat_intent="拍甲", characters=["甲"], chapter=1, stage=1),
        BeatInput(beat_intent="拍乙", characters=["乙"], chapter=1, stage=1),
    ]
    stage = StageInput(chapter=1, stage=1, characters=["甲", "乙"], beats=beats)
    assert stage.chapter == 1 and stage.stage == 1
    assert stage.characters == ["甲", "乙"]
    assert [b.beat_intent for b in stage.beats] == ["拍甲", "拍乙"]


def test_stage_input_defaults_empty():
    stage = StageInput(chapter=1, stage=1)
    assert stage.characters == []
    assert stage.beats == []
