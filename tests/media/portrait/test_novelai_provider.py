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
