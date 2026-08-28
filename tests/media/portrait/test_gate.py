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


def _make_sleep_recorder(slept: list[float]):
    async def record_sleep(s: float) -> None:
        slept.append(s)

    return record_sleep


@pytest.mark.asyncio
async def test_run_passes_through_result_and_calls_once() -> None:
    gate = ImageGenGate(min_interval_s=0.0)
    calls = []

    async def call():
        calls.append(1)
        return b"IMG"

    assert await gate.run(call) == b"IMG"
    assert calls == [1]


@pytest.mark.asyncio
async def test_run_serializes_concurrent_calls() -> None:
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
async def test_run_honours_min_interval_between_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    interval_sleeps: list[float] = []

    class _FakeLoop:
        def time(self) -> float:
            return clock[0]

    async def fake_sleep(delay: float) -> None:
        interval_sleeps.append(delay)
        clock[0] += delay

    monkeypatch.setattr(
        "media.portrait.gate.asyncio.get_running_loop", lambda: _FakeLoop(),
    )
    monkeypatch.setattr("media.portrait.gate.asyncio.sleep", fake_sleep)

    gate = ImageGenGate(min_interval_s=0.05)
    call_starts: list[float] = []
    completions: list[float] = []

    async def call():
        call_starts.append(clock[0])
        clock[0] += 0.10  # body work: completion is later than start
        completions.append(clock[0])
        return b"X"

    await gate.run(call)
    assert len(call_starts) == 1
    assert len(completions) == 1
    assert completions[0] - call_starts[0] == pytest.approx(0.10)
    assert interval_sleeps == []  # no prior completion to honour

    await gate.run(call)
    assert interval_sleeps == [0.05]
    assert call_starts[1] - completions[0] == pytest.approx(0.05)
    assert completions[1] - call_starts[1] == pytest.approx(0.10)


@pytest.mark.asyncio
async def test_run_backs_off_and_retries_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(
        "media.portrait.gate.asyncio.sleep", _make_sleep_recorder(slept),
    )
    gate = ImageGenGate(min_interval_s=0.0, rate_limit_backoff_s=(8.0, 20.0, 45.0))
    n = 0

    async def call():
        nonlocal n
        n += 1
        if n < 3:
            raise _http_error(429)
        return b"OK"

    assert await gate.run(call) == b"OK"
    assert n == 3
    assert slept == [8.0, 20.0]


@pytest.mark.asyncio
async def test_run_raises_after_429_retries_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []
    monkeypatch.setattr(
        "media.portrait.gate.asyncio.sleep", _make_sleep_recorder(slept),
    )
    gate = ImageGenGate(min_interval_s=0.0, rate_limit_backoff_s=(0.0, 0.0, 0.0))
    n = 0

    async def call():
        nonlocal n
        n += 1
        raise _http_error(429)

    with pytest.raises(httpx.HTTPStatusError) as ei:
        await gate.run(call)
    assert ei.value.response.status_code == 429
    assert n == 4  # initial attempt + one sleep per backoff entry
    assert slept == [0.0, 0.0, 0.0]


@pytest.mark.asyncio
async def test_run_retries_transient_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []
    monkeypatch.setattr(
        "media.portrait.gate.asyncio.sleep", _make_sleep_recorder(slept),
    )
    gate = ImageGenGate(min_interval_s=0.0, max_transient_retries=2, transient_backoff_s=2.0)
    n = 0

    async def call():
        nonlocal n
        n += 1
        if n < 3:
            raise httpx.ConnectError("boom")
        return b"OK"

    assert await gate.run(call) == b"OK"
    assert n == 3
    assert slept == [2.0, 2.0]


@pytest.mark.asyncio
async def test_run_raises_after_transient_transport_retries_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []
    monkeypatch.setattr(
        "media.portrait.gate.asyncio.sleep", _make_sleep_recorder(slept),
    )
    gate = ImageGenGate(min_interval_s=0.0, max_transient_retries=2, transient_backoff_s=2.0)
    n = 0

    async def call():
        nonlocal n
        n += 1
        raise httpx.ConnectError("boom")

    with pytest.raises(httpx.ConnectError):
        await gate.run(call)
    assert n == 3  # initial attempt + max_transient_retries retries
    assert slept == [2.0, 2.0]


@pytest.mark.asyncio
async def test_run_treats_5xx_as_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(
        "media.portrait.gate.asyncio.sleep", _make_sleep_recorder(slept),
    )
    gate = ImageGenGate(min_interval_s=0.0, max_transient_retries=2, transient_backoff_s=2.0)
    n = 0

    async def call():
        nonlocal n
        n += 1
        if n < 2:
            raise _http_error(503)
        return b"OK"

    assert await gate.run(call) == b"OK"
    assert n == 2
    assert slept == [2.0]


@pytest.mark.asyncio
async def test_run_raises_after_transient_5xx_retries_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []
    monkeypatch.setattr(
        "media.portrait.gate.asyncio.sleep", _make_sleep_recorder(slept),
    )
    gate = ImageGenGate(min_interval_s=0.0, max_transient_retries=2, transient_backoff_s=2.0)
    n = 0

    async def call():
        nonlocal n
        n += 1
        raise _http_error(503)

    with pytest.raises(httpx.HTTPStatusError) as ei:
        await gate.run(call)
    assert ei.value.response.status_code == 503
    assert n == 3
    assert slept == [2.0, 2.0]


@pytest.mark.asyncio
async def test_run_does_not_retry_permanent_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []
    monkeypatch.setattr(
        "media.portrait.gate.asyncio.sleep", _make_sleep_recorder(slept),
    )
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
async def test_run_lets_cancelled_error_propagate() -> None:
    gate = ImageGenGate(min_interval_s=0.0)

    async def call():
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await gate.run(call)
