"""Plot-direction suggestions: one LLM call per turn that proposes short one-line
directions for what could happen next, grounded in this turn's finalized text + current
character states. Purely a UI aid for the off-page director's next instruction -- never
auto-submitted, never treated as canon.

Grounding material sits in the system prompt; only the director's hint travels as the user
turn (see suggest_directions's docstring)."""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from loguru import logger

from engine.story_sandbox.llm_json import extract_json_list
from engine.story_sandbox.state import CharacterState

CallLLM = Callable[[str, str], Awaitable[str]]

_SUGGEST_SYS = (
    "根据刚写完的这段正文、各角色的人设档案、以及各角色当前状态，给出 4 个不同的后续走向建议。"
    "如果 user 消息里给出了导演的补充提示，这 4 条建议必须都是围绕该提示方向的不同具体演绎——"
    "同一个方向下的不同走法/不同细节展开，不要只有一条贴合、其余几条各自跑去无关的新方向；"
    "没有补充提示时才需要给出 4 个彼此不同的后续走向。"
    "4 个后续走向建议中，应至少包含能触及/考验在场角色因果锚点（创伤/执念/渴望等，见人设档案）"
    "的走向——可以是冲突、抉择、或被迫面对底线/渴望的时刻，不要只给表层动作推进。"
    "每条建议必须紧接当前这一幕往下走——同一个地点、同一批在场角色、同一个时间点，"
    "是这一幕接下来会发生的事，不是跳到别的场景、别的时间、别的地点开启的新情节，"
    "也不是场景切换或时间跳跃。只有'在场角色'可以被建议行动/说话；'相关角色'（如果给出）"
    "目前不在场，只是背景/关系参考，默认不要让他们凭空出现在场景里或采取行动。"
    "每条只用一句话概括方向（不是完整正文，不是详细展开），"
    '只输出 JSON 字符串数组，形如 ["建议一", "建议二", "建议三", "建议四"]，'
    "不要输出任何 JSON 以外的文字。"
)

_TARGET_COUNT = 4


def _core_xp_block(core_xp: list[str] | None) -> str:
    items = [str(x).strip() for x in (core_xp or []) if str(x).strip()]
    if not items:
        return ""
    return "\n\n本章题材基调（建议方向贴合，但不强制覆盖正文已经写出的走向）：" + "、".join(items)


def _cards_block(cards: list[dict] | None, related_cards: list[dict] | None = None) -> str:
    if not cards and not related_cards:
        return ""
    body = ""
    if cards:
        body += "\n\n角色人设档案（静态资料，与下方当前状态互补）：\n" + "\n\n".join(
            c["card"] for c in cards
        )
    if related_cards:
        body += (
            "\n\n相关角色档案（不在场，仅供背景/关系参考——默认不要让他们出现或行动）：\n"
            + "\n\n".join(c["card"] for c in related_cards)
        )
    return body


def _recall_block_section(recall_block: str) -> str:
    """recall_block already carries its own "## 相关历史/设定回收" header (see
    memory_recall.recall.recall_relevant_context) -- just gate on emptiness and prepend a
    separating blank line, no extra header needed here."""
    text = (recall_block or "").strip()
    return f"\n\n{text}" if text else ""


async def suggest_directions(
    finalized_text: str, character_states: dict[str, CharacterState], call_llm: CallLLM,
    *, hint: str = "", core_xp: list[str] | None = None, cards: list[dict] | None = None,
    related_cards: list[dict] | None = None, recall_block: str = "",
) -> list[str]:
    """Returns up to 4 short one-line direction labels: one call, retried once (results merged
    and de-duplicated, first-seen order) if the first call comes back short of 4 -- never
    retried a third time, so a persistently uncooperative model still degrades to however many
    it actually produced. A result with more than 4 is truncated without retrying. Malformed/
    non-list JSON degrades to an empty list rather than raising -- a bad suggestion call must
    never break the turn that already succeeded at writing prose. extract_json_list tolerates a
    ```json fence or noise around the array, which weak models sometimes add despite the system
    prompt's "JSON only" instruction.

    related_cards (background/relationship context for characters connected to whoever's
    present, but not themselves present -- see cast.py::resolve_related_cast) are grounding
    only: a suggested direction shouldn't casually have them already acting in the scene. See
    docs/superpowers/specs/2026-07-26-sandbox-present-vs-related-cast-design.md.

    All grounding material (finalized text, character cards, character states, recall_block)
    lives in the system prompt; the user turn carries only the director's hint (or a bare
    instruction when no hint was given), so prompt caching keys off the system prefix across
    regenerate calls. recall_block is this same turn's already-computed recall context (see
    memory_recall.recall.recall_relevant_context) -- callers pass through whatever was recalled
    for the prose itself, not a fresh recall call, so a suggested direction never contradicts a
    setting/event the prose just relied on."""
    system = _SUGGEST_SYS + _core_xp_block(core_xp)
    system += f"\n\n刚写完的正文：{finalized_text}{_cards_block(cards, related_cards)}"
    system += f"\n\n各角色当前状态：{json.dumps(character_states, ensure_ascii=False)}"
    system += _recall_block_section(recall_block)
    user = (
        f"导演的补充提示：{hint.strip()}（4 条建议都要贴合这个方向分别展开，不要有的贴合有的跑题）"
        if hint.strip() else "无补充提示，请直接给出建议。"
    )

    async def _call_once() -> list[str]:
        raw = await call_llm(system, user)
        parsed = extract_json_list(raw)
        if parsed is None:
            logger.warning(
                "[story_sandbox] suggest_directions unparseable, raw={!r}", raw[:300]
            )
            return []
        return [str(item).strip() for item in parsed if isinstance(item, str) and item.strip()]

    results = await _call_once()
    if len(results) < _TARGET_COUNT:
        retry = await _call_once()
        seen: set[str] = set()
        merged: list[str] = []
        for item in [*results, *retry]:
            if item not in seen:
                seen.add(item)
                merged.append(item)
        results = merged
    if len(results) < _TARGET_COUNT:
        logger.warning(
            "[story_sandbox] suggest_directions degraded to {}/{} after retry",
            len(results), _TARGET_COUNT,
        )
    return results[:_TARGET_COUNT]
