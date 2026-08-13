"""Built-in art-style preset catalog for character portrait generation. Plain Python data
(not a StrEnum, not a JSON config) -- mirrors engine/execution/prose_style.py's preset
model in spirit (id + content bundle), but presets here carry prompt fragments + a static
preview asset path instead of markdown body text."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArtStylePreset:
    id: str
    label: str
    positive_fragment: str
    negative_fragment: str
    preview_path: str  # served from src/frontend/public/art-style-presets/<id>.jpg


DEFAULT_ART_STYLE_PRESET_ID = "anime"

ART_STYLE_PRESETS: list[ArtStylePreset] = [
    ArtStylePreset(
        id="anime", label="日系动漫",
        positive_fragment="masterpiece, best quality, highly detailed, anime style, sharp focus",
        negative_fragment="worst quality, low quality, blurry, extra fingers, deformed, bad anatomy, watermark, text",
        preview_path="/art-style-presets/anime.jpg",
    ),
    ArtStylePreset(
        id="cyberpunk", label="赛博朋克",
        positive_fragment=(
            "cyberpunk style, neon lighting, futuristic cityscape, rain-slicked streets, "
            "holographic details, high contrast, masterpiece, best quality, highly detailed"
        ),
        negative_fragment="worst quality, low quality, blurry, pastel colors, medieval, watermark, text",
        preview_path="/art-style-presets/cyberpunk.jpg",
    ),
    ArtStylePreset(
        id="photoreal", label="写实/照片级",
        positive_fragment="photorealistic, realistic skin texture, natural lighting, DSLR photo, ultra detailed, 8k, sharp focus",
        negative_fragment="worst quality, low quality, blurry, anime, cartoon, illustration, painting, watermark, text, deformed",
        preview_path="/art-style-presets/photoreal.jpg",
    ),
    ArtStylePreset(
        id="western-comic", label="美漫风",
        positive_fragment=(
            "western comic book style, bold ink outlines, dynamic shading, vibrant flat "
            "colors, comic panel art, masterpiece, best quality"
        ),
        negative_fragment="worst quality, low quality, blurry, photorealistic, anime style, watermark, text",
        preview_path="/art-style-presets/western-comic.jpg",
    ),
    ArtStylePreset(
        id="korean-webtoon", label="韩漫风",
        positive_fragment=(
            "korean webtoon style, clean linework, soft cel shading, glossy highlights, "
            "vibrant modern palette, masterpiece, best quality"
        ),
        negative_fragment="worst quality, low quality, blurry, rough sketch, western comic, watermark, text",
        preview_path="/art-style-presets/korean-webtoon.jpg",
    ),
]

_BY_ID = {p.id: p for p in ART_STYLE_PRESETS}


def get_art_style_preset(preset_id: str | None) -> ArtStylePreset:
    """Unknown/missing id falls back to the default preset -- never raises, since this
    feeds prompt assembly and a bad id should degrade gracefully, not break generation."""
    return _BY_ID.get(preset_id or "", _BY_ID[DEFAULT_ART_STYLE_PRESET_ID])
