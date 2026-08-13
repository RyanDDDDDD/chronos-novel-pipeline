"""ToolNode subclass adding call-level transactions (spec D2-D5) and the
upstream-write author guard (D13). Wrapping happens at node level so tool
bodies stay untouched and real tool_call_ids are available for snapshot
metadata (individual tools never see their own call id)."""
from __future__ import annotations

from typing import Any

from langgraph.prebuilt import ToolNode
from loguru import logger

from engine.setup_chat import tool_trace
from engine.setup_chat.author_guard import affected_chapter_range, stop_author_if_affected
from engine.setup_chat.turn_snapshot import restore_if_matches, take_snapshot

# Spec D3: explicit read-only set, default-strict -- unknown (incl. dynamic
# skill tools) count as writes. read_*/query_* prefixes cover future read tools.
READONLY_TOOL_NAMES = frozenset({
    "recall_research", "web_search", "load_skill", "present_choices",
})
_READONLY_PREFIXES = ("read_", "query_")


def is_write_tool(name: str) -> bool:
    if name in READONLY_TOOL_NAMES:
        return False
    return not name.startswith(_READONLY_PREFIXES)


def _extract_tool_calls(input: Any) -> list[dict]:
    """Tool calls this ToolNode invocation is being asked to run.

    Mirrors langgraph.prebuilt.tool_node.ToolNode._parse_input's three shapes —
    production dispatches each tool call individually via the Send API as
    {"__type": "tool_call_with_context", "tool_call": {...}, "state": {...}}, not
    the legacy {"messages": [AIMessage(tool_calls=[...])]} batch this used to
    assume exclusively (that silently made gate_tool_call a no-op in production —
    found live, 2026-07-08):
    1. dict with __type == "tool_call_with_context" -> single call, state inlined
    2. list of ToolCall dicts (each with type == "tool_call") -> Send API, no
       inlined state
    3. dict with a "messages" key, or bare message list -> legacy batch shape
    """
    if isinstance(input, dict) and input.get("__type") == "tool_call_with_context":
        tc = input.get("tool_call")
        return [tc] if isinstance(tc, dict) else []
    if isinstance(input, list) and input and isinstance(input[-1], dict) and input[-1].get("type") == "tool_call":
        return [tc for tc in input if isinstance(tc, dict)]
    msgs = input.get("messages") if isinstance(input, dict) else input
    if not msgs:
        return []
    last = msgs[-1]
    return [tc for tc in (getattr(last, "tool_calls", None) or []) if isinstance(tc, dict)]


def _result_tool_messages(result: Any) -> list:
    if isinstance(result, dict):
        return list(result.get("messages") or [])
    return list(result) if isinstance(result, list) else []


class TransactionalToolNode(ToolNode):
    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        from langchain_core.messages import ToolMessage

        from engine.setup_chat import plan_runner

        all_calls = _extract_tool_calls(input)
        rejected: dict[str, str] = {}
        for tc in all_calls:
            name = str(tc.get("name", ""))
            verdict = plan_runner.gate_tool_call(name, tc.get("args") or {})
            if verdict is not None:
                rejected[str(tc.get("id", ""))] = verdict
                # Gate blocks before the tool body ever runs -> on_tool_start/end never
                # fire for it. Log it here so the turn's trace shows attempted-but-blocked
                # calls too, not just the ones that actually executed.
                seq = tool_trace.next_call(name, tc.get("args") or {})
                tool_trace.log_call_rejected(seq, name, verdict)

        if not rejected:
            return await self._ainvoke_kept(input, config, **kwargs)

        reject_msgs = [
            ToolMessage(content=text, tool_call_id=cid,
                        name=next((str(tc.get("name", "")) for tc in all_calls
                                   if str(tc.get("id", "")) == cid), ""),
                        status="error")
            for cid, text in rejected.items()
        ]
        kept_ids = {str(tc.get("id", "")) for tc in all_calls} - set(rejected)
        if not kept_ids:
            return {"messages": reject_msgs}

        # Only the legacy batched shape can have a mix of kept/rejected calls in
        # one invocation (Send-dispatched shapes always carry exactly one call,
        # so a non-empty kept_ids there would already have skipped this branch
        # via `not rejected` above). Filter the AIMessage's tool_calls and
        # delegate the rest.
        msgs = input.get("messages") if isinstance(input, dict) else (input if isinstance(input, list) else None)
        if not msgs:
            return {"messages": reject_msgs}
        last = msgs[-1]
        kept = [tc for tc in (getattr(last, "tool_calls", None) or []) if str(tc.get("id", "")) in kept_ids]
        last = last.model_copy(update={"tool_calls": kept})
        input = {**input, "messages": [*msgs[:-1], last]} if isinstance(input, dict) else [*msgs[:-1], last]
        result = await self._ainvoke_kept(input, config, **kwargs)
        out_msgs = _result_tool_messages(result)
        return {"messages": [*out_msgs, *reject_msgs]}

    async def _ainvoke_kept(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        write_calls = [tc for tc in _extract_tool_calls(input) if is_write_tool(str(tc.get("name", "")))]
        if write_calls:
            for tc in write_calls:
                rng = affected_chapter_range(str(tc.get("name", "")), tc.get("args") or {})
                if rng is not None:
                    await stop_author_if_affected(
                        rng[0], rng[1],
                        f"设定工具 {tc.get('name')} 即将改写相关章节剧情，本章主笔进度已重置",
                    )
            take_snapshot(
                [str(tc.get("id", "")) for tc in write_calls],
                [str(tc.get("name", "")) for tc in write_calls],
            )
        result = await super().ainvoke(input, config, **kwargs)
        if write_calls:
            ids = {str(tc.get("id", "")) for tc in write_calls}
            answers = [tm for tm in _result_tool_messages(result)
                       if str(getattr(tm, "tool_call_id", "")) in ids]
            errored = [tm for tm in answers if getattr(tm, "status", None) == "error"]
            if answers and len(errored) == len(answers):
                restore_if_matches(ids)
            elif errored:
                logger.warning(
                    "[transactional-tools] mixed write batch (ok={}, err={}), restore skipped",
                    len(answers) - len(errored), len(errored),
                )
        return result
