"""Set dialog checkpoint → The front end can display history (filtering internal memory and tool intermediate states)."""
from __future__ import annotations

from engine.setup_chat.memory import sanitize_assistant_for_display, strip_memory_for_display


def export_chat_messages_for_ui(
    checkpoint_messages: list,
    *,
    persist_dir: str | None = None,
) -> list[dict]:
    """Export human/final ai from LangGraph state.messages with stable id.

    The ai message text with tool_calls (the description before the model adjustment tool) is not discarded and accumulated to follow it.
    The `thinking` folded block of the final answer; empty statements are not included, and if the entire answer is empty, the answer does not include thinking."""

    def _clean(content: object) -> str:
        if not isinstance(content, str) or not content.strip():
            return ""
        if persist_dir:
            return sanitize_assistant_for_display(content, persist_dir).strip()
        return strip_memory_for_display(content).strip()

    out: list[dict] = []
    pending_thinking: list[str] = []
    for i, m in enumerate(checkpoint_messages):
        role = getattr(m, "type", "") or ""
        if role in ("system", "tool"):
            continue
        if role == "ai" and getattr(m, "tool_calls", None):
            narration = _clean(getattr(m, "content", ""))
            if narration:
                pending_thinking.append(narration)
            continue
        content = getattr(m, "content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        if role == "ai":
            content = _clean(content)
            if not content:
                continue
        msg_id = getattr(m, "id", None) or f"ckpt-{i}"
        msg: dict = {
            "id": msg_id,
            "role": "user" if role == "human" else "assistant",
            "content": content,
        }
        if role == "ai" and pending_thinking:
            msg["thinking"] = "\n\n".join(pending_thinking)
        if role == "ai":
            pending_thinking = []
        out.append(msg)
    return out
