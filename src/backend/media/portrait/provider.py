"""Portrait image provider interface + service discriminator. Pluggable so different
cloud APIs (NovitaImageProvider, NovelAIImageProvider) share one call site via
media.portrait.provider_factory.build_image_provider()."""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum


class ImageService(StrEnum):
    """Which cloud image API a custom_models `image_gen` entry talks to. Stored as the
    entry's `service` string; DEFAULT_IMAGE_SERVICE covers entries that predate the field."""

    NOVITA = "novita"
    NOVELAI = "novelai"


DEFAULT_IMAGE_SERVICE: ImageService = ImageService.NOVITA


class ImagePortraitProvider(ABC):
    """Generates a single portrait image from a text prompt."""

    @abstractmethod
    async def generate(self, prompt: str, *, negative_prompt: str = "") -> bytes:
        """Return image bytes (PNG or JPEG) for the given prompt. Raises on network/HTTP
        failure and on provider-side rejection (quota/subscription/content) -- callers (the
        SCHEDULER portrait job) catch and convert that into a failed-generation broadcast;
        this layer does not retry."""
