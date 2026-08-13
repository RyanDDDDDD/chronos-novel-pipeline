"""Skeleton-fidelity reviewer: does the candidate prose cover every skeleton
beat's key facts without inventing unrelated events? LLM judge -- malformed/
missing verdict degrades to pass (never blocks writing). Runtime axis only
(stage_review.py's candidate review); consumes base_draft (skeleton text) +
refined (candidate prose).
"""
from __future__ import annotations

import os

from engine.author_loop.review.review_hook import ReviewContext, ReviewHook, ReviewScore
from engine.execution.embed_json import parse_embed_json

_PROMPT = os.path.join(os.path.dirname(__file__), "fidelity.md")


class Hook(ReviewHook):
    name = "fidelity"
    display_name = "骨架保真判官"
    weight = 1.0
    floor = 6
    consumes = ["base_draft", "refined"]

    def build_prompt(self, ctx: ReviewContext) -> tuple[str, str]:
        with open(_PROMPT, encoding="utf-8") as f:
            system = f.read()
        user = f"## 骨架\n{ctx.base_draft}\n\n## 正文\n{ctx.refined}"
        return system, user

    def parse(self, raw: str) -> ReviewScore:
        objs = parse_embed_json(raw)
        obj = objs[0] if objs else {}
        verdict = "fail" if str(obj.get("verdict") or "").strip() == "fail" else "pass"
        if verdict == "pass":
            return ReviewScore(score=10, feedback="")
        missing = [str(x).strip() for x in (obj.get("missing") or []) if str(x).strip()]
        invented = [str(x).strip() for x in (obj.get("invented") or []) if str(x).strip()]
        notes = (
            [f"漏写：{m}" for m in missing]
            + [f"编造（骨架未支持）：{x}" for x in invented]
        )
        return ReviewScore(score=3, feedback="\n".join(notes))
