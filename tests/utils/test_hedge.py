"""hedged_call: generic delay-hedged execution, extracted from llm/retry.py so non-LLM
callers (e.g. domain/search_provider.py's ChronosCloudSearchProvider) can reuse it."""
import asyncio

import pytest
from utils.hedge import hedged_call


@pytest.mark.asyncio
async def test_hedge_disabled_is_plain_passthrough():
    calls = 0

    async def attempt():
        nonlocal calls
        calls += 1
        return "result"

    result = await hedged_call(attempt, hedge_enabled=False, delay=0.01)

    assert result == "result"
    assert calls == 1


@pytest.mark.asyncio
async def test_hedge_not_triggered_when_primary_fast():
    calls = 0

    async def attempt():
        nonlocal calls
        calls += 1
        return "result"

    result = await hedged_call(attempt, hedge_enabled=True, delay=10.0)

    assert result == "result"
    assert calls == 1  # primary returned well within the delay -- no second attempt fired


@pytest.mark.asyncio
async def test_hedge_fires_and_wins_when_primary_slow():
    call_count = 0

    async def attempt():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            await asyncio.sleep(10.0)  # never finishes before the test's own timeout
            return "primary"
        return "hedge-won"

    result = await hedged_call(attempt, hedge_enabled=True, delay=0.05)

    assert result == "hedge-won"
    assert call_count == 2


@pytest.mark.asyncio
async def test_hedge_raises_last_error_when_both_fail():
    async def attempt():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await hedged_call(attempt, hedge_enabled=True, delay=0.05)
