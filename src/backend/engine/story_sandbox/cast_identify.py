"""Present-cast identification for story_sandbox: state_derive's two LLM calls
(derive_initial_states/derive_character_states) let the LLM freely decide which character names
to report, and it commonly shortens a full given_name (e.g. "高木柔柔" -> "柔柔") in the JSON key --
misattributing state and leaking the shortened form into active_cast (cast_tracker.py) and the UI.
This module adds a dedicated identification step (its own LLM call, told the full novel roster as
reference) followed by deterministic substring-containment normalization against that same
roster, so state_derive is only ever asked to describe (and only ever returns) canonical
given_names. See
docs/superpowers/specs/2026-07-20-sandbox-character-state-name-resolution-design.md."""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable

from loguru import logger

from engine.story_sandbox.derivation_retry import (
    DerivationValidationError,
    SandboxErrorCode,
    call_llm_with_retry,
)
from engine.story_sandbox.llm_json import extract_json_dict

CallLLM = Callable[[str, str], Awaitable[str]]

_IDENTIFY_SYS = (
    "根据导演指令与正文内容，判断这段情节里实际在场/出现的角色，分成两类分别列出："
    "「角色」是小说里有固定人设的角色——你会收到本小说的角色全名参考名单，能对上的角色请"
    "直接输出名单里的写法，不要自行简写或改写名字；「路人」是没有固定人设、纯粹这一场戏里"
    "临时出现的背景角色（例如路边大爷、班上同学这类），不需要对照参考名单，按正文/指令里"
    "实际的称呼写就行。只输出 JSON，形如 {\"角色\": [\"角色全名\", ...], \"路人\": "
    "[\"路人称呼\", ...]}，某一类没有就输出空数组，不要输出 JSON 以外的任何文字。"
)


def resolve_roster_names(raw_names: Iterable[str], roster: list[str]) -> dict[str, str | None]:
    """Maps each raw name to its resolved canonical roster name by substring containment
    (`raw in full or full in raw`, either direction) -- a unique hit resolves; hitting >=2
    distinct roster names (ambiguous) or 0 (unmatched) maps to None, never guessed. Duplicate raw
    names collapse to one entry; insertion order preserved."""
    resolved: dict[str, str | None] = {}
    for raw in raw_names:
        if raw in resolved:
            continue
        hits = {full for full in roster if raw in full or full in raw}
        resolved[raw] = next(iter(hits)) if len(hits) == 1 else None
    return resolved


def _clean_name_list(raw: object) -> list[str]:
    """去重(保序)+空值过滤，不做 roster 校验——用于「路人」这一路，也用于「角色」拿到原始
    字符串之后交给 resolve_roster_names 之前的预处理。长度上限防弱模型把一整句话当成一个
    名字塞进数组。"""
    if not isinstance(raw, list):
        return []
    seen: list[str] = []
    for item in raw:
        name = str(item).strip()
        if name and len(name) <= 20 and name not in seen:
            seen.append(name)
    return seen


def _parse_structured_names_or_none(raw: str) -> dict[str, list[str]] | None:
    parsed = extract_json_dict(raw)
    if parsed is None:
        return None
    return {
        "角色": _clean_name_list(parsed.get("角色")),
        "路人": _clean_name_list(parsed.get("路人")),
    }


_IDENTIFY_SYS_PROSE = (
    "根据这段正文内容，判断这段情节里实际在场/出现的角色，分成两类分别列出："
    "「角色」是小说里有固定人设的角色——你会收到本小说的角色全名参考名单，能对上的角色请"
    "直接输出名单里的写法，不要自行简写或改写名字；「路人」是没有固定人设、纯粹这一场戏里"
    "临时出现的背景角色（例如路边大爷、班上同学这类），不需要对照参考名单，按正文里"
    "实际的称呼写就行。只回答确实登场了、有实际言行的角色，只是被顺带提及、回忆或转述的名字"
    "不算在场。只输出 JSON，形如 {\"角色\": [\"角色全名\", ...], \"路人\": "
    "[\"路人称呼\", ...]}，某一类没有就输出空数组，不要输出 JSON 以外的任何文字。"
)


