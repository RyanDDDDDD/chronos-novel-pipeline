import pytest
from engine.archive.archive_error import assert_state_presence, validate_state_presence


def test_validate_state_presence_flags_missing_state():
    parsed = {"1": {"delta": {}}}
    relevant = [{"stage_num": 1}]
    errors = validate_state_presence(parsed, relevant)
    assert any(e.field == "stages.1.state" for e in errors)


def test_validate_state_presence_flags_empty_physiology():
    parsed = {"1": {"delta": {"state": {"physiology": "", "psychology": "x"}}}}
    relevant = [{"stage_num": 1}]
    errors = validate_state_presence(parsed, relevant)
    assert any(e.field == "stages.1.state.physiology" for e in errors)


def test_validate_state_presence_flags_empty_psychology():
    parsed = {"1": {"delta": {"state": {"physiology": "x", "psychology": ""}}}}
    relevant = [{"stage_num": 1}]
    errors = validate_state_presence(parsed, relevant)
    assert any(e.field == "stages.1.state.psychology" for e in errors)


def test_validate_state_presence_accepts_full_state():
    parsed = {"1": {"delta": {"state": {"physiology": "a", "psychology": "b"}}}}
    relevant = [{"stage_num": 1}]
    assert validate_state_presence(parsed, relevant) == []


def test_validate_state_presence_checks_every_relevant_stage():
    parsed = {"1": {"delta": {"state": {"physiology": "a", "psychology": "b"}}}}
    relevant = [{"stage_num": 1}, {"stage_num": 2}]
    errors = validate_state_presence(parsed, relevant)
    assert any(e.field == "stages.2.state" for e in errors)


def test_assert_state_presence_raises_on_missing():
    with pytest.raises(ValueError):
        assert_state_presence({"1": {"delta": {}}}, [{"stage_num": 1}])


def test_assert_state_presence_passes_silently_when_complete():
    assert_state_presence(
        {"1": {"delta": {"state": {"physiology": "a", "psychology": "b"}}}},
        [{"stage_num": 1}],
    )
