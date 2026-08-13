"""Setup cast signature reviewer: code prechecks on tic/hobbies/clothing, then LLM judge."""
from __future__ import annotations

import os

from engine.author_loop.review.review_hook import ReviewContext, ReviewHook, ReviewScore
from engine.execution.embed_json import parse_embed_json

_PROMPT = os.path.join(os.path.dirname(__file__), "setup_cast_signature.md")

_GENERIC_PALETTE = frozenset({"黑", "白", "灰"})


def _cast_user(ctx: ReviewContext) -> str:
    world = ctx.world_text or "（尚未构建世界观，仅评角色卡内部质量）"
    return f"## 世界观（角色须与此一致）\n{world}\n\n## 待评角色\n{ctx.character_card or ''}"


def _is_generic_clothing(clothing: dict) -> bool:
    palette = clothing.get("color_palette")
    materials = clothing.get("materials_preference")
    signature = str(clothing.get("signature_outfit") or "").strip()
    accessories = clothing.get("accessories")
    if not isinstance(palette, list):
        palette = []
    if not isinstance(materials, list):
        materials = []
    if isinstance(accessories, list) and any(str(x).strip() for x in accessories):
        return False
    if signature and "待细化" not in signature and "由旧数据迁移" not in signature:
        return False
    if materials:
        return False
    if not palette:
        return True
    if len(palette) == 1 and str(palette[0]).strip() in _GENERIC_PALETTE:
        return True
    return False


class Hook(ReviewHook):
    name = "setup_cast_signature"
    display_name = "辨识度配饰"
    weight = 1.0
    floor = 60
    consumes = ["character_card", "world_text", "character"]

    def evaluate(self, ctx: ReviewContext) -> ReviewScore | None:
        char = ctx.character
        if not isinstance(char, dict):
            return None

        verbal_tic = str(char.get("verbal_tic") or "").strip()
        hobbies = char.get("hobbies")
        if not isinstance(hobbies, list):
            hobbies = []
        has_hobbies = any(isinstance(h, str) and h.strip() for h in hobbies)

        clothing = char.get("clothing_dna")
        if not isinstance(clothing, dict):
            clothing = {}

        if not verbal_tic and not has_hobbies and _is_generic_clothing(clothing):
            return ReviewScore(
                score=50,
                feedback=(
                    "缺少辨识度标志：请补充口癖、爱好，或给出非泛化的着装色系/材质偏好，"
                    "并与世界地理、势力或力量体系相呼应。"
                ),
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
