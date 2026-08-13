import pytest
from engine.author_loop.review.review_hook import ReviewContext, ReviewHook, ReviewScore
from engine.author_loop.self_review import SelfReviewConfig, run_self_review


class _FixedHook(ReviewHook):
    name = "fixed"
    display_name = "Fixed"
    weight = 1.0
    floor = 60
    consumes = ["world_text"]

    def __init__(self, score: int) -> None:
        super().__init__()
        self._score = score

    def evaluate(self, ctx: ReviewContext) -> ReviewScore | None:
        return ReviewScore(score=self._score, feedback="fb")


@pytest.mark.asyncio
async def test_scale_100_clamps_and_compares_threshold():
    hook = _FixedHook(85)
    ctx = ReviewContext(
        beat_intent="", base_draft="", refined="", prev_beat_text=None, directive="",
        world_text="x",
    )
    cfg = SelfReviewConfig(enabled=True, threshold=80, plugins={}, scale=100)
    v = await run_self_review(ctx, pytest.fail, cfg, hooks=[hook])  # noqa: ARG001
    assert v.action == "accept"
    assert v.composite == 85.0


@pytest.mark.asyncio
async def test_scale_100_rewrite_below_threshold():
    hook = _FixedHook(75)
    ctx = ReviewContext(
        beat_intent="", base_draft="", refined="", prev_beat_text=None, directive="",
        world_text="x",
    )
    cfg = SelfReviewConfig(enabled=True, threshold=80, plugins={}, scale=100)
    v = await run_self_review(ctx, pytest.fail, cfg, hooks=[hook])
    assert v.action == "rewrite"


@pytest.mark.asyncio
async def test_scale_default_10_unchanged():
    hook = _FixedHook(9)
    ctx = ReviewContext(
        beat_intent="", base_draft="", refined="", prev_beat_text=None, directive="",
        world_text="x",
    )
    cfg = SelfReviewConfig(enabled=True, threshold=8, plugins={})
    v = await run_self_review(ctx, pytest.fail, cfg, hooks=[hook])
    assert v.action == "accept"
