from __future__ import annotations

import pytest


def test_image_service_members():
    from media.portrait.provider import DEFAULT_IMAGE_SERVICE, ImageService

    assert ImageService.NOVITA == "novita"
    assert ImageService.NOVELAI == "novelai"
    assert ImageService("novita") is ImageService.NOVITA
    assert DEFAULT_IMAGE_SERVICE is ImageService.NOVITA


def test_image_service_rejects_unknown():
    from media.portrait.provider import ImageService

    with pytest.raises(ValueError):
        ImageService("comfyui")


def test_abc_generate_signature_has_negative_prompt():
    import inspect

    from media.portrait.provider import ImagePortraitProvider

    sig = inspect.signature(ImagePortraitProvider.generate)
    assert "negative_prompt" in sig.parameters
    assert sig.parameters["negative_prompt"].default == ""
