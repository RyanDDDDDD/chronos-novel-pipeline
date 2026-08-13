"""Character dynamic-state derivation for dialogue_mode: two LLM calls share a dynamic field
schema (psychology/posture/clothing/action/demeanor + content-pack extras) -- distinct from the
static character card (identity/personality/physique/etc., resolved by cards.py, never re-derived
here). derive_initial_states runs once, on a chapter's opening stage, before any prose exists for
that stage -- grounded in each present character's persona card + the opening stage's skeleton text.
derive_character_states runs after every stage's prose is finalized, updating whatever the prior
call (initial or a previous stage) last reported."""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from context.state_derive_schema import build_derive_sys, build_init_sys, normalize_character_states

from engine.story_sandbox.llm_json import extract_json_dict

CallLLM = Callable[..., Awaitable[tuple[str, int, int]]]


def _init_sys() -> str:
    return build_init_sys()


def _derive_sys() -> str:
    return build_derive_sys()


def _parse_states_json(raw: str) -> dict[str, dict]:
    """Malformed/non-dict JSON, or a non-dict per-character entry, degrades to reporting nothing
    rather than raising -- a bad derivation call must never break a stage that already succeeded
    at writing prose."""
    parsed = extract_json_dict(raw)
    if parsed is None:
        return {}
    entries = {
        str(name): dict(fields)
        for name, fields in parsed.items()
        if isinstance(fields, dict)
    }
    normalized = normalize_character_states(entries, strict_scored_desc=False)
    return normalized or {}


async def derive_initial_states(
    cards: list[dict], stage_description: str, call_llm: CallLLM,
) -> dict[str, dict]:
    """One-time initialization, run only on a chapter's opening stage before any prose exists --
    grounds each present character's initial state in their persona card + the opening stage's
    skeleton text. Returns {} without calling the LLM if there are no cards."""
    if not cards:
        return {}
    cards_block = "\n\n".join(c["card"] for c in cards)
    user = f"角色人设档案：\n{cards_block}\n\n本章开场剧情梗概：{stage_description}"
    raw, _in_tokens, _out_tokens = await call_llm(_init_sys(), user)
    return _parse_states_json(raw)


async def derive_character_states(
    prior_states: dict[str, dict], finalized_text: str, call_llm: CallLLM,
) -> dict[str, dict]:
    """Returns a dict of ONLY the characters the derivation reported -- caller merges this into
    the full character_states dict, leaving everyone else untouched."""
    import json

    user = f"此前状态：{json.dumps(prior_states, ensure_ascii=False)}\n\n新正文：{finalized_text}"
    raw, _in_tokens, _out_tokens = await call_llm(_derive_sys(), user)
    return _parse_states_json(raw)
