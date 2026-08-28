"""Pick the concrete ImagePortraitProvider for a custom_models `image_gen` entry, keyed off
its `service` field (ImageService). Plain if/elif -- two providers, no registry (YAGNI)."""
from __future__ import annotations

from media.portrait.provider import DEFAULT_IMAGE_SERVICE, ImagePortraitProvider, ImageService


def build_image_provider(entry: dict) -> ImagePortraitProvider:
    service = ImageService(entry.get("service") or DEFAULT_IMAGE_SERVICE)
    api_key = entry.get("api_key") or ""
    model = entry.get("model") or ""

    if service is ImageService.NOVELAI:
        from media.portrait.novelai_provider import NovelAIImageProvider

        return NovelAIImageProvider(api_key=api_key, model=model)

    from media.portrait.novita_provider import NovitaImageProvider

    return NovitaImageProvider(api_key=api_key, model=model)
