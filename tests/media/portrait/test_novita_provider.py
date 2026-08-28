from __future__ import annotations

import httpx
import pytest


def _submit_response(url, task_id="task-1"):
    return httpx.Response(200, json={"task_id": task_id}, request=httpx.Request("POST", url))


def _task_result_response(url, status, *, image_url=None, reason=""):
    body = {"task": {"task_id": "task-1", "status": status, "reason": reason}}
    if image_url is not None:
        body["images"] = [{"image_url": image_url}]
    return httpx.Response(200, json=body, request=httpx.Request("GET", url))


@pytest.mark.asyncio
async def test_generate_returns_image_bytes(monkeypatch):
    from media.portrait.novita_provider import NovitaImageProvider

    captured = {}

    async def fake_post(self, url, *, json, headers, timeout):
        captured["submit_url"] = url
        captured["submit_json"] = json
        captured["submit_headers"] = headers
        return _submit_response(url)

    async def fake_get(self, url, *, params=None, headers=None, timeout):
        if params is not None:
            captured["poll_params"] = params
            captured["poll_headers"] = headers
            return _task_result_response(
                url, "TASK_STATUS_SUCCEED", image_url="https://cdn.example.com/out.png"
            )
        captured["image_url"] = url
        return httpx.Response(200, content=b"PNGDATA", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = NovitaImageProvider(api_key="test-key", model="test-model")
    result = await provider.generate("1girl, silver hair, red eyes")

    assert result == b"PNGDATA"
    assert captured["submit_json"]["request"]["prompt"] == "1girl, silver hair, red eyes"
    assert captured["submit_json"]["request"]["model_name"] == "test-model"
    assert captured["submit_json"]["request"]["width"] == 832
    assert captured["submit_json"]["request"]["height"] == 1216
    assert captured["submit_headers"]["Authorization"] == "Bearer test-key"
    assert captured["poll_params"]["task_id"] == "task-1"
    assert captured["poll_headers"]["Authorization"] == "Bearer test-key"
    assert captured["image_url"] == "https://cdn.example.com/out.png"


@pytest.mark.asyncio
async def test_generate_propagates_http_errors(monkeypatch):
    from media.portrait.novita_provider import NovitaImageProvider

    async def fake_post(self, url, *, json, headers, timeout):
        raise httpx.ConnectError("network down", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = NovitaImageProvider(api_key="test-key", model="test-model")
    with pytest.raises(httpx.ConnectError):
        await provider.generate("prompt")


@pytest.mark.asyncio
async def test_generate_uses_constructor_args_not_global_config(monkeypatch):
    from media.portrait.novita_provider import NovitaImageProvider

    captured = {}

    async def fake_post(self, url, *, json, headers, timeout):
        captured["json"] = json
        captured["headers"] = headers
        return _submit_response(url)

    async def fake_get(self, url, *, params=None, headers=None, timeout):
        if params is not None:
            return _task_result_response(
                url, "TASK_STATUS_SUCCEED", image_url="https://cdn.example.com/out.png"
            )
        return httpx.Response(200, content=b"PNGDATA", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = NovitaImageProvider(api_key="ctor-key", model="ctor-model")
    result = await provider.generate("prompt")

    assert result == b"PNGDATA"
    assert captured["json"]["request"]["model_name"] == "ctor-model"
    assert captured["headers"]["Authorization"] == "Bearer ctor-key"


@pytest.mark.asyncio
async def test_generate_polls_through_processing_status(monkeypatch):
    from media.portrait import novita_provider
    from media.portrait.novita_provider import NovitaImageProvider

    poll_statuses = iter(["TASK_STATUS_QUEUED", "TASK_STATUS_PROCESSING", "TASK_STATUS_SUCCEED"])
    sleep_calls = []

    async def fake_post(self, url, *, json, headers, timeout):
        return _submit_response(url)

    async def fake_get(self, url, *, params=None, headers=None, timeout):
        if params is not None:
            status = next(poll_statuses)
            image_url = "https://cdn.example.com/out.png" if status == "TASK_STATUS_SUCCEED" else None
            return _task_result_response(url, status, image_url=image_url)
        return httpx.Response(200, content=b"PNGDATA", request=httpx.Request("GET", url))

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(novita_provider.asyncio, "sleep", fake_sleep)

    provider = NovitaImageProvider(api_key="test-key", model="test-model")
    result = await provider.generate("prompt")

    assert result == b"PNGDATA"
    assert len(sleep_calls) == 2


@pytest.mark.asyncio
async def test_generate_sends_negative_prompt(monkeypatch):
    from media.portrait.novita_provider import NovitaImageProvider

    captured = {}

    async def fake_post(self, url, *, json, headers, timeout):
        captured["submit_json"] = json
        return _submit_response(url)

    async def fake_get(self, url, *, params=None, headers=None, timeout):
        if params is not None:
            return _task_result_response(
                url, "TASK_STATUS_SUCCEED", image_url="https://cdn.example.com/out.png"
            )
        return httpx.Response(200, content=b"PNGDATA", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = NovitaImageProvider(api_key="test-key", model="test-model")
    result = await provider.generate("1girl", negative_prompt="worst quality, blurry")

    assert result == b"PNGDATA"
    assert captured["submit_json"]["request"]["negative_prompt"] == "worst quality, blurry"


@pytest.mark.asyncio
async def test_generate_sends_a_random_seed_each_call(monkeypatch):
    """No seed field == relying on an unverified Novita default for whether identical
    prompts produce identical images (the previous ComfyUI provider always randomized
    seed explicitly -- this got dropped in the Novita migration)."""
    from media.portrait.novita_provider import NovitaImageProvider

    captured_seeds = []

    async def fake_post(self, url, *, json, headers, timeout):
        captured_seeds.append(json["request"]["seed"])
        return _submit_response(url)

    async def fake_get(self, url, *, params=None, headers=None, timeout):
        if params is not None:
            return _task_result_response(
                url, "TASK_STATUS_SUCCEED", image_url="https://cdn.example.com/out.png"
            )
        return httpx.Response(200, content=b"PNGDATA", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = NovitaImageProvider(api_key="test-key", model="test-model")
    await provider.generate("1girl")
    await provider.generate("1girl")

    assert len(captured_seeds) == 2
    for seed in captured_seeds:
        assert isinstance(seed, int)
        assert 0 <= seed < 2**32
    assert captured_seeds[0] != captured_seeds[1]


@pytest.mark.asyncio
async def test_generate_clamps_oversized_prompt_and_negative_prompt(monkeypatch):
    """Novita rejects Txt2ImgRequest.Prompt/NegativePrompt above 1024 runes with a 400
    VALIDATOR error (reproduced live 2026-08-11 against a character whose LLM-extracted
    visual tags alone ran to 1313 chars) -- the client must clamp before submitting."""
    from media.portrait.novita_provider import NovitaImageProvider

    captured = {}

    async def fake_post(self, url, *, json, headers, timeout):
        captured["submit_json"] = json
        return _submit_response(url)

    async def fake_get(self, url, *, params=None, headers=None, timeout):
        if params is not None:
            return _task_result_response(
                url, "TASK_STATUS_SUCCEED", image_url="https://cdn.example.com/out.png"
            )
        return httpx.Response(200, content=b"PNGDATA", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    long_prompt = ", ".join(f"tag{i}" for i in range(400))
    long_negative = ", ".join(f"neg{i}" for i in range(400))
    assert len(long_prompt) > 1024 and len(long_negative) > 1024

    provider = NovitaImageProvider(api_key="test-key", model="test-model")
    result = await provider.generate(long_prompt, negative_prompt=long_negative)

    assert result == b"PNGDATA"
    sent_prompt = captured["submit_json"]["request"]["prompt"]
    sent_negative = captured["submit_json"]["request"]["negative_prompt"]
    assert len(sent_prompt) <= 1024
    assert len(sent_negative) <= 1024
    # Clamped at a tag boundary, not mid-word.
    assert long_prompt.startswith(sent_prompt)
    assert not sent_prompt.endswith(",")


@pytest.mark.asyncio
async def test_generate_raises_on_failed_task(monkeypatch):
    from media.portrait.novita_provider import NovitaImageProvider

    async def fake_post(self, url, *, json, headers, timeout):
        return _submit_response(url)

    async def fake_get(self, url, *, params=None, headers=None, timeout):
        return _task_result_response(url, "TASK_STATUS_FAILED", reason="nsfw content blocked")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = NovitaImageProvider(api_key="test-key", model="test-model")
    with pytest.raises(RuntimeError, match="nsfw content blocked"):
        await provider.generate("prompt")
