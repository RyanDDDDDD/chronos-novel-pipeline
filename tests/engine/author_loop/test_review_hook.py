import pytest
from engine.author_loop.review.review_hook import (
    ReviewContext,
    ReviewHook,
    ReviewScore,
)


def test_review_context_holds_fields():
    ctx = ReviewContext(
        beat_intent="拍意图", base_draft="草稿", refined="定稿",
        prev_beat_text=None, directive="指示",
    )
    assert ctx.refined == "定稿"
    assert ctx.prev_beat_text is None


def test_review_score_fields():
    s = ReviewScore(score=8, feedback="丢了声景")
    assert s.score == 8
    assert s.feedback == "丢了声景"


def test_base_hook_defaults_and_notimplemented():
    h = ReviewHook()
    assert h.name == "" and h.weight == 0.0 and h.floor == 0
    assert h.consumes == []
    ctx = ReviewContext("i", "b", "r", None, "d")
    with pytest.raises(NotImplementedError):
        h.build_prompt(ctx)
    with pytest.raises(NotImplementedError):
        h.parse("{}")


def test_consumes_is_per_instance_not_shared():
    #Variable default pitfall to prevent regression: the consumes of two instances do not share the same list
    a, b = ReviewHook(), ReviewHook()
    a.consumes.append("x")
    assert b.consumes == []


def test_review_context_beats_defaults_to_none():
    ctx = ReviewContext("i", "b", "r", None, "d")
    assert ctx.beats is None


def test_review_context_accepts_beats():
    beats = [{"text": "拍0"}, {"text": "拍1"}]
    ctx = ReviewContext("i", "b", "r", None, "d", beats=beats)
    assert ctx.beats == beats


def test_base_hook_evaluate_defaults_to_none():
    h = ReviewHook()
    ctx = ReviewContext("i", "b", "r", None, "d")
    assert h.evaluate(ctx) is None
