"""Build_round_from_md's QuestionType is fully implemented."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "backend"))

from engine.execution.agent_hook import QuestionType, build_round_from_md  # noqa: E402


def test_build_round_type_is_enum():
    spec = build_round_from_md("## ROUND global\n出题\n", 0, None)
    assert spec is not None
    assert spec["type"] is QuestionType.GLOBAL
    assert isinstance(spec["type"], QuestionType)


def test_build_round_invalid_type_falls_back_segment():
    spec = build_round_from_md("## ROUND bogus\n出题\n", 0, None)
    assert spec is not None
    assert spec["type"] is QuestionType.SEGMENT
