"""Shared clothing_dna schema helpers: validation keys + LLM-facing render lines."""
from __future__ import annotations

from typing import Any

CLOTHING_DNA_REQUIRED_KEYS = (
    "color_palette",
    "materials_preference",
    "signature_outfit",
    "accessories",
)


def default_signature_outfit(dna: dict[str, Any]) -> str:
    """Synthesize a placeholder signature outfit from legacy palette/material tags."""
    palette = "、".join(str(x).strip() for x in (dna.get("color_palette") or []) if str(x).strip())
    materials = "、".join(str(x).strip() for x in (dna.get("materials_preference") or []) if str(x).strip())
    parts: list[str] = []
    if palette:
        parts.append(f"{palette}色系")
    if materials:
        parts.append(f"{materials}材质")
    base = "，".join(parts) if parts else "基础"
    return f"{base}的日常常服（由旧数据迁移，待细化具体款式）"


def render_clothing_dna_lines(dna: dict[str, Any]) -> list[str]:
    """Turn a clothing_dna dict into prompt/summary lines for LLM grounding."""
    if not dna:
        return []
    palette = "／".join(dna.get("color_palette") or []) or "（无）"
    materials = "／".join(dna.get("materials_preference") or []) or "（无）"
    signature = str(dna.get("signature_outfit") or "").strip() or "（无）"
    accessories_raw = dna.get("accessories")
    if isinstance(accessories_raw, list):
        accessories = "／".join(str(x).strip() for x in accessories_raw if str(x).strip()) or "（无）"
    else:
        accessories = "（无）"
    return [
        "着装基底(clothing_dna)："
        f"招牌常服={signature}；配饰={accessories}；色系={palette}；材质偏好={materials}"
        "——写 clothing 时以招牌常服+配饰为款式基准，结合色系/材质与 stage 场景具体化",
    ]
