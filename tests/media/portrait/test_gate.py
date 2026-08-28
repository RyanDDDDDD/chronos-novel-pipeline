from __future__ import annotations

import asyncio

import httpx
import pytest

from media.portrait.gate import ImageGenGate


def _http_error(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://example.test/gen")
    return httpx.HTTPStatusError(
        f"HTTP {status}", request=req, response=httpx.Response(status, request=req),
    )


async def _noop_sleep(_s: float) -> None:
    return None


@pytest.mark.asyncio
async def test_run_passes_through_result_and_calls_once():
    gate = ImageGenGate(min_interval_s=0.0)
    calls = []

    async def call():
        calls.append(1)
        return b"IMG"

    assert await gate.run(call) == b"IMG"
    assert calls == [1]


@pytest.mark.asyncio
async def test_run_serializes_concurrent_calls():
    gate = ImageGenGate(min_interval_s=0.0)
    active = 0
    max_active = 0

    async def call():
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        active -= 1
        return b"X"

    await asyncio.gather(*(gate.run(call) for _ in range(4)))
    assert max_active == 1


@pytest.mark.asyncio
async def test_run_honours_min_interval_between_calls():
    gate = ImageGenGate(min_interval_s=0.05)
    starts: list[float] = []

    async def call():
        starts.append(asyncio.get_running_loop().time())
        return b"X"

    await gate.run(call)
    await gate.run(call)
    assert starts[1] - starts[0] >= 0.05


@pytest.mark.asyncio
async def test_run_backs_off_and_retries_on_429(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr("media.portrait.gate.asyncio.sleep", fake_sleep)
    gate = ImageGenGate(min_interval_s=0.0, rate_limit_backoff_s=(8.0, 20.0, 45.0))
    n = 0

    async def call():
        nonlocal n
        n += 1
        if n < 3:
            raise _http_error(429)
        return b"OK"

    assert await gate.run(call) == b"OK"
    assert slept == [8.0, 20.0]


@pytest.mark.asyncio
async def test_run_raises_after_429_retries_exhausted(monkeypatch):
    monkeypatch.setattr("media.portrait.gate.asyncio.sleep", _noop_sleep)
    gate = ImageGenGate(min_interval_s=0.0, rate_limit_backoff_s=(0.0, 0.0, 0.0))

    async def call():
        raise _http_error(429)

    with pytest.raises(httpx.HTTPStatusError) as ei:
        await gate.run(call)
    assert ei.value.response.status_code == 429


@pytest.mark.asyncio
async def test_run_retries_transient_transport_error(monkeypatch):
    monkeypatch.setattr("media.portrait.gate.asyncio.sleep", _noop_sleep)
    gate = ImageGenGate(min_interval_s=0.0, max_transient_retries=2)
    n = 0

    async def call():
        nonlocal n
        n += 1
        if n < 3:
            raise httpx.ConnectError("boom")
        return b"OK"

    assert await gate.run(call) == b"OK"
    assert n == 3


@pytest.mark.asyncio
async def test_run_treats_5xx_as_transient(monkeypatch):
    monkeypatch.setattr("media.portrait.gate.asyncio.sleep", _noop_sleep)
    gate = ImageGenGate(min_interval_s=0.0, max_transient_retries=2)
    n = 0

    async def call():
        nonlocal n
        n += 1
        if n < 2:
            raise _http_error(503)
        return b"OK"

    assert await gate.run(call) == b"OK"


@pytest.mark.asyncio
async def test_run_does_not_retry_permanent_errors(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("media.portrait.gate.asyncio.sleep", lambda s: slept.append(s))
    gate = ImageGenGate(min_interval_s=0.0)
    n = 0

    async def call():
        nonlocal n
        n += 1
        raise RuntimeError("NovelAI 拒绝生成：订阅未激活或 Anlas 点数不足（HTTP 402）")

    with pytest.raises(RuntimeError, match="402"):
        await gate.run(call)
    assert n == 1
    assert slept == []


@pytest.mark.asyncio
async def test_run_lets_cancelled_error_propagate():
    gate = ImageGenGate(min_interval_s=0.0)

    async def call():
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await gate.run(call)
