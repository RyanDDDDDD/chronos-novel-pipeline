"""Setup cast anchors reviewer: code prechecks on causal_anchors, then LLM judge."""
from __future__ import annotations

import os

from engine.author_loop.review.review_hook import ReviewContext, ReviewHook, ReviewScore
from engine.execution.embed_json import parse_embed_json

_PROMPT = os.path.join(os.path.dirname(__file__), "setup_cast_anchors.md")


def _cast_user(ctx: ReviewContext) -> str:
    world = ctx.world_text or "（尚未构建世界观，仅评角色卡内部质量）"
    return f"## 世界观（角色须与此一致）\n{world}\n\n## 待评角色\n{ctx.character_card or ''}"


class Hook(ReviewHook):
    name = "setup_cast_anchors"
    display_name = "因果锚点"
    weight = 1.0
    floor = 60
    consumes = ["character_card", "world_text", "character"]

    def evaluate(self, ctx: ReviewContext) -> ReviewScore | None:
        char = ctx.character
        if not isinstance(char, dict):
            return None

        anchors = char.get("causal_anchors")
        if not isinstance(anchors, dict):
            return ReviewScore(
                score=35,
                feedback="因果锚点不足，请至少补充两条具体、可推演行为的创伤/执念/渴望等锚点。",
            )

        valid = {
            k: v.strip()
            for k, v in anchors.items()
            if isinstance(v, str) and v.strip()
        }
        if len(valid) < 2:
            return ReviewScore(
                score=35,
                feedback="因果锚点不足，请至少补充两条具体、可推演行为的创伤/执念/渴望等锚点。",
            )

        for key, text in valid.items():
            if len(text) < 10:
                return ReviewScore(
                    score=40,
                    feedback=f"锚点「{key}」过短，请展开为可推演具体行为与选择的实质描述。",
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
