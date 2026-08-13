import asyncio

import pytest
from loguru import logger


@pytest.mark.asyncio
async def test_sandbox_step_timer_logs_started_and_completed():
    from utils.timer import sandbox_step_timer

    captured: list[str] = []
    sink_id = logger.add(lambda m: captured.append(str(m)), level="INFO")
    try:
        async with sandbox_step_timer("unit_test_step"):
            await asyncio.sleep(0.01)
    finally:
        logger.remove(sink_id)

    started = [m for m in captured if "unit_test_step" in m and "STARTED" in m]
    completed = [m for m in captured if "unit_test_step" in m and "COMPLETED" in m]
    assert started, "expected a STARTED log line"
    assert completed, "expected a COMPLETED log line"
    assert "elapsed_ms" in completed[0] or "elapsed=" in completed[0]


@pytest.mark.asyncio
async def test_sandbox_step_timer_logs_completed_even_on_exception():
    from utils.timer import sandbox_step_timer

    captured: list[str] = []
    sink_id = logger.add(lambda m: captured.append(str(m)), level="INFO")
    try:
        with pytest.raises(ValueError):
            async with sandbox_step_timer("failing_step"):
                raise ValueError("boom")
    finally:
        logger.remove(sink_id)

    assert any("failing_step" in m and "COMPLETED" in m for m in captured)


@pytest.mark.asyncio
async def test_sandbox_step_timer_includes_extra_meta():
    from utils.timer import sandbox_step_timer

    async with sandbox_step_timer("meta_step", extra_meta={"chapter": 3}) as _:
        pass
