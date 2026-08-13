"""Main author of quality self-review node (mechanism layer, no knowledge of plug-ins).

Each loaded review plug-in is run once by LLM and scored 1-10 points → weighted comprehensive score (only the actual participating plug-ins are normalized) +
Single dimension floor double gate → verdict. The consumes field of a plug-in has a missing value in ctx (for example, b0 has no prev)
Or disabled → skip the dimension; a certain plug-in is abnormal → warning skip without blocking.

Single judgment contract: Only the ReviewScore{score,feedback} output by each plug-in parse is recognized, and there is no second set of parsing."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from loguru import logger

from engine.author_loop.review.review_hook import ReviewContext, ReviewHook

CallLLM = Callable[..., Awaitable[tuple[str, int, int]]]


@dataclass
class PluginCfg:
    enabled: bool
    weight: float
    floor: int


@dataclass
class SelfReviewConfig:
    enabled: bool
    threshold: int
    plugins: dict[str, PluginCfg]
    scale: int = 10


@dataclass
class SelfReviewVerdict:
    action: str  # "accept" | "rewrite"
    composite: float
    scores: list[tuple[str, int]]
    feedback: str


def _ctx_has(ctx: ReviewContext, field: str) -> bool:
    """
Whether the field of the plug-in consumes has an evaluable value in ctx (None/empty string is regarded as missing)."""
    val = getattr(ctx, field, None)
    return bool(val) if isinstance(val, str) else val is not None


def _participates(hook: ReviewHook, ctx: ReviewContext, cfg: SelfReviewConfig) -> bool:
    pc = cfg.plugins.get(hook.name)
    if pc is not None and not pc.enabled:
        return False
    #Any field of consumes has a missing value → does not participate in the evaluation (for example, coherence's prev_beat_text is None in b0)
    return all(_ctx_has(ctx, f) for f in hook.consumes)


async def run_self_review(
    ctx: ReviewContext,
    call_llm: CallLLM,
    cfg: SelfReviewConfig,
    hooks: list[ReviewHook],
) -> SelfReviewVerdict:
    scored: list[tuple[ReviewHook, int, str]] = []  # (hook, score, feedback)
    for hook in hooks:
        if not _participates(hook, ctx, cfg):
            continue
        try:
            code_result = hook.evaluate(ctx)
            if code_result is not None:
                result = code_result
            else:
                system, user = hook.build_prompt(ctx)
                raw, _i, _o = await call_llm(
                    system, user, disable_thinking=True, _log_agent=f"review:{hook.name}",
                )
                result = hook.parse(raw or "")
        except Exception as exc:  #noqa: BLE001 — Single plug-in failure does not block other reviews
            logger.warning("[self-review] 插件 {} 评分失败: {}", hook.name, exc)
            continue
        hi = cfg.scale
        lo = 0 if hi == 100 else 1
        score = max(lo, min(hi, int(result.score)))
        scored.append((hook, score, result.feedback))

    scores_out = [(h.name, s) for h, s, _ in scored]
    if not scored:  #No evaluation dimension → release (empty set invariant)
        return SelfReviewVerdict("accept", 0.0, scores_out, "")

    total_w = sum(_weight(cfg, h) for h, _, _ in scored)
    composite = (
        sum(_weight(cfg, h) * s for h, s, _ in scored) / total_w
        if total_w > 0 else float(sum(s for _, s, _ in scored)) / len(scored)
    )

    breached_fb = [
        fb for _h, s, fb in scored
        if _floor(cfg, _h) <= cfg.scale and s < _floor(cfg, _h)
    ]
    below_threshold = composite < cfg.threshold
    if not breached_fb and not below_threshold:
        return SelfReviewVerdict("accept", composite, scores_out, "")

    #Not comprehensive → full-dimensional feedback; only single-dimensional breakdown → only breakdown-dimensional feedback
    sources = [fb for _h, _s, fb in scored] if below_threshold else breached_fb
    feedback = "\n".join(fb for fb in sources if fb.strip())
    return SelfReviewVerdict("rewrite", composite, scores_out, feedback)


def _weight(cfg: SelfReviewConfig, hook: ReviewHook) -> float:
    pc = cfg.plugins.get(hook.name)
    return pc.weight if pc is not None else hook.weight


def _floor(cfg: SelfReviewConfig, hook: ReviewHook) -> int:
    pc = cfg.plugins.get(hook.name)
    return pc.floor if pc is not None else hook.floor
