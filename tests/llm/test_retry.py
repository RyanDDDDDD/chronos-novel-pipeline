"""RetryingChatModel: transparent astream/ainvoke retry on transient network/rate-limit errors."""
import asyncio

import httpx
import llm.retry as retry_module
import openai
import pytest
from langchain_core.runnables.base import Runnable
from llm.retry import DEFAULT_RETRIES, RetryingChatModel


class _FakeRunnable(Runnable):
    """Real `Runnable` subclass (pydantic validates `RunnableBindingBase.bound` via
    isinstance) with controllable ainvoke/astream responses for retry tests."""

    def __init__(
        self,
        ainvoke_responses: list | None = None,
        astream_responses: list | None = None,
    ) -> None:
        self._ainvoke_responses = list(ainvoke_responses or [])
        self._astream_responses = list(astream_responses or [])
        self.ainvoke_calls = 0
        self.astream_calls = 0

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError("tests only exercise the async path")

    async def ainvoke(self, input, config=None, **kwargs):
        self.ainvoke_calls += 1
        resp = self._ainvoke_responses.pop(0)
        if isinstance(resp, BaseException):
            raise resp
        return resp

    async def astream(self, input, config=None, **kwargs):
        self.astream_calls += 1
        attempt = self._astream_responses.pop(0)
        if isinstance(attempt, BaseException):
            raise attempt
        for piece in attempt:
            if isinstance(piece, BaseException):
                raise piece
            yield piece


def _transport_error() -> httpx.ReadError:
    return httpx.ReadError("connection reset")


def _rate_limit_error_2() -> openai.RateLimitError:
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    response = httpx.Response(429, request=request)
    return openai.RateLimitError("rate limited", response=response, body=None)


async def test_retrying_chat_model_ainvoke_retries_transport_error_then_succeeds():
    fake = _FakeRunnable(ainvoke_responses=[_transport_error(), "ok"])
    model = RetryingChatModel(bound=fake)

    result = await model.ainvoke(["msg"])

    assert result == "ok"
    assert fake.ainvoke_calls == 2


async def test_retrying_chat_model_ainvoke_retries_rate_limit_then_succeeds():
    fake = _FakeRunnable(ainvoke_responses=[_rate_limit_error_2(), "ok"])
    model = RetryingChatModel(bound=fake)

    result = await model.ainvoke(["msg"])

    assert result == "ok"
    assert fake.ainvoke_calls == 2


async def test_retrying_chat_model_ainvoke_reraises_after_exhausting_transport_retries():
    fake = _FakeRunnable(ainvoke_responses=[_transport_error()] * (DEFAULT_RETRIES + 1))
    model = RetryingChatModel(bound=fake)

    with pytest.raises(httpx.ReadError):
        await model.ainvoke(["msg"])
    assert fake.ainvoke_calls == DEFAULT_RETRIES + 1


async def test_retrying_chat_model_astream_retries_when_zero_chunks_yielded():
    fake = _FakeRunnable(astream_responses=[_transport_error(), ["a", "b"]])
    model = RetryingChatModel(bound=fake)

    result = [piece async for piece in model.astream(["msg"])]

    assert result == ["a", "b"]
    assert fake.astream_calls == 2


async def test_retrying_chat_model_astream_does_not_retry_after_partial_yield():
    async def _one_then_fail():
        yield "a"
        raise httpx.ReadError("connection reset")

    class _PartialYieldRunnable(Runnable):
        def invoke(self, input, config=None, **kwargs):
            raise NotImplementedError

        async def astream(self, input, config=None, **kwargs):
            async for piece in _one_then_fail():
                yield piece

    model = RetryingChatModel(bound=_PartialYieldRunnable())

    collected = []
    with pytest.raises(httpx.ReadError):
        async for piece in model.astream(["msg"]):
            collected.append(piece)
    assert collected == ["a"]


async def test_retrying_chat_model_astream_rate_limit_and_transport_counters_independent():
    # Rate-limit retry budget (RATE_LIMIT_RETRIES) is separate from the transport retry
    # budget (DEFAULT_RETRIES) -- exhausting one type doesn't consume the other's budget.
    fake = _FakeRunnable(astream_responses=[
        _rate_limit_error_2(), _transport_error(), ["ok"],
    ])
    model = RetryingChatModel(bound=fake)

    result = [piece async for piece in model.astream(["msg"])]

    assert result == ["ok"]
    assert fake.astream_calls == 3


async def test_retrying_chat_model_getattr_forwards_to_bound():
    class _NamedRunnable(Runnable):
        model = "deepseek-v4-flash"

        def invoke(self, input, config=None, **kwargs):
            raise NotImplementedError

    model = RetryingChatModel(bound=_NamedRunnable())

    assert model.model == "deepseek-v4-flash"


