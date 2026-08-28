from __future__ import annotations

import pytest

from media.portrait.novelai_provider import NovelAIImageProvider
from media.portrait.novita_provider import NovitaImageProvider
from media.portrait.provider_factory import build_image_provider


def test_defaults_to_novita_when_service_absent():
    p = build_image_provider({"api_key": "k", "model": "pony-v6"})
    assert isinstance(p, NovitaImageProvider)


def test_novita_when_service_novita():
    p = build_image_provider({"service": "novita", "api_key": "k", "model": "m"})
    assert isinstance(p, NovitaImageProvider)


def test_novelai_when_service_novelai():
    p = build_image_provider({"service": "novelai", "api_key": "tok", "model": "nai-diffusion-4-5-full"})
    assert isinstance(p, NovelAIImageProvider)


def test_unknown_service_raises():
    with pytest.raises(ValueError):
        build_image_provider({"service": "comfyui", "api_key": "k", "model": "m"})
