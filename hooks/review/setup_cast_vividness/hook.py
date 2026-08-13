"""Setup cast vividness reviewer: code prechecks on physique slots, then LLM judge."""
from __future__ import annotations

import os

from engine.author_loop.review.review_hook import ReviewContext, ReviewHook, ReviewScore
from engine.execution.embed_json import parse_embed_json

_PROMPT = os.path.join(os.path.dirname(__file__), "setup_cast_vividness.md")

_MIN_SLOT_LEN = 6


def _cast_user(ctx: ReviewContext) -> str:
    world = ctx.world_text or "（尚未构建世界观，仅评角色卡内部质量）"
    return f"## 世界观（角色须与此一致）\n{world}\n\n## 待评角色\n{ctx.character_card or ''}"


class Hook(ReviewHook):
    name = "setup_cast_vividness"
    display_name = "画面感"
    weight = 1.0
    floor = 60
    consumes = ["character_card", "world_text", "character"]

    def evaluate(self, ctx: ReviewContext) -> ReviewScore | None:
        char = ctx.character
        if not isinstance(char, dict):
            return None

        physique = char.get("physique")
        if not isinstance(physique, dict):
            return ReviewScore(
                score=45,
                feedback="体型描写有效槽位不足，请至少在两处 physique 槽位给出可视觉化的实质描写。",
            )

        filled = sum(
            1
            for v in physique.values()
            if isinstance(v, str) and len(v.strip()) >= _MIN_SLOT_LEN
        )
        if filled < 2:
            return ReviewScore(
                score=45,
                feedback="体型描写有效槽位不足，请至少在两处 physique 槽位给出可视觉化的实质描写。",
            )

        return None

    def build_prompt(self, ctx: ReviewContext) -> tuple[str, str]:
        with open(_PROMPT, encoding="utf-8") as f:
            system = f.read()
        return system, _cast_user(ctx)

    def parse(self, raw: str) -> ReviewScore:
        objs = parse_embed_json(raw)
        obj = objs[0] if objs else {}
        try:
            score = int(obj.get("score", 70))
        except (TypeError, ValueError):
            score = 70
        score = max(0, min(100, score))
        return ReviewScore(score=score, feedback=str(obj.get("feedback", "")).strip())
