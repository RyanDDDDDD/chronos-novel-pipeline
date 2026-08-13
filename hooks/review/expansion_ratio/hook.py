"""Expansion-ratio reviewer: candidate prose must expand the skeleton by at
least EXPANSION_RATIO_FLOOR times the character count. Pure code, no LLM call
-- see ReviewHook.evaluate(). Runtime axis only (stage_review.py's candidate
review); consumes base_draft (skeleton text) + refined (candidate prose).
"""
from __future__ import annotations

from engine.author_loop.review.review_hook import ReviewContext, ReviewHook, ReviewScore
from utils.expand_report import cn_chars

EXPANSION_RATIO_FLOOR = 1.2


class Hook(ReviewHook):
    name = "expansion_ratio"
    display_name = "扩写倍率"
    weight = 1.0
    floor = 6
    consumes = ["base_draft", "refined"]

    def evaluate(self, ctx: ReviewContext) -> ReviewScore | None:
        skeleton_chars = cn_chars(ctx.base_draft)
        if skeleton_chars == 0:
            return ReviewScore(score=10, feedback="")
        prose_chars = cn_chars(ctx.refined)
        if prose_chars >= skeleton_chars * EXPANSION_RATIO_FLOOR:
            return ReviewScore(score=10, feedback="")
        target = int(skeleton_chars * EXPANSION_RATIO_FLOOR)
        feedback = (
            f"当前正文 {prose_chars} 字，骨架 {skeleton_chars} 字，"
            f"未达 {EXPANSION_RATIO_FLOOR} 倍扩写要求（目标 ≥{target} 字）。"
            "请围绕骨架细节补充动作/心理/感官描写与台词，让每一拍写得更丰满。"
        )
        return ReviewScore(score=3, feedback=feedback)
