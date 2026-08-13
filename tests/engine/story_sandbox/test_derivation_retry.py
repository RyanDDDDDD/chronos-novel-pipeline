import pytest
from engine.story_sandbox.derivation_retry import (
    DerivationValidationError,
    SandboxErrorCode,
    call_llm_with_retry,
)


@pytest.mark.asyncio
async def test_call_llm_with_retry_returns_first_success_without_retrying():
    calls = []

    async def call_llm(_system, _user):
        calls.append(1)
        return "ok"

    result = await call_llm_with_retry(
        "sys", "user", call_llm,
        parse=lambda raw: raw if raw == "ok" else None,
        code=SandboxErrorCode.STATE_DERIVE_FAILED,
    )
    assert result == "ok"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_call_llm_with_retry_succeeds_on_second_attempt():
    responses = iter(["坏的", "好的"])

    async def call_llm(_system, _user):
        return next(responses)

    result = await call_llm_with_retry(
        "sys", "user", call_llm,
        parse=lambda raw: raw if raw == "好的" else None,
        code=SandboxErrorCode.SCENE_DERIVE_FAILED,
    )
    assert result == "好的"


@pytest.mark.asyncio
async def test_call_llm_with_retry_raises_after_exhausting_attempts():
    calls = []

    async def call_llm(_system, _user):
        calls.append(1)
        return "一直不合法"

    with pytest.raises(DerivationValidationError) as exc_info:
        await call_llm_with_retry(
            "sys", "user", call_llm,
            parse=lambda _raw: None,
            code=SandboxErrorCode.INIT_STATE_FAILED,
        )
    assert len(calls) == 3  # _MAX_ATTEMPTS
    assert exc_info.value.code == SandboxErrorCode.INIT_STATE_FAILED
    assert exc_info.value.last_raw == "一直不合法"
