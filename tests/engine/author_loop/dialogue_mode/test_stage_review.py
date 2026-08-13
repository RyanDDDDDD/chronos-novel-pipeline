"""stage_review.py: runtime review axis wiring (map-reduce via the shared
hooks/review/ registry) + feedback rendering."""
import pytest
from engine.author_loop.dialogue_mode.stage_review import (
    RUNTIME_HOOK_NAMES,
    ReviewResult,
    _active_runtime_hooks,
    render_review_feedback,
    review_candidate,
)


def test_runtime_hook_names_contains_expected_three():
    assert set(RUNTIME_HOOK_NAMES) == {"fidelity", "expansion_ratio", "style"}


def test_active_runtime_hooks_excludes_disabled(monkeypatch):
    import engine.author_loop.dialogue_mode.stage_review as sr

    class _FakeHook:
        def __init__(self, name):
            self.name = name

    monkeypatch.setattr(sr, "REVIEW_HOOKS", [_FakeHook("fidelity"), _FakeHook("style")])
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"disabled_runtime_review_hooks": ["style"]},
    )
    active = _active_runtime_hooks()
    assert [h.name for h in active] == ["fidelity"]


def test_active_runtime_hooks_returns_all_when_none_disabled(monkeypatch):
    import engine.author_loop.dialogue_mode.stage_review as sr

    class _FakeHook:
        def __init__(self, name):
            self.name = name

    monkeypatch.setattr(sr, "REVIEW_HOOKS", [_FakeHook("fidelity"), _FakeHook("style")])
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"disabled_runtime_review_hooks": []},
    )
    active = _active_runtime_hooks()
    assert [h.name for h in active] == ["fidelity", "style"]


async def _fake_llm(system, user, **kw):
    return ("ignored", 0, 0)


@pytest.mark.asyncio
async def test_review_candidate_no_active_hooks_accepts(monkeypatch):
    import engine.author_loop.dialogue_mode.stage_review as sr
    monkeypatch.setattr(sr, "_active_runtime_hooks", lambda: [])
    result = await review_candidate(skeleton_text="骨架", prose="正文", call_llm=_fake_llm)
    assert result.passed is True
    assert result.notes == []


@pytest.mark.asyncio
async def test_review_candidate_builds_context_and_calls_run_self_review(monkeypatch):
    """skeleton_text/prose 要正确映射进 ReviewContext(base_draft/refined),
    并把当前生效的 runtime hooks 原样传给 run_self_review。"""
    import engine.author_loop.dialogue_mode.stage_review as sr
    import engine.author_loop.self_review as self_review_mod

    class _FakeHook:
        def __init__(self, name, floor):
            self.name = name
            self.floor = floor

    hooks = [_FakeHook("fidelity", 6), _FakeHook("style", 6)]
    monkeypatch.setattr(sr, "_active_runtime_hooks", lambda: hooks)

    captured = {}

    async def fake_run_self_review(ctx, call_llm, cfg, hooks):
        captured["ctx"] = ctx
        captured["hooks"] = hooks
        return self_review_mod.SelfReviewVerdict("accept", 9.0, [], "")

    monkeypatch.setattr(sr, "run_self_review", fake_run_self_review)

    await review_candidate(skeleton_text="骨架原文", prose="正文原文", call_llm=_fake_llm)
    assert captured["ctx"].base_draft == "骨架原文"
    assert captured["ctx"].refined == "正文原文"
    assert captured["hooks"] == hooks


@pytest.mark.asyncio
async def test_review_candidate_passes_when_verdict_accepts(monkeypatch):
    import engine.author_loop.dialogue_mode.stage_review as sr
    import engine.author_loop.self_review as self_review_mod

    class _FH:
        floor = 6

    monkeypatch.setattr(sr, "_active_runtime_hooks", lambda: [_FH()])

    async def fake_run_self_review(ctx, call_llm, cfg, hooks):
        return self_review_mod.SelfReviewVerdict("accept", 9.0, [], "")

    monkeypatch.setattr(sr, "run_self_review", fake_run_self_review)
    result = await review_candidate(skeleton_text="骨架", prose="正文", call_llm=_fake_llm)
    assert result.passed is True
    assert result.notes == []


@pytest.mark.asyncio
async def test_review_candidate_combines_multiple_fail_notes(monkeypatch):
    """字数不够 + 保真漏拍同时发生 → 反馈里两条都要有。"""
    import engine.author_loop.dialogue_mode.stage_review as sr
    import engine.author_loop.self_review as self_review_mod

    class _FH:
        floor = 6

    monkeypatch.setattr(sr, "_active_runtime_hooks", lambda: [_FH()])

    async def fake_run_self_review(ctx, call_llm, cfg, hooks):
        return self_review_mod.SelfReviewVerdict(
            "rewrite", 4.0, [], "拍1的关键事实\n扩写要求未达标",
        )

    monkeypatch.setattr(sr, "run_self_review", fake_run_self_review)
    result = await review_candidate(skeleton_text="骨架", prose="正文", call_llm=_fake_llm)
    assert result.passed is False
    joined = "\n".join(result.notes)
    assert "拍1的关键事实" in joined
    assert "扩写要求未达标" in joined


def test_render_review_feedback_lists_all_notes():
    result = ReviewResult(passed=False, notes=["漏写：拍1", "字数不够"])
    text = render_review_feedback(result)
    assert "漏写：拍1" in text
    assert "字数不够" in text
    assert "审核未通过" in text
