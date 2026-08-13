from engine.author_loop.review.review_hook import ReviewContext
from engine.author_loop.review.review_loader import discover_review_hooks
from utils.paths import REVIEW_HOOKS_DIR


def _hook():
    hooks = {h.name: h for h in discover_review_hooks(REVIEW_HOOKS_DIR)}
    return hooks["fidelity"]


def test_hook_is_discoverable_with_expected_attrs():
    hook = _hook()
    assert hook.consumes == ["base_draft", "refined"]
    assert hook.floor == 6
    assert hook.weight == 1.0


def test_build_prompt_includes_skeleton_and_prose():
    hook = _hook()
    ctx = ReviewContext("", "骨架原文", "正文原文", None, "")
    system, user = hook.build_prompt(ctx)
    assert "骨架原文" in user and "正文原文" in user


def test_parse_pass_verdict_scores_ten_no_feedback():
    hook = _hook()
    result = hook.parse('{"verdict": "pass", "missing": [], "invented": []}')
    assert result.score == 10
    assert result.feedback == ""


def test_parse_fail_verdict_below_floor_with_missing_and_invented_notes():
    hook = _hook()
    raw = (
        '{"verdict": "fail", "missing": ["拍2的关键情节"], '
        '"invented": ["骨架未支持的情节"]}'
    )
    result = hook.parse(raw)
    assert result.score < hook.floor
    assert "拍2的关键情节" in result.feedback
    assert "骨架未支持的情节" in result.feedback


def test_parse_malformed_json_degrades_to_pass():
    """判官解析失败(LLM 没吐合法 JSON)按 pass 处理,不阻塞写作。"""
    hook = _hook()
    result = hook.parse("不是 JSON 的胡话")
    assert result.score == 10
