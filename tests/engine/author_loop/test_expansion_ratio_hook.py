from engine.author_loop.review.review_hook import ReviewContext
from engine.author_loop.review.review_loader import discover_review_hooks
from utils.paths import REVIEW_HOOKS_DIR


def _hook():
    hooks = {h.name: h for h in discover_review_hooks(REVIEW_HOOKS_DIR)}
    return hooks["expansion_ratio"]


def test_hook_is_discoverable_with_expected_attrs():
    hook = _hook()
    assert hook.consumes == ["base_draft", "refined"]
    assert hook.floor == 6
    assert hook.weight == 1.0


def test_passes_at_exact_floor():
    from hooks.review.expansion_ratio.hook import EXPANSION_RATIO_FLOOR
    hook = _hook()
    ctx = ReviewContext("", "甲" * 100, "乙" * int(100 * EXPANSION_RATIO_FLOOR), None, "")
    result = hook.evaluate(ctx)
    assert result is not None
    assert result.score == 10
    assert result.feedback == ""


def test_fails_just_under_floor():
    from hooks.review.expansion_ratio.hook import EXPANSION_RATIO_FLOOR
    hook = _hook()
    ctx = ReviewContext("", "甲" * 100, "乙" * (int(100 * EXPANSION_RATIO_FLOOR) - 1), None, "")
    result = hook.evaluate(ctx)
    assert result is not None
    assert result.score == 3
    assert str(int(100 * EXPANSION_RATIO_FLOOR)) in result.feedback
    assert "100" in result.feedback


def test_passes_for_empty_skeleton():
    """空骨架无从比较扩写倍数,不该崩、也不该判 fail。"""
    hook = _hook()
    ctx = ReviewContext("", "", "随便写点什么", None, "")
    result = hook.evaluate(ctx)
    assert result is not None
    assert result.score == 10
