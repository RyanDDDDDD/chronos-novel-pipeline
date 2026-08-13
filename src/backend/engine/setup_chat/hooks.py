"""setup-chat LangGraph post_model_hook: only performs assistant retelling and purification (display layer).

Historically, there was still a "one-stop, one-step" final tool block here: after running through heavy tools such as construct/add_character in this round,
Just strip all the tool_calls of the model's subsequent AI messages into plain text. But it only matches ToolMessage by tool name, regardless of failure.
As a result, the retry call of the model after the tool **fails** is also stripped off as a chain call of the same wheel - manifested as "it says to retry but does not retry, you have to manually
Just send a message." The hard block has been deleted: step by step and return to prompt soft constraints + natural dependency doors between tools (such as schema needs to be
world), no longer use runtime hooks to intercept tool_calls."""
from __future__ import annotations

from collections.abc import Callable

from langchain_core.messages import AIMessage

#The maximum number of ReAct steps allowed in a single round of user messages (agent↔tools round trip); the default is 25, which is easily reached.
SETUP_CHAT_RECURSION_LIMIT = 64


def _sanitize_ai_message(ai: AIMessage, persist_dir: str) -> AIMessage:
    from llm.message_utils import clone_ai_message

    from engine.setup_chat.memory import sanitize_assistant_for_display

    if not isinstance(ai.content, str) or ai.tool_calls:
        return ai
    cleaned = sanitize_assistant_for_display(ai.content, persist_dir)
    if cleaned == ai.content:
        return ai
    return clone_ai_message(ai, content=cleaned or "好的。")


def make_post_model_hook(persist_dir_getter: Callable[[], str] | None = None):
    """
create_react_agent post_model_hook: Purify assistant retelling (remove internal memory/decision replay)."""

    def hook(state: dict) -> dict:
        from langchain_core.messages import RemoveMessage

        if persist_dir_getter is None:
            return {}
        msgs = state.get("messages") or []
        if not msgs:
            return {}
        last = msgs[-1]
        #Only plain text helper messages are sanitized; rounds with tool_calls are always allowed and calls are never stripped.
        if not isinstance(last, AIMessage) or not isinstance(last.content, str) or last.tool_calls:
            return {}
        sanitized = _sanitize_ai_message(last, persist_dir_getter())
        if sanitized is last:
            return {}
        if last.id:
            return {"messages": [RemoveMessage(id=last.id), sanitized]}
        return {"messages": [sanitized]}

    return hook
