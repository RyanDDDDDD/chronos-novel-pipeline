"""AgentHook protocol base class.

Each hooks/packages/<directory>/hook.py defines a Hook subclass that inherits this class,
Gather agent-specific logic (skill options, output rendering, etc.) in one place.

The main loop and setup builder discover and instantiate Hook through AgentPluginLoader;
If the hook is not found, the caller downgrades (skips the skill / uses default behavior)."""
from __future__ import annotations

import re
from enum import StrEnum

_ROUND_HEADER_RE = re.compile(
    r"^##\s+ROUND\s+(global|segment)(?:\s+(radio|checkbox))?\s*$",
    re.MULTILINE,
)


class QuestionType(StrEnum):
    """
Multiple rounds of question format (setup questions / refine_analysis for analysis)."""

    GLOBAL = "global"
    """整章/整体一次产出。"""


    SEGMENT = "segment"
    """
逐段并行产出。"""


class SelectMode(StrEnum):
    """The selection base of skill candidate options - skill is self-declared, and the engine determines single/multiple selections accordingly (not hard-coded)."""

    SINGLE = "single"
    """
选 ≤1 个候选（默认）。"""


    MULTI = "multi"
    """选 0..N 个候选（无上限）。"""


def split_round_prompts(md: str) -> list[tuple[str, str | None, str]]:
    """
Press ``## ROUND <qtype> [<ctrl>]`` to cut refine_analysis and return [(qtype, ctrl, body)…].

    When ctrl is radio/checkbox, the engine forces the control type; the default ctrl=None maintains the status quo.
    Without ``## ROUND``, the entire article will be made into a single round ``[("segment", None, body)]`` (backwards compatible)."""

    matches = list(_ROUND_HEADER_RE.finditer(md))
    if not matches:
        body = md.strip()
        return [("segment", None, body)] if body else []
    out: list[tuple[str, str | None, str]] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        body = md[start:end].strip()
        out.append((m.group(1), m.group(2), body))
    return out


def _format_prev_sel(prev_sel: dict | str | None) -> str:
    """
Render the last round of user selections into text that can be injected into prompt."""
    if prev_sel is None:
        return "（无）"
    if isinstance(prev_sel, str):
        return prev_sel.strip() or "（无）"
    if summary := (prev_sel.get("summary") or "").strip():
        return summary
    return str(prev_sel)


def build_round_from_md(
    md: str,
    round: int,
    prev_sel: dict | str | None,
) -> dict | None:
    """Get the round section from markdown containing the ``## ROUND`` section and inject the ``{prev_sel}`` placeholder."""
    rounds = split_round_prompts(md)
    if round < 0 or round >= len(rounds):
        return None
    qtype_raw, ctrl, body = rounds[round]
    try:
        qtype = QuestionType(qtype_raw)
    except ValueError:
        #refine_analysis falls back to segment when the head is spelled incorrectly, which is consistent with the single-round headless pocket to avoid the whole step from collapsing.
        qtype = QuestionType.SEGMENT
    content = body.replace("{prev_sel}", _format_prev_sel(prev_sel))
    return {"content": content, "needLLM": True, "type": qtype, "force_type": ctrl}


class AgentHook:
    """
Agent plug-in base class. Each hook has a default empty implementation, and subclasses only override the required methods.

    handles: list[str]
        Declare which agent_names this hook is responsible for (for directory-level hook discovery).
        Single-agent-specific directories can be left blank."""


    #It is written by plugin_loader when loading and used for log and other rollback identification.
    _agent_name: str = ""

    handles: list[str] = []
    #Fields/data keys provided by this agent to prompt (for prompt requires contract lint; see AGENT_PACKAGE §5.5)
    injects: list[str] = []
    display_name: str = ""   #skill display name; empty → fallback agent directory name
    description: str = ""    #skill description; empty → fallback display_name/agent
    agent_type: str = ""     #structure / expansion, etc.; author_loop skill is used for discovery
    #Candidate options radio/multiple selection: skill self-declaration, the engine renders the radio/checkbox and parses the reply accordingly (default radio)
    select_mode: SelectMode = SelectMode.SINGLE
    default_role: str = ""   #Prompt role of single-node agent; empty → fallback agent name

    async def build_options(
        self,
        segment: dict,
        pi_data: dict,
        chapter: int,
        step_config: dict,
        call_llm=None,
    ) -> list[dict] | None:
        """
Main expansion skill: output a list of candidate solutions; None/[] means that no skill instructions are injected into this paragraph."""
        return None

    def render_selection_option(self, opt: dict) -> list[str] | None:
        """Render a single selected option into a line of instruction text; the agent can override it (such as pose's chain/pairs)."""
        return None
