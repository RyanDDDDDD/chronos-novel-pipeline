import pytest
from engine.author_loop.review.review_hook import ReviewContext, ReviewHook, ReviewScore
from engine.author_loop.self_review import (
    PluginCfg,
    SelfReviewConfig,
    run_self_review,
)


class _StubHook(ReviewHook):
    def __init__(self, name, score, *, consumes=("refined",)):
        self.name = name
        self.display_name = name
        self.consumes = list(consumes)
        self._score = score

    def build_prompt(self, ctx):
        return (f"sys-{self.name}", "user")

    def parse(self, raw):
        return ReviewScore(score=self._score, feedback=f"fb-{self.name}")


def _ctx(prev="上一拍"):
    return ReviewContext("意图", "草稿", "定稿", prev, "指示")


async def _fake_llm(system, user, **kw):
    return ("ignored-raw", 0, 0)


def _cfg(plugins, threshold=7):
    return SelfReviewConfig(
        enabled=True, threshold=threshold,
        plugins={n: PluginCfg(True, w, f) for n, (w, f) in plugins.items()},
    )


class _CodeOnlyStub(ReviewHook):
    def __init__(self, name, score, feedback=""):
        self.name = name
        self.display_name = name
        self.consumes = []
        self._score = score
        self._feedback = feedback

    def evaluate(self, ctx):
        return ReviewScore(score=self._score, feedback=self._feedback)


@pytest.mark.asyncio
async def test_code_only_hook_never_calls_llm_and_rewrites_on_breach():
    calls = []

    async def spy_llm(system, user, **kw):
        calls.append((system, user))
        return ("ignored-raw", 0, 0)

    hooks = [_CodeOnlyStub("code_check", 3, "代码判违规")]
    cfg = _cfg({"code_check": (1.0, 6)})
    v = await run_self_review(_ctx(), spy_llm, cfg, hooks)
    assert calls == []  # never called the LLM
    assert v.action == "rewrite"
    assert "代码判违规" in v.feedback


@pytest.mark.asyncio
async def test_code_only_hook_accepts_when_score_above_floor():
    async def forbidden_llm(system, user, **kw):
        raise AssertionError("code-only hook must not call the LLM")

    hooks = [_CodeOnlyStub("code_check", 10, "")]
    cfg = _cfg({"code_check": (1.0, 6)})
    v = await run_self_review(_ctx(), forbidden_llm, cfg, hooks)
    assert v.action == "accept"


@pytest.mark.asyncio
async def test_code_only_and_llm_hooks_can_coexist():
    hooks = [_CodeOnlyStub("code_check", 10, ""), _StubHook("style", 9)]
    cfg = _cfg({"code_check": (0.5, 6), "style": (0.5, 6)})
    v = await run_self_review(_ctx(), _fake_llm, cfg, hooks)
    assert v.action == "accept"
    assert [n for n, _ in v.scores] == ["code_check", "style"]


@pytest.mark.asyncio
async def test_all_pass_accepts():
    hooks = [_StubHook("deletion", 9), _StubHook("coherence", 8)]
    cfg = _cfg({"deletion": (0.6, 7), "coherence": (0.4, 6)})
    v = await run_self_review(_ctx(), _fake_llm, cfg, hooks)
    assert v.action == "accept"
    assert v.composite == pytest.approx((0.6 * 9 + 0.4 * 8) / 1.0)


@pytest.mark.asyncio
async def test_single_floor_breach_rewrites_even_if_composite_high():
    #Delete score=4 to break through floor 7; connecting to the full score raises the overall score to 6.4, still higher than threshold 6 → only refills the breakdown dimension
    hooks = [_StubHook("deletion", 4), _StubHook("coherence", 10)]
    cfg = _cfg({"deletion": (0.6, 7), "coherence": (0.4, 6)}, threshold=6)
    v = await run_self_review(_ctx(), _fake_llm, cfg, hooks)
    assert v.action == "rewrite"
    assert "fb-deletion" in v.feedback
    assert "fb-coherence" not in v.feedback  #Only recharge the breakdown dimension


@pytest.mark.asyncio
async def test_composite_below_threshold_rewrites():
    hooks = [_StubHook("deletion", 7), _StubHook("coherence", 6)]
    cfg = _cfg({"deletion": (0.6, 7), "coherence": (0.4, 6)}, threshold=8)
    v = await run_self_review(_ctx(), _fake_llm, cfg, hooks)
    assert v.action == "rewrite"  #Comprehensive 6.6 < 8, full-dimensional recharge
    assert "fb-deletion" in v.feedback and "fb-coherence" in v.feedback


@pytest.mark.asyncio
async def test_b0_skips_coherence_when_prev_none():
    #coherence consumes prev_beat_text; skip the plug-in when prev=None, only press deletion to rule
    hooks = [_StubHook("deletion", 9),
             _StubHook("coherence", 1, consumes=("prev_beat_text", "refined"))]
    cfg = _cfg({"deletion": (0.6, 7), "coherence": (0.4, 6)})
    v = await run_self_review(_ctx(prev=None), _fake_llm, cfg, hooks)
    assert v.action == "accept"  #coherence skipped, not dragged down
    assert [n for n, _ in v.scores] == ["deletion"]
    assert v.composite == pytest.approx(9.0)  #Only deletion normalized


@pytest.mark.asyncio
async def test_plugin_exception_is_skipped_not_fatal():
    class _Boom(_StubHook):
        def parse(self, raw):
            raise ValueError("boom")
    hooks = [_StubHook("deletion", 9), _Boom("coherence", 0)]
    cfg = _cfg({"deletion": (0.6, 7), "coherence": (0.4, 6)})
    v = await run_self_review(_ctx(), _fake_llm, cfg, hooks)
    assert v.action == "accept"
    assert [n for n, _ in v.scores] == ["deletion"]


@pytest.mark.asyncio
async def test_disabled_plugin_excluded():
    hooks = [_StubHook("deletion", 9), _StubHook("coherence", 1)]
    cfg = SelfReviewConfig(
        enabled=True, threshold=7,
        plugins={"deletion": PluginCfg(True, 0.6, 7),
                 "coherence": PluginCfg(False, 0.4, 6)},  #Turn off connection
    )
    v = await run_self_review(_ctx(), _fake_llm, cfg, hooks)
    assert v.action == "accept"
    assert [n for n, _ in v.scores] == ["deletion"]


@pytest.mark.asyncio
async def test_no_participating_plugins_accepts():
    #All are skipped/disabled by consumes → unevaluable → released (empty set invariant)
    hooks = [_StubHook("coherence", 1, consumes=("prev_beat_text",))]
    cfg = _cfg({"coherence": (0.4, 6)})
    v = await run_self_review(_ctx(prev=None), _fake_llm, cfg, hooks)
    assert v.action == "accept"
    assert v.scores == []
