"""衔接判官：本拍定稿与前一拍正文的承接是否断裂/体位跳变/复读。

b0（无前拍）由节点据 consumes 跳过，本插件不必自处理。打 1–10 + 哪处断裂的反馈。
"""
from __future__ import annotations

import os

from engine.author_loop.review.review_hook import ReviewContext, ReviewHook, ReviewScore
from engine.execution.embed_json import parse_embed_json

_PROMPT = os.path.join(os.path.dirname(__file__), "coherence.md")


class Hook(ReviewHook):
    name = "coherence"
    display_name = "衔接判官"
    weight = 0.4
    floor = 6
    consumes = ["prev_beat_text", "refined"]

    def build_prompt(self, ctx: ReviewContext) -> tuple[str, str]:
        with open(_PROMPT, encoding="utf-8") as f:
            system = f.read()
        user = (
            f"## 前一拍正文\n{ctx.prev_beat_text}\n\n"
            f"## 本拍定稿（待评其与前一拍的承接）\n{ctx.refined}"
        )
        return system, user

    def parse(self, raw: str) -> ReviewScore:
        objs = parse_embed_json(raw)
        obj = objs[0] if objs else {}
        try:
            score = int(obj.get("score", 7))
        except (TypeError, ValueError):
            score = 7
        return ReviewScore(score=score, feedback=str(obj.get("feedback", "")).strip())
