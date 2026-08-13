"""Setup world tension reviewer: LLM judge for actionable conflict between factions/themes/power."""
from __future__ import annotations

import os

from engine.author_loop.review.review_hook import ReviewContext, ReviewHook, ReviewScore
from engine.execution.embed_json import parse_embed_json

_PROMPT = os.path.join(os.path.dirname(__file__), "setup_world_tension.md")


class Hook(ReviewHook):
    name = "setup_world_tension"
    display_name = "冲突张力"
    weight = 1.0
    floor = 60
    consumes = ["world_text"]

    def build_prompt(self, ctx: ReviewContext) -> tuple[str, str]:
        with open(_PROMPT, encoding="utf-8") as f:
            system = f.read()
        user = f"## 待评世界观\n{ctx.world_text or ''}"
        return system, user

    def parse(self, raw: str) -> ReviewScore:
        objs = parse_embed_json(raw)
        obj = objs[0] if objs else {}
        try:
            score = int(obj.get("score", 70))
        except (TypeError, ValueError):
            score = 70
        score = max(0, min(100, score))
        return ReviewScore(score=score, feedback=str(obj.get("feedback", "")).strip())
