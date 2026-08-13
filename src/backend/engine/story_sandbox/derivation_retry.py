"""Shared validation+retry wrapper for story-sandbox's four state/scene derivation LLM calls.
Unlike llm_json.py's tolerant parsing (malformed JSON silently degrades to {}), a call that
still can't be parsed as a JSON dict after retrying must not silently become "no change this
turn" -- it retries a few times, then raises and aborts the turn."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import TypeVar

from loguru import logger

T = TypeVar("T")
CallLLM = Callable[[str, str], Awaitable[str]]

# 3 attempts (2 retries) -- bumped from the original 1-retry (direction_suggest.py-style)
# convention after observing back-to-back empty completions from the cloud LLM provider
# (not malformed JSON -- a genuinely empty raw response) exhaust a single retry and abort
# an otherwise-fine turn. See docs/superpowers/specs/2026-08-03-sandbox-derive-retry-hardening-design.md.
_MAX_ATTEMPTS = 3


class SandboxErrorCode(StrEnum):
    """Wire-format error code attached to story_sandbox_error when a derivation call exhausts
    its retries -- lets the frontend eventually branch per-code without a protocol change."""

    INIT_STATE_FAILED = "INIT_STATE_FAILED"
    INIT_SCENE_FAILED = "INIT_SCENE_FAILED"
    STATE_DERIVE_FAILED = "STATE_DERIVE_FAILED"
    SCENE_DERIVE_FAILED = "SCENE_DERIVE_FAILED"
    IDENTIFY_CAST_FAILED = "IDENTIFY_CAST_FAILED"


class DerivationValidationError(Exception):
    """Raised when a derivation call is still unparseable after _MAX_ATTEMPTS tries --
    propagates out of the graph node, aborting the whole turn (caught in message_hub.py; nothing
    from this turn's superstep gets persisted)."""

    def __init__(self, code: SandboxErrorCode, last_raw: str) -> None:
        self.code = code
        self.last_raw = last_raw
        super().__init__(f"{code.value}：状态推演校验失败，已终止本轮创作")


async def call_llm_with_retry(
    system: str, user: str, call_llm: CallLLM, *,
    parse: Callable[[str], T | None], code: SandboxErrorCode,
) -> T:
    """Calls call_llm up to _MAX_ATTEMPTS times; `parse` extracts+validates the JSON response,
    returning None to trigger a retry. Returns the first non-None parse; logs and raises
    DerivationValidationError with the last raw response once attempts are exhausted."""
    raw = ""
    for attempt in range(_MAX_ATTEMPTS):
        raw = await call_llm(system, user)
        result = parse(raw)
        if result is not None:
            return result
        logger.warning(
            "[story_sandbox] {} attempt {}/{} unparseable, raw={!r}",
            code.value, attempt + 1, _MAX_ATTEMPTS, raw[:300],
        )
    logger.error("[story_sandbox] {} exhausted {} attempts, aborting turn", code.value, _MAX_ATTEMPTS)
    raise DerivationValidationError(code, raw)
