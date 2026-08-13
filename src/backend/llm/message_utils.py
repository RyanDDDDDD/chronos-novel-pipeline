"""Small helpers for LangChain message cloning without dropping provider metadata."""
from __future__ import annotations

from langchain_core.messages import AIMessage


def clone_ai_message(ai: AIMessage, **overrides) -> AIMessage:
    """Clone an AIMessage, preserving additional_kwargs/response_metadata by default.

    LangChain reconstructors often pass only content/id/tool_calls, which drops
    DeepSeek thinking-mode ``reasoning_content`` and triggers 400 on the next turn."""
    data = ai.model_dump()
    data.update(overrides)
    if overrides.get("tool_calls") == []:
        ak = dict(data.get("additional_kwargs") or {})
        ak.pop("tool_calls", None)
        ak.pop("function_call", None)
        data["additional_kwargs"] = ak
        data["invalid_tool_calls"] = []
    return AIMessage(**data)
