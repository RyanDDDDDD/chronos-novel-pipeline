"""Character-state derivation for story-sandbox: two LLM calls share a dynamic field schema
(psychology/posture/clothing/action/demeanor + content-pack extras) -- distinct from the static
character card (identity/background/voice/etc., rendered separately by cast.py, never re-derived
here). derive_initial_states runs once, on a chapter's opening turn, before any prose exists --
grounded in each stage1 character's persona card + the opening premise + this turn's actual
instruction. derive_character_states
runs every turn after prose is finalized, updating whatever derive_initial_states (or a prior
turn) last reported."""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from context.state_derive_schema import (
    build_derive_sys,
    build_derive_sys_closed,
    build_init_sys,
    build_init_sys_from_prose,
    normalize_character_states,
)

from engine.story_sandbox.derivation_retry import SandboxErrorCode, call_llm_with_retry
from engine.story_sandbox.llm_json import extract_json_dict
from engine.story_sandbox.state import CharacterState

CallLLM = Callable[[str, str], Awaitable[str]]


def _init_sys() -> str:
    return build_init_sys()


def _init_sys_from_prose() -> str:
    return build_init_sys_from_prose()


def _derive_sys() -> str:
    return build_derive_sys()


def _derive_sys_closed() -> str:
    return build_derive_sys_closed()


def _parse_states_or_none(raw: str) -> dict[str, CharacterState] | None:
    """None when extract_json_dict can't parse a dict at all, or scored_desc normalization fails
    under strict mode -- triggers call_llm_with_retry's retry."""
    parsed = extract_json_dict(raw)
    if parsed is None:
        return None
    entries = {
        str(name): dict(fields)
        for name, fields in parsed.items()
        if isinstance(fields, dict)
    }
    normalized = normalize_character_states(entries, strict_scored_desc=True)
    return normalized


async def derive_initial_states(
    cards: list[dict], instruction: str, call_llm: CallLLM,
) -> dict[str, CharacterState]:
    """One-time initialization, run only on a chapter's opening turn before any prose exists --
    grounds each identified character's initial state in their persona card + this turn's actual
    instruction, the sole grounding text in both chapter and free mode (chapter mode's frontend
    prefills the composer from the plot outline on a fresh chapter, but whatever the director
    actually sends is what this reads -- see cast.resolve_character_cards for how `cards` is
    resolved). Returns {} without calling the LLM if there are no cards (e.g. the instruction
    named nobody the identify layer could resolve)."""
    if not cards:
        return {}
    cards_block = "\n\n".join(c["card"] for c in cards)
    user = f"角色人设档案：\n{cards_block}\n\n导演这一轮发送的开场指令：{instruction}"
    return await call_llm_with_retry(
        _init_sys(), user, call_llm,
        parse=_parse_states_or_none, code=SandboxErrorCode.INIT_STATE_FAILED,
    )


async def derive_initial_states_from_prose(
    cards: list[dict], final_text: str, call_llm: CallLLM,
) -> dict[str, CharacterState]:
    """Mid-chapter sibling of derive_initial_states, for a character's first-ever appearance on
    a non-opening turn -- same one-time cold-start contract, grounded on this turn's finalized
    prose instead of the opening instruction. Returns {} without calling the LLM if there are
    no cards."""
    if not cards:
        return {}
    cards_block = "\n\n".join(c["card"] for c in cards)
    user = f"角色人设档案：\n{cards_block}\n\n这段新写的正文：{final_text}"
    return await call_llm_with_retry(
        _init_sys_from_prose(), user, call_llm,
        parse=_parse_states_or_none, code=SandboxErrorCode.INIT_STATE_FAILED,
    )


async def derive_character_states(
    prior_states: dict[str, CharacterState], finalized_text: str, call_llm: CallLLM,
    present: list[str] | None = None,
) -> dict[str, CharacterState]:
    """Returns a dict of ONLY the characters the derivation reported -- caller merges this into
    the full character_states dict, leaving everyone else untouched. `present`, when given, is
    the already-resolved closed-set of canonical character names for this turn (see
    cast_identify.resolve_present_roster) -- the prompt then asks for exactly those names instead
    of letting the model freely decide who's present. `present=None` (the default) keeps the
    original free-form prompt, used when the identify layer degrades (see
    cast_identify.resolve_present_roster's docstring)."""
    if present is None:
        user = f"此前状态：{json.dumps(prior_states, ensure_ascii=False)}\n\n新正文：{finalized_text}"
        sys_prompt = _derive_sys()
    else:
        user = (
            f"在场角色：{json.dumps(present, ensure_ascii=False)}\n\n"
            f"此前状态：{json.dumps(prior_states, ensure_ascii=False)}\n\n新正文：{finalized_text}"
        )
        sys_prompt = _derive_sys_closed()
    return await call_llm_with_retry(
        sys_prompt, user, call_llm,
        parse=_parse_states_or_none, code=SandboxErrorCode.STATE_DERIVE_FAILED,
    )
