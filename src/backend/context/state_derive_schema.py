"""Prompt builders + normalization for character-state derivation fields.

Field definitions live in context.content_packs (baseline + content-pack overrides);
this module turns them into LLM system prompts and validates scored_desc payloads."""
from __future__ import annotations

from typing import Any, Literal

from context.content_packs import StateFieldSpec, state_derive_fields

StateFieldKind = Literal["text", "scored_desc"]


def _fields_schema_line(fields: list[StateFieldSpec]) -> str:
    return "／".join(f.derive_hint for f in fields)


def _json_example_inner(fields: list[StateFieldSpec]) -> str:
    parts: list[str] = []
    for f in fields:
        if f.kind == "scored_desc":
            parts.append(f'"{f.key}": {{"score": 0, "desc": "..."}}')
        else:
            parts.append(f'"{f.key}": "..."')
    return ", ".join(parts)


def field_count() -> int:
    return len(state_derive_fields())


def build_init_sys() -> str:
    fields = state_derive_fields()
    n = len(fields)
    schema = _fields_schema_line(fields)
    example = _json_example_inner(fields)
    return (
        f"根据每个角色的人设档案、以及这一章开场的剧情梗概，为每个角色推演出登场时的初始状态，"
        f"只包含以下 {n} 个字段：{schema}。"
        "text 类字段每项一句话概括，要贴合人设和即将发生的剧情，不能空泛；"
        "scored_desc 类字段必须给出 score（0-100 整数）与 desc（一句话身体感受/外显征兆，"
        "供后续正文描写参考）。"
        f'只输出 JSON，形如 {{"角色名": {{{example}}}}}, '
        "覆盖收到的每一个角色，不要遗漏，一字不改地照抄档案里的角色名写法作为 key，"
        "不要新增档案之外的角色，也不要输出这些字段之外的任何字段，"
        "不要输出任何 JSON 以外的文字。"
    )


def build_init_sys_from_prose() -> str:
    """Mid-chapter sibling of build_init_sys: same cold-start contract (every field must get a
    grounded, non-empty value), but grounds on this turn's finalized prose instead of the
    opening instruction -- used when a character's first-ever appearance happens on a
    non-opening turn (no plot-outline prefill exists mid-chapter, only the written text)."""
    fields = state_derive_fields()
    n = len(fields)
    schema = _fields_schema_line(fields)
    example = _json_example_inner(fields)
    return (
        f"根据每个角色的人设档案、以及这段新写的正文，为每个角色推演出登场时的初始状态，"
        f"只包含以下 {n} 个字段：{schema}。"
        "text 类字段每项一句话概括，要贴合人设和正文实际写到的内容，不能空泛；"
        "scored_desc 类字段必须给出 score（0-100 整数）与 desc（一句话身体感受/外显征兆，"
        "供后续正文描写参考）。"
        f'只输出 JSON，形如 {{"角色名": {{{example}}}}}, '
        "覆盖收到的每一个角色，不要遗漏，一字不改地照抄档案里的角色名写法作为 key，"
        "不要新增档案之外的角色，也不要输出这些字段之外的任何字段，"
        "不要输出任何 JSON 以外的文字。"
    )


def build_derive_sys() -> str:
    fields = state_derive_fields()
    n = len(fields)
    schema = _fields_schema_line(fields)
    example = _json_example_inner(fields)
    return (
        f"根据这段新写的正文，输出其中出现的每个角色的状态，只包含以下 {n} 个字段：{schema}。"
        "text 类字段每项一句话概括；scored_desc 类字段必须给出 score（0-100 整数）"
        "与 desc（一句话身体感受/外显征兆，供后续正文描写参考）。"
        "你会收到每个角色此前的状态（角色刚登场、此前没有记录时是空的，此时每个字段都要"
        "根据这段正文合理推断出一个初始值，不能留空）；没有变化的字段照抄原值。哪怕是没有"
        "固定人设的临时/路人角色（例如路边大爷、班上同学这类），只要这段正文写了他们的言行，"
        "也要一并列出他们的状态，不要因为他们不在\"此前状态\"里就跳过。只输出 JSON，"
        f'形如 {{"角色名": {{{example}}}}}, '
        "只列出这段正文里实际出现的角色，不要输出这些字段之外的任何字段，"
        "不要输出任何 JSON 以外的文字。"
    )


def build_derive_sys_closed() -> str:
    fields = state_derive_fields()
    n = len(fields)
    schema = _fields_schema_line(fields)
    example = _json_example_inner(fields)
    return (
        f"根据这段新写的正文，为『在场角色』列表里给出的每一个角色输出状态，只包含以下 {n} 个字段："
        f"{schema}。text 类字段每项一句话概括；scored_desc 类字段必须给出 score（0-100 整数）"
        "与 desc（一句话身体感受/外显征兆，供后续正文描写参考）。"
        "你会收到每个角色此前的状态（角色刚登场、此前没有记录时是空的，此时每个字段都要"
        "根据这段正文合理推断出一个初始值，不能留空）；没有变化的字段照抄原值。只输出 JSON，"
        f'形如 {{"角色名": {{{example}}}}}, '
        "必须覆盖『在场角色』列表里的每一个名字，一字不改地照抄列表里的写法作为 key，"
        "不要新增列表之外的角色，不要输出这些字段之外的任何字段，不要输出任何 JSON 以外的文字。"
    )


def _normalize_scored_desc(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    score_raw = raw.get("score")
    desc_raw = raw.get("desc")
    if not isinstance(desc_raw, str) or not desc_raw.strip():
        return None
    if score_raw is None or isinstance(score_raw, bool):
        return None
    try:
        score = int(score_raw)
    except (TypeError, ValueError):
        return None
    score = max(0, min(100, score))
    return {"score": score, "desc": desc_raw.strip()}


def normalize_character_states(
    parsed: dict[str, dict[str, Any]],
    *,
    strict_scored_desc: bool,
) -> dict[str, dict[str, Any]] | None:
    """Normalize known fields; pass through unknown keys unchanged.

    When strict_scored_desc is True, any invalid scored_desc value for a registered field
    makes the whole parse fail (None) so sandbox derivation can retry."""
    fields = {f.key: f for f in state_derive_fields()}
    out: dict[str, dict[str, Any]] = {}
    for name, entry in parsed.items():
        if not isinstance(entry, dict):
            continue
        normalized_entry: dict[str, Any] = {}
        for key, value in entry.items():
            spec = fields.get(key)
            if spec is None:
                normalized_entry[key] = value
                continue
            if spec.kind == "scored_desc":
                scored = _normalize_scored_desc(value)
                if scored is None:
                    if strict_scored_desc:
                        return None
                    continue
                normalized_entry[key] = scored
            elif isinstance(value, str):
                normalized_entry[key] = value
            else:
                normalized_entry[key] = value
        out[str(name)] = normalized_entry
    return out


def format_state_field_value(key: str, value: Any) -> str | None:
    if value in ("", None, {}, []):
        return None
    fields = {f.key: f for f in state_derive_fields()}
    spec = fields.get(key)
    if spec and spec.kind == "scored_desc" and isinstance(value, dict):
        score = value.get("score")
        desc = value.get("desc")
        if isinstance(desc, str) and desc.strip() and score is not None:
            return f"{score}/100，{desc.strip()}"
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return str(value)
