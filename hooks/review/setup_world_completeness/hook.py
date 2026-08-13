"""Setup world completeness reviewer: code prechecks on world_bible structure,
then LLM judge for substantive content quality."""
from __future__ import annotations

import os

from engine.author_loop.review.review_hook import ReviewContext, ReviewHook, ReviewScore
from engine.execution.embed_json import parse_embed_json

_PROMPT = os.path.join(os.path.dirname(__file__), "setup_world_completeness.md")

_NAMED_LISTS = ("factions", "geography", "races", "power_system", "core_themes")

_LIST_LABELS: dict[str, str] = {
    "factions": "势力",
    "geography": "地理",
    "races": "种族",
    "power_system": "力量体系",
    "core_themes": "核心主题",
}


class Hook(ReviewHook):
    name = "setup_world_completeness"
    display_name = "设定完整度"
    weight = 1.0
    floor = 60
    consumes = ["world_text", "world_bible"]

    def evaluate(self, ctx: ReviewContext) -> ReviewScore | None:
        bible = ctx.world_bible
        if not isinstance(bible, dict):
            return None

        for key in _NAMED_LISTS:
            items = bible.get(key)
            if isinstance(items, list) and len(items) == 0:
                label = _LIST_LABELS[key]
                return ReviewScore(
                    score=30,
                    feedback=f"缺少{label}维度内容，请补充实质设定。",
                )

        for key in _NAMED_LISTS:
            items = bible.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                desc = str(item.get("desc", "")).strip()
                if not desc:
                    name = str(item.get("name", "未命名"))
                    return ReviewScore(
                        score=35,
                        feedback=f"「{name}」缺少描述，请为每条设定补充可支撑写作的说明。",
                    )

        for key, label in (("tone", "基调"), ("background", "背景")):
            val = str(bible.get(key, "")).strip()
            if len(val) < 15:
                return ReviewScore(
                    score=40,
                    feedback=f"{label}过短，请扩写世界观立意与时代/社会背景。",
                )

        for key in _NAMED_LISTS:
            items = bible.get(key)
            if not isinstance(items, list):
                continue
            min_len = 20 if key == "races" else 8
            for item in items:
                if not isinstance(item, dict):
                    continue
                desc = str(item.get("desc", "")).strip()
                if not desc:
                    continue
                if len(desc) < min_len:
                    name = str(item.get("name", "未命名"))
                    if key == "races":
                        feedback = (
                            f"「{name}」种族描述过短，请补充社会结构、文化习俗、"
                            "与力量体系/势力的关联及日常差异等细节。"
                        )
                    else:
                        feedback = f"「{name}」描述过短，请展开为可独立支撑写作的实质内容。"
                    return ReviewScore(score=45, feedback=feedback)

        return None

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