async def identify_present_characters(
    instruction: str, roster: list[str], call_llm: CallLLM,
) -> dict[str, list[str]]:
    """One LLM call: given this turn's director instruction (the sole grounding text -- the
    frontend prefills it from plot outline data on a fresh chapter, but whatever the director
    actually sends is what this reads) and the full novel roster as reference, returns a
    structured {"角色": [...], "路人": [...]} split -- 角色 entries may still be shortened,
    normalize with resolve_roster_names; 路人 entries are NOT roster-matched (they're not on
    it by definition), only cleaned via _clean_name_list."""
    roster_block = "、".join(roster)
    user = f"角色全名参考名单：{roster_block}\n\n导演指令：{instruction}"
    return await call_llm_with_retry(
        _IDENTIFY_SYS, user, call_llm,
        parse=_parse_structured_names_or_none, code=SandboxErrorCode.IDENTIFY_CAST_FAILED,
    )


async def identify_present_characters_in_prose(
    final_text: str, roster: list[str], call_llm: CallLLM,
) -> dict[str, list[str]]:
    """Post-prose sibling of identify_present_characters: same {"角色":[...],"路人":[...]}
    output contract and retry/parse machinery, but grounds on this turn's already-finalized
    final_text instead of the pre-prose instruction."""
    roster_block = "、".join(roster)
    user = f"角色全名参考名单：{roster_block}\n\n正文：{final_text}"
    return await call_llm_with_retry(
        _IDENTIFY_SYS_PROSE, user, call_llm,
        parse=_parse_structured_names_or_none, code=SandboxErrorCode.IDENTIFY_CAST_FAILED,
    )


async def resolve_present_roster_in_prose(
    final_text: str, roster: list[str], call_llm: CallLLM,
) -> tuple[list[str], list[str]] | None:
    """Post-prose sibling of resolve_present_roster -- same resolve_roster_names closed-set
    correction and roster-empty/retry-exhausted degrade contract (returns None), grounded on
    final_text instead of instruction."""
    if not roster:
        return None
    try:
        raw = await identify_present_characters_in_prose(final_text, roster, call_llm)
    except DerivationValidationError:
        logger.warning(
            "[story_sandbox] identify_present_characters_in_prose exhausted retries, falling back",
        )
        return None
    mapping = resolve_roster_names(raw["角色"], roster)
    dropped = [name for name, resolved in mapping.items() if resolved is None]
    if dropped:
        logger.info("[story_sandbox] cast_identify dropped unmatched/ambiguous names: {}", dropped)
    seen: list[str] = []
    for resolved in mapping.values():
        if resolved is not None and resolved not in seen:
            seen.append(resolved)
    return seen, raw["路人"]


async def resolve_present_roster(
    instruction: str, roster: list[str], call_llm: CallLLM,
) -> tuple[list[str], list[str]] | None:
    """Runs identify_present_characters + resolve_roster_names, returning
    (resolved_cast_names, passerby_names) -- 角色 goes through the same closed-set
    resolve_roster_names validation as before (unmatched/ambiguous dropped); 路人 passes
    through unfiltered (already cleaned by _clean_name_list inside identify_present_characters,
    never roster-checked -- they're not on the roster by definition). Returns None ("identify
    layer unavailable this turn") when `roster` is empty or the identify call's retries are
    exhausted -- same degrade contract as before, callers fall back to scan_characters."""
    if not roster:
        return None
    try:
        raw = await identify_present_characters(instruction, roster, call_llm)
    except DerivationValidationError:
        logger.warning("[story_sandbox] identify_present_characters exhausted retries, falling back")
        return None
    mapping = resolve_roster_names(raw["角色"], roster)
    dropped = [name for name, resolved in mapping.items() if resolved is None]
    if dropped:
        logger.info("[story_sandbox] cast_identify dropped unmatched/ambiguous names: {}", dropped)
    seen: list[str] = []
    for resolved in mapping.values():
        if resolved is not None and resolved not in seen:
            seen.append(resolved)
    return seen, raw["路人"]


def remap_state_keys(states: dict[str, dict], roster: list[str]) -> dict[str, dict]:
    """Defense-in-depth: even given a closed-set prompt, the derivation LLM's own returned dict
    may still use a shortened key. Re-resolves every key against the full `roster` the same way
    resolve_present_roster does; ambiguous/unmatched keys are dropped (logged), matched keys
    renamed to the canonical roster name. No-op when `roster` is empty -- mirrors
    resolve_present_roster's degrade rule."""
    if not roster:
        return states
    mapping = resolve_roster_names(states.keys(), roster)
    dropped = [raw for raw, resolved in mapping.items() if resolved is None]
    if dropped:
        logger.info("[story_sandbox] cast_identify dropped unresolvable state keys: {}", dropped)
    result: dict[str, dict] = {}
    for raw, value in states.items():
        canonical = mapping[raw]
        if canonical is not None:
            result[canonical] = value
    return result
