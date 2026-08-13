"""Portrait image provider interface: pluggable so a different cloud API can later join
NovitaImageProvider without changing callers."""
from __future__ import annotations

from abc import ABC, abstractmethod


class ImagePortraitProvider(ABC):
    """Generates a single portrait image from a text prompt."""

    @abstractmethod
    async def generate(self, prompt: str) -> bytes:
        """Return PNG image bytes for the given prompt. Raises on network/HTTP failure --
        callers (the SCHEDULER job, see Task 9) are responsible for catching and converting
        that into a failed-generation broadcast; this layer does not retry."""
