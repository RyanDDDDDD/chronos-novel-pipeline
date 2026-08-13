"""Style reviewer: detect AI-ish clichés in the refined stage text.

This axis is per-stage (no prev/cur comparison). It is intentionally not part
of the transition (pair-based) review map; see
engine.setup_chat.chapter_review::run_chapter_stage_review. Also reused by the
author_loop runtime candidate-review axis (stage_review.py) -- the same
judge, toggled independently per axis via disabled_buildtime_review_hooks /
disabled_runtime_review_hooks.

evaluate() adds a fast code-only precheck (banned-regex hit -> immediate
fail, skipping the LLM call); no hit -> None, falls through to the LLM judge
below (build_prompt/parse). This subsumes what used to be a separate
"banned_regex" check hardcoded in author_loop/dialogue_mode/observer.py
(retired -- same criteria, one judge instead of two).
"""
from __future__ import annotations

import os

from engine.author_loop.review.review_hook import ReviewContext, ReviewHook, ReviewScore
from engine.execution import style_guard
from engine.execution.embed_json import parse_embed_json

_PROMPT = os.path.join(os.path.dirname(__file__), "style.md")


class Hook(ReviewHook):
    name = "style"
    display_name = "文风判官"
    weight = 1.0
    floor = 6
    consumes = ["refined"]

    def evaluate(self, ctx: ReviewContext) -> ReviewScore | None:
        hit = style_guard.find_violation(ctx.refined, style_guard.get_compiled_patterns())
        if hit is None:
            return None
        return ReviewScore(score=1, feedback=f"命中禁用句式：「{hit.group(0)}」")

    def build_prompt(self, ctx: ReviewContext) -> tuple[str, str]:
        with open(_PROMPT, encoding="utf-8") as f:
            system = f.read()
        user = f"## 正文\n{ctx.refined}"
        return system, user

    def parse(self, raw: str) -> ReviewScore:
        objs = parse_embed_json(raw)
        obj = objs[0] if objs else {}
        try:
            score = int(obj.get("score", 7))
        except (TypeError, ValueError):
            score = 7
        return ReviewScore(score=score, feedback=str(obj.get("feedback", "")).strip())