async def test_retrying_chat_model_survives_bind_composition():
    fake = _FakeRunnable(ainvoke_responses=[_transport_error(), "ok"])
    model = RetryingChatModel(bound=fake)

    bound = model.bind(temperature=0.5)
    result = await bound.ainvoke(["msg"])

    assert result == "ok"
    assert fake.ainvoke_calls == 2


def test_retrying_chat_model_hedge_enabled_defaults_to_false():
    fake = _FakeRunnable(ainvoke_responses=["ok"])
    model = RetryingChatModel(bound=fake)

    assert model.hedge_enabled is False


def test_retrying_chat_model_hedge_enabled_can_be_set_true():
    fake = _FakeRunnable(ainvoke_responses=["ok"])
    model = RetryingChatModel(bound=fake, hedge_enabled=True)

    assert model.hedge_enabled is True


class _FirstCallHangsRunnable(Runnable):
    """First ainvoke() call hangs until cancelled; second call returns immediately --
    simulates "primary too slow, hedge wins"."""

    def __init__(self) -> None:
        self.calls = 0
        self.first_call_cancelled = False

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError

    async def ainvoke(self, input, config=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            try:
                await asyncio.Event().wait()
            finally:
                self.first_call_cancelled = True
            return "unreachable"  # pragma: no cover
        return "hedge-won"


async def test_ainvoke_hedge_not_triggered_when_primary_fast(monkeypatch):
    monkeypatch.setattr(retry_module, "HEDGE_DELAY_S", 5.0)
    fake = _FakeRunnable(ainvoke_responses=["ok"])
    model = RetryingChatModel(bound=fake, hedge_enabled=True)

    result = await model.ainvoke(["msg"])

    assert result == "ok"
    assert fake.ainvoke_calls == 1


async def test_ainvoke_hedge_fires_and_wins_when_primary_slow(monkeypatch):
    monkeypatch.setattr(retry_module, "HEDGE_DELAY_S", 0.05)
    fake = _FirstCallHangsRunnable()
    model = RetryingChatModel(bound=fake, hedge_enabled=True)

    result = await model.ainvoke(["msg"])

    assert result == "hedge-won"
    assert fake.calls == 2
    assert fake.first_call_cancelled is True


async def test_ainvoke_hedge_raises_last_error_when_both_exhaust_retries(monkeypatch):
    monkeypatch.setattr(retry_module, "HEDGE_DELAY_S", 0.05)
    fake = _FakeRunnable(ainvoke_responses=[_transport_error()] * (2 * (DEFAULT_RETRIES + 1)))
    model = RetryingChatModel(bound=fake, hedge_enabled=True)

    with pytest.raises(httpx.ReadError):
        await model.ainvoke(["msg"])
    assert fake.ainvoke_calls == 2 * (DEFAULT_RETRIES + 1)


class _HangingThenFastAstream(Runnable):
    """First astream() call hangs before yielding anything until closed/cancelled; second
    call yields immediately -- simulates "primary too slow, hedge wins" for streaming."""

    def __init__(self) -> None:
        self.calls = 0
        self.primary_closed = False

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError

    async def astream(self, input, config=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            try:
                await asyncio.Event().wait()
            finally:
                self.primary_closed = True
            yield "unreachable"  # pragma: no cover
        else:
            yield "hedge-a"
            yield "hedge-b"


async def test_astream_hedge_not_triggered_when_primary_fast(monkeypatch):
    monkeypatch.setattr(retry_module, "HEDGE_DELAY_S", 5.0)
    fake = _FakeRunnable(astream_responses=[["a", "b"]])
    model = RetryingChatModel(bound=fake, hedge_enabled=True)

    result = [piece async for piece in model.astream(["msg"])]

    assert result == ["a", "b"]
    assert fake.astream_calls == 1


async def test_astream_hedge_fires_and_closes_loser_generator(monkeypatch):
    monkeypatch.setattr(retry_module, "HEDGE_DELAY_S", 0.05)
    fake = _HangingThenFastAstream()
    model = RetryingChatModel(bound=fake, hedge_enabled=True)

    result = [piece async for piece in model.astream(["msg"])]

    assert result == ["hedge-a", "hedge-b"]
    assert fake.calls == 2
    assert fake.primary_closed is True


async def test_astream_hedge_raises_last_error_when_both_exhaust_retries(monkeypatch):
    monkeypatch.setattr(retry_module, "HEDGE_DELAY_S", 0.05)
    fake = _FakeRunnable(astream_responses=[_transport_error()] * (2 * (DEFAULT_RETRIES + 1)))
    model = RetryingChatModel(bound=fake, hedge_enabled=True)

    with pytest.raises(httpx.ReadError):
        async for _ in model.astream(["msg"]):
            pass
    assert fake.astream_calls == 2 * (DEFAULT_RETRIES + 1)
