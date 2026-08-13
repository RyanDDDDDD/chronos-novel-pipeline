"""Shared single-shot fix agent runner: one high-effort-thinking LLM call (no ReAct
loop), used by the three background fix agents (character/world/chapter-skeleton) once
a review verdict says "needs fixing". The model plans every edit in this single pass and
emits them as (possibly several) parallel tool calls, which are executed directly --
there is no follow-up turn to see a tool's result and decide what to call next, so this
only works because none of the fix tools (edit_character, set_world_*, regenerate_stage)
need a prior call's result to decide the next one; each fix-agent prompt scopes the model
to acting only on what the review rubric names. Replaces the old bounded ReAct loop
(create_react_agent, recursion_limit=32): a single call structurally cannot hit a
recursion limit, so that whole failure class (silent job death, no notification -- see
docs/superpowers/specs/2026-08-09-setup-review-fix-agent-design.md) is gone by
construction rather than caught after the fact."""
from __future__ import annotations

from typing import Any


def _extract_text(content: Any) -> str:
    """AIMessage.content is either a plain string or (Anthropic, with tool calls/thinking
    active) a list of content blocks -- pull out just the "text" blocks, dropping
    "thinking"/"tool_use"/etc, so extended-thinking traces never leak into the
    user-facing summary."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "".join(parts).strip()
    return ""


async def run_single_shot_fix_agent(
    *, node_name: str, tools: list[Any], prompt: str, task_text: str,
) -> str:
    """Run one reasoning pass: bind tools + the node's configured model (high-effort
    thinking by default, see author_loop_skill_prefs._DEFAULT_THINKING_EFFORT_NODE_IDS)
    onto the LLM, ask it to plan and call every needed fix in this one turn, execute
    whatever tool calls come back, then return its accompanying text as the "what I
    changed" description fed into the caller's notify summary. `node_name` routes through
    the existing per-node model/sampling-param config (bind_node_llm + the pipeline config
    panel), so each fix agent can be tuned separately from the interactive chat agent."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from llm.factory import get_cloud_llm

    from engine.modes.author_loop_skill_prefs import (
        load_dialogue_prefs,
        node_llm_sampling_kwargs,
        resolve_node_base_llm,
    )

    import_params = load_dialogue_prefs()["import_llm_params"]
    base_llm = resolve_node_base_llm(get_cloud_llm(), node_name, import_params)
    model = base_llm.bind_tools(tools)
    sampling = node_llm_sampling_kwargs(base_llm, node_name, import_params)
    if sampling:
        model = model.bind(**sampling)

    response = await model.ainvoke(
        [SystemMessage(content=prompt), HumanMessage(content=task_text)],
    )

    tools_by_name = {t.name: t for t in tools}
    for call in response.tool_calls:
        tool = tools_by_name.get(call["name"])
        if tool is not None:
            await tool.ainvoke(call["args"])

    return _extract_text(response.content) or "（fix agent 未给出文字总结）"
