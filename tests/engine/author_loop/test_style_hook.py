from engine.author_loop.review.review_hook import ReviewContext
from engine.author_loop.review.review_loader import discover_review_hooks
from utils.paths import REVIEW_HOOKS_DIR


def _hook():
    hooks = {h.name: h for h in discover_review_hooks(REVIEW_HOOKS_DIR)}
    return hooks["style"]


def test_hook_is_discoverable_with_expected_attrs():
    hook = _hook()
    assert hook.consumes == ["refined"]
    assert hook.floor == 6
    assert hook.weight == 1.0


def test_evaluate_returns_none_when_no_banned_pattern_hit(monkeypatch):
    """没命中禁用正则时 evaluate() 返回 None,交给 build_prompt/parse 的 LLM 判官接手。"""
    import engine.execution.style_guard as sg
    monkeypatch.setattr(sg, "get_compiled_patterns", lambda: [])
    hook = _hook()
    ctx = ReviewContext("", "", "普通正文，没有命中任何禁用句式。", None, "")
    assert hook.evaluate(ctx) is None


def test_evaluate_fails_fast_on_banned_pattern_hit(monkeypatch):
    """命中禁用正则时 evaluate() 直接判 fail(远低于 floor),不必等 LLM 调用。"""
    import re

    import engine.execution.style_guard as sg
    monkeypatch.setattr(sg, "get_compiled_patterns", lambda: [re.compile("微不可察")])
    hook = _hook()
    ctx = ReviewContext("", "", "她微不可察地叹了口气。", None, "")
    result = hook.evaluate(ctx)
    assert result is not None
    assert result.score < hook.floor
    assert "微不可察" in result.feedback


def test_build_prompt_and_parse_unchanged_llm_judge_path():
    hook = _hook()
    ctx = ReviewContext("", "", "定稿正文", None, "")
    system, user = hook.build_prompt(ctx)
    assert "定稿正文" in user
    result = hook.parse('{"score": 8, "feedback": ""}')
    assert result.score == 8
