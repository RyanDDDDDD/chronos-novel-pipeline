"""Per-node thinking-effort overrides — delegates to domain.model_profile subclasses.

Kept as a thin compatibility layer; new code should import from domain.model_profile."""
from __future__ import annotations

from domain.model_profile import (
    ThinkingEffort,
    resolve_thinking_bind,
)


def resolve_thinking_kwargs(llm: object, effort: ThinkingEffort) -> dict[str, object]:
    """Enable thinking at the given effort (legacy enable-only entry point)."""
    return resolve_thinking_bind(llm, enable_thinking=True, effort=effort)
