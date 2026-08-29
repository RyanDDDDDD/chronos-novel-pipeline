from __future__ import annotations

import io
import zipfile

import httpx
import pytest


def _zip_bytes(png: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("image_0.png", png)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_generate_posts_expected_payload_and_returns_png(monkeypatch):
    from media.portrait.novelai_provider import NovelAIImageProvider

    captured = {}

    async def fake_post(self, url, *, json, headers, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return httpx.Response(200, content=_zip_bytes(b"PNGDATA"),
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = NovelAIImageProvider(api_key="tok", model="nai-diffusion-4-5-full")
    result = await provider.generate("1girl, silver hair", negative_prompt="bad hands")

    assert result == b"PNGDATA"
    assert captured["url"] == "https://image.novelai.net/ai/generate-image"
    assert captured["headers"]["Authorization"] == "Bearer tok"
    assert captured["json"]["input"] == "1girl, silver hair"
    assert captured["json"]["model"] == "nai-diffusion-4-5-full"
    p = captured["json"]["parameters"]
    assert p["width"] == 832
    assert p["height"] == 1216
    assert p["negative_prompt"] == "bad hands"
    # v4_prompt / v4_negative_prompt structured objects are REQUIRED by V4.5/V5.
    assert p["v4_prompt"]["caption"]["base_caption"] == "1girl, silver hair"
    assert p["v4_negative_prompt"]["caption"]["base_caption"] == "bad hands"


@pytest.mark.asyncio
async def test_generate_raises_on_402(monkeypatch):
    from media.portrait.novelai_provider import NovelAIImageProvider

    async def fake_post(self, url, *, json, headers, timeout=None):
        return httpx.Response(402, json={"message": "no subscription"},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = NovelAIImageProvider(api_key="tok", model="m")
    with pytest.raises(RuntimeError, match="订阅|Anlas"):
        await provider.generate("1girl")


@pytest.mark.asyncio
async def test_generate_raises_on_empty_zip(monkeypatch):
    from media.portrait.novelai_provider import NovelAIImageProvider

    empty = io.BytesIO()
    with zipfile.ZipFile(empty, "w"):
        pass

    async def fake_post(self, url, *, json, headers, timeout=None):
        return httpx.Response(200, content=empty.getvalue(),
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = NovelAIImageProvider(api_key="tok", model="m")
    with pytest.raises(RuntimeError, match="ZIP"):
        await provider.generate("1girl")


def _png(w: int = 832, h: int = 1216) -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (w, h), (1, 2, 3)).save(b, format="PNG")
    return b.getvalue()


@pytest.mark.asyncio
async def test_char_captions_go_into_v4_prompt(monkeypatch):
    from media.portrait.novelai_provider import NovelAIImageProvider

    captured = {}

    async def fake_post(self, url, *, json=None, files=None, headers=None):
        captured["json"] = json
        captured["files"] = files
        return httpx.Response(200, content=_zip_bytes(b"X"),
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = NovelAIImageProvider(api_key="tok", model="nai-diffusion-4-5-full")
    await provider.generate(
        "tavern, 2girls",
        char_captions=[
            {"char_caption": "1girl, silver hair", "centers": [{"x": 0.5, "y": 0.5}]},
            {"char_caption": "1girl, red hair", "centers": [{"x": 0.5, "y": 0.5}]},
        ],
    )
    caps = captured["json"]["parameters"]["v4_prompt"]["caption"]["char_captions"]
    assert [c["char_caption"] for c in caps] == ["1girl, silver hair", "1girl, red hair"]
    neg = captured["json"]["parameters"]["v4_negative_prompt"]["caption"]["char_captions"]
    assert [c["char_caption"] for c in neg] == ["", ""]
    assert captured["files"] is None  # no references -> plain JSON


@pytest.mark.asyncio
async def test_precise_reference_sends_multipart(monkeypatch):
    import hashlib

    from media.portrait.novelai_provider import NovelAIImageProvider

    captured = {}

    async def fake_post(self, url, *, json=None, files=None, headers=None):
        captured["json"] = json
        captured["files"] = files
        return httpx.Response(200, content=_zip_bytes(b"X"),
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = NovelAIImageProvider(api_key="tok", model="nai-diffusion-4-5-full")
    await provider.generate(
        "tavern",
        char_captions=[{"char_caption": "1girl", "centers": [{"x": 0.5, "y": 0.5}]}],
        character_references=[_png()],
        reference_strength=0.7,
        reference_fidelity=1.0,
    )
    assert captured["json"] is None                       # multipart path
    files = captured["files"]
    assert "request" in files and "director_ref_0" in files
    import json as _json
    req = _json.loads(files["request"][1])
    params = req["parameters"]
    assert "director_reference_images" not in params      # stripped from JSON
    cached = params["director_reference_images_cached"]
    assert cached[0]["data"] == "director_ref_0"
    prepped_bytes = files["director_ref_0"][1]
    assert cached[0]["cache_secret_key"] == hashlib.sha256(prepped_bytes).hexdigest()
    assert params["director_reference_strength_values"] == [0.7]
    assert params["director_reference_secondary_strength_values"] == [0.0]
    assert params["director_reference_information_extracted"] == [1]
    assert params["director_reference_descriptions"][0]["caption"]["base_caption"] == "character"
    assert params["normalize_reference_strength_multiple"] is True


@pytest.mark.asyncio
async def test_precise_reference_rejected_on_non_v45_model():
    from media.portrait.novelai_provider import NovelAIImageProvider

    provider = NovelAIImageProvider(api_key="tok", model="nai-diffusion-5-full")
    with pytest.raises(RuntimeError, match="V4.5"):
        await provider.generate("x", character_references=[_png()])


@pytest.mark.asyncio
async def test_generate_randomizes_seed_each_call(monkeypatch):
    from media.portrait.novelai_provider import NovelAIImageProvider

    seeds = []

    async def fake_post(self, url, *, json, headers, timeout=None):
        seeds.append(json["parameters"]["seed"])
        return httpx.Response(200, content=_zip_bytes(b"X"),
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = NovelAIImageProvider(api_key="tok", model="m")
    await provider.generate("1girl")
    await provider.generate("1girl")

    assert len(seeds) == 2
    assert seeds[0] != seeds[1]
    assert all(isinstance(s, int) and 0 <= s < 2**32 for s in seeds)
