"""address_ref covers the same chapter detection (pure functional interface).

When creating a file, LLM freely generates per-target titles, which may miss the relationship rivals present in the same chapter (such as missing a certain girl in the three-girl scene);
Moreover, missed births under slider gate control will be used permanently and cannot be self-healed. This module only detects and exposes deficiencies, but does not remedy them——
It can be called by the builder to generate log alarms, and can also be reused for future remediation/batch auditing.

The baseline of expected coverage = the **same-chapter relationship opponents** of this character in the relationship map (master-slave rivals + equal group members in the same chapter).
This is consistent with the filtering criteria of the state_core relationship block in the same chapter: if there is a relationship and presence, it should have an exclusive title."""
from __future__ import annotations


def address_ref_targets_in_archive(archive: dict) -> set[str]:
    """The target keys of this chapter's (flat, single-snapshot) address_ref."""
    ar = archive.get("address_ref")
    return {str(k) for k in ar} if isinstance(ar, dict) else set()


def find_missing_address_targets(archive: dict, expected_targets: set[str]) -> list[str]:
    """Opponents who should have exclusive names but do not appear in address_ref throughout the process (sorted return; empty = complete coverage).

    expected_targets = The set of relational opponents in this chapter, calculated and injected by the caller (builder) through the social relationship graph——
    This module only performs pure set operations and does not rely on relationship sources (the engine is neutral, and the relationship source is in hooks/archive/social_relations)."""
    return sorted(expected_targets - address_ref_targets_in_archive(archive))


#── Remedy: Directed complement call (pure functional interface, LLM call is held by builder)───────────────────────


def build_remediation_prompt(
    name: str, missing: list[str], relation_desc: dict[str, str], state_hint: str, tone: str
) -> tuple[str, str]:
    """
Fill in the (system, user) prompt for address_ref that is missing.

    relation_desc = {opponent name: relationship description}, calculated and injected by the caller (builder) through the social relationship graph - this module does not touch
    Relational source (engine neutral). Let LLM derive an exclusive title based on the relationship + current psychology + the tone of the work; don’t make up your mind, and use words according to the tone."""
    rel_lines = [
        f"- 「{m}」：{relation_desc.get(m, '关系对象')}" for m in missing
    ]
    system = (
        "你为角色补全其对特定关系对象的专属称呼候选池。严格据给定关系性质 + 当前心理状态 + "
        "本作基调派生，**勿脑补关系、勿预设题材**。**下方列出的每个对象都必须给出 1–3 个称呼**"
        "（平等关系如姐妹/同门同辈走亲属或昵称类称呼，不必带主从色彩）。\n"
        '只输出 JSON：{"对象名": ["称呼1", "称呼2"], …}，不要其它内容。'
    )
    parts = [f"## 角色\n{name}", "## 待补称呼的关系对象\n" + "\n".join(rel_lines)]
    if state_hint:
        parts.append(f"## 当前心理状态\n{state_hint}")
    if tone:
        parts.append(f"## 本作基调\n{tone}")
    parts.append("## 任务\n为上述每个对象给出此刻贴合关系与心理的专属称呼候选池。")
    return system, "\n\n".join(parts)


def parse_remediation(raw: dict, missing: list[str]) -> dict[str, list[str]]:
    """
Parsing the complementary name reply → {opponent: [pool]}: Only the objects in missing are accepted, the values ​​are unified into non-empty list[str], and empty is discarded."""
    out: dict[str, list[str]] = {}
    if not isinstance(raw, dict):
        return out
    miss = set(missing)
    for k, v in raw.items():
        if k not in miss:
            continue
        if isinstance(v, list):
            pool = [str(x).strip() for x in v if str(x).strip()]
        elif isinstance(v, str) and v.strip():
            pool = [v.strip()]
        else:
            pool = []
        if pool:
            out[str(k)] = pool
    return out


def apply_remediation(archive: dict, pools: dict[str, list[str]]) -> None:
    """Inject the supplementary name pool into the file's (flat) address_ref (if the opponent
    entry already exists, it will not be overwritten). Modify in place."""
    ar = archive.get("address_ref")
    if not isinstance(ar, dict):
        ar = {}
        archive["address_ref"] = ar
    for target, pool in pools.items():
        ar.setdefault(target, list(pool))
