"""Setup world distinctiveness reviewer: LLM judge for genre identity vs tropes."""
from __future__ import annotations

import os

from engine.author_loop.review.review_hook import ReviewContext, ReviewHook, ReviewScore
from engine.execution.embed_json import parse_embed_json

_PROMPT = os.path.join(os.path.dirname(__file__), "setup_world_distinctiveness.md")


class Hook(ReviewHook):
    name = "setup_world_distinctiveness"
    display_name = "题材辨识度"
    weight = 1.0
    floor = 60
    consumes = ["world_text"]

    def build_prompt(self, ctx: ReviewContext) -> tuple[str, str]:
        with open(_PROMPT, encoding="utf-8") as f:
            system = f.read()
        parts = [f"## 待评世界观\n{ctx.world_text or ''}"]
        brief = (ctx.novel_brief or "").strip()
        if brief:
            parts.append(f"## 作品 brief（须与下列世界观气质一致）\n{brief}")
        user = "\n\n".join(parts)
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
