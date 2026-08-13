"""The built-in prompt resource built by cast setting + two rounds of question generation (built in the engine, not hooks/packages user plug-in).

Reuse the REFINE primitive build_round_from_md to parse two rounds of ``## ROUND``; prompt is distributed with the engine as a built-in resource.
Do not use AgentPluginLoader (that is the per-chapter user plug-in discovery mechanism)."""
from __future__ import annotations

import os

from engine.execution.agent_hook import build_round_from_md

_PROMPT_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def _read(name: str) -> str:
    with open(os.path.join(_PROMPT_DIR, name), encoding="utf-8") as f:
        return f.read()


def load_system_prompt() -> str:
    """
Role team builder system prompt (persona + principle)."""
    return _read("system.md")


def build_round(round: int, prev_sel: dict | str | None) -> dict | None:
    """Take the round question spec (0=roster skeleton, 1=role-by-role depth; out of bounds=None)."""
    return build_round_from_md(_read("rounds.md"), round, prev_sel)
