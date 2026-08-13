"""Skill-side interactive assistant: Refine/parse selection/broadcast selection. For hook calls, the engine core does not reference——
The interactive form of "multiple choice questions" belongs to skill self-determination, so it is classified as skill-side (hook always import engine.execution.*)."""
from __future__ import annotations

from collections.abc import Awaitable, Callable


def roster_state_preamble(seg: dict, ctx: dict) -> str:
    """Pre-context before asking the question: List of characters present (to prevent out-of-the-box/original characters) + current status of the characters (to prevent options that are contrary to psychology).

    If the weak model does not provide a list when asking questions, it will make up the characters from the training memory (such as writing characters that are not in this chapter into the options). If it does not provide a status, it may
    Come up with angles that go against the tone of collapse/resistance. Both are taken from seg/ctx ready-made data. If empty, the corresponding segment is omitted."""
    parts: list[str] = []
    chars = [c for c in (seg.get("characters") or []) if c]
    if chars:
        parts.append(
            "## 在场角色（只能用这些角色，严禁引入名单外或原著记忆里的角色）\n" + "、".join(chars)
        )
    state = str(ctx.get("state_text", "")).strip()
    if state:
        parts.append("## 角色当前状态（拟选项须贴合，勿与心理基调相悖）\n" + state)
    return "\n\n".join(parts)


async def craft_options_via_refine(
    call_llm, *, agent: str, role: str | None, user: str
) -> list[dict]:
    """
Load refine_analysis.md of this skill as system (including craft + question setting rules + output format, prompt returns to md),
    LLM based on this beat + candidate options. Parse `{"options": [...]}` → [{label, ...}] (if not [])."""
    from llm.prompt_manager import PromptManager
    from utils.paths import AGENTS_DIR

    from engine.execution.embed_json import parse_embed_json

    system = PromptManager.load_agent_refine_analysis(agent, role, AGENTS_DIR)
    if not system.strip():
        return []
    raw, _i, _o = await call_llm(system, user, disable_thinking=True)
    objs = parse_embed_json(raw)
    obj = objs[0] if objs else {}
    opts = obj.get("options") if isinstance(obj, dict) else None
    if not isinstance(opts, list):
        return []
    return [o for o in opts if isinstance(o, dict) and str(o.get("label", "")).strip()]


def parse_choice_reply(reply: dict | None, *, n: int, multi: bool) -> list[int]:
    """
Parse select replies into a list of selected subscripts (0-based). Single/multiple selections are unified into list semantics (single=≤1).

    multi → reads {"choices":[1 base,...]} (also tolerates a single {"choice"}); single → reads {"choice": 1 base|0=skip}.
    Skip / empty → []; out of bounds / illegal, roll back the first item in single (preservation behavior), and eliminate it in multi."""

    r = reply or {}
    if multi:
        raw = r.get("choices")
        if raw is None and r.get("choice") is not None:
            raw = [r.get("choice")]
        picks: list[int] = []
        for x in raw or []:
            try:
                k = int(x)
            except (TypeError, ValueError):
                continue
            i = k - 1
            if 0 <= i < n and i not in picks:
                picks.append(i)
        return picks
    raw = r.get("choice")
    if raw is None:
        return [0]
    try:
        pick = int(raw)
    except (TypeError, ValueError):
        return [0]
    if pick == 0:
        return []
    i = pick - 1
    return [i] if 0 <= i < n else [0]


async def ask_choice(
    prompt_user,
    *,
    skill: str,
    seg: dict,
    options: list[dict],
    multi: bool,
    auto_pick: Callable[[], Awaitable[list[int]]] | None,
) -> list[int]:
    """
Select unified entrance. prompt_user has → via new channel prompt_user(kind, payload) to let the user choose;
    None → auto_pick(). Return to the selected subscript list ([]=skip→pure narrative)."""
    if prompt_user is None:
        return await auto_pick() if auto_pick is not None else []
    menu = [
        {"index": i + 1, "label": (str(o.get("label", "")).splitlines() or [""])[0]}
        for i, o in enumerate(options)
    ]
    payload: dict = {
        "skill": skill, "multi": multi, "index": seg.get("index", 0),
        "intent": seg.get("intent", seg.get("text", "")), "options": menu,
    }
    if seg.get("_beat") is not None:
        payload["beat"] = seg.get("_beat")
        payload["beats"] = seg.get("_beats")
    reply = await prompt_user("choice", payload)
    return parse_choice_reply(reply, n=len(options), multi=multi)
