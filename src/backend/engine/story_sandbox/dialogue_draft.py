"""Joint dialogue+action draft for the characters on stage this turn -- generated before prose
so the prose writer has a concrete reference for how the turn's exchange could play out, instead
of having to design every character's lines inline while also carrying the scene's narration.

A single LLM call drafts every present character's lines together (not one call per character):
splitting character performance into separate calls and re-assembling them was tried and reverted
in author_loop (see docs/superpowers/specs/2026-07-21-sandbox-dialogue-draft-design.md) because
per-character isolation loses the back-and-forth a real exchange needs. Prose is free to reword
the exact phrasing, but must actually weave the drafted exchange into the turn -- not skip it as
optional flavor -- see prompt.py's _progress_block, which labels it accordingly.

present_cards (may be given lines/actions) and related_cards (background/relationship context
only -- see cast.py::render_related_cast_block's docstring for why this split exists) are kept
separate all the way into this LLM's own system prompt, not just the final rendered prose
prompt: a related character's persona card is still useful context for how a present character
might refer to them, but this draft must never invent lines/actions FOR a related character
themselves. See docs/superpowers/specs/2026-07-26-sandbox-present-vs-related-cast-design.md."""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from loguru import logger

from engine.story_sandbox.state import CharacterState, Round

CallLLM = Callable[[str, str], Awaitable[str]]

_DRAFT_SYS_PREFIX = (
    "根据下面的指令、最近的正文记录、在场角色的人设档案与当前状态，为这些角色写一段联合对话草稿——"
    "角色之间可以互相搭话、反驳、接话，也可以有人保持沉默；这段草稿只是给正式动笔的作者参考，"
    "不是最终成稿，目标写出约 {turn_count} 行台词，"
    "不必刻意凑数——判断这轮确实不需要对话时仍可输出空字符串。\n"
    "只有'在场角色'可以被安排台词/动作；'相关角色'（如果给出）只是背景/关系参考，"
    "绝不能给相关角色写台词、动作或任何登场表现。\n"
)
#题材中性 baseline：意图构造引导 + few-shot 示例，内容包（如成人向）可经
#ContentPack.dialogue_intent_guidance 整段覆写，见 content_packs.py（与 setup_chat/
#dialogue_draft.py 共用同一份覆写——两处 baseline 文案逐字相同，是姊妹版本）。
_DEFAULT_INTENT_GUIDANCE = (
    "每一句台词落笔前，先想清楚这个角色此刻真正想要什么、想通过这句话达成什么——"
    "意图是台词设计里最重要的一环，必须写出来，不能只是把台词字面意思换个说法重复一遍，"
    "要点出台词背后没直说的目的/算计/心理落差；台词意图须源于该角色人设档案里的因果锚点"
    "（创伤/执念/渴望等），符合其心理底线与算计方式。\n"
    "格式：逐行「角色名（意图：……；动作/心理：……）：台词」，例如：\n"
    "柚子（意图：想逼退对方又不想彻底撕破脸；动作/心理：后退半步，声音发紧）：你别过来。\n"
    "陆屿（意图：试探她的底线，看她会不会真的翻脸；动作/心理：伸手按住门框，笑意不达眼底）：我说了不听？\n"
)
_DRAFT_SYS_SUFFIX = (
    "只输出这样的台词草稿本身，不要输出任何解释或标题；如果判断这一轮不适合安排对话，"
    "直接输出空字符串。"
)


def _draft_sys(turn_count: int) -> str:
    from context.content_packs import active_dialogue_intent_guidance

    guidance = active_dialogue_intent_guidance() or _DEFAULT_INTENT_GUIDANCE
    body = _DRAFT_SYS_PREFIX + guidance + _DRAFT_SYS_SUFFIX
    return body.replace("{turn_count}", str(turn_count))


def _cards_block(present_cards: list[dict], related_cards: list[dict]) -> str:
    body = "在场角色人设档案（可安排台词/动作）：\n" + "\n\n".join(c["card"] for c in present_cards)
    if related_cards:
        body += (
            "\n\n相关角色档案（不在场，仅供背景/关系参考——禁止为其安排台词或动作）：\n"
            + "\n\n".join(c["card"] for c in related_cards)
        )
    return f"\n\n{body}"


async def draft_dialogue(
    instruction: str, turns: list[Round], character_states: dict[str, CharacterState],
    present_cards: list[dict], related_cards: list[dict], call_llm: CallLLM,
    *, turn_count: int = 3,
) -> str:
    """Returns "" (no LLM call) when present_cards is empty -- with no one confidently present,
    there is no one to draft dialogue/actions for (related_cards alone never justifies a draft,
    per this module's whole present-vs-related split). All grounding material (cards, recent
    turns, character states) lives in the system prompt; the user turn carries only the
    instruction, same cache-friendly split as direction_suggest.py::suggest_directions.
    turn_count is a soft target rendered into the prompt, not a hard line-count guarantee --
    callers (graph.py's dialogue_draft nodes) compute it from the per-novel config or
    len(present_names) + 1; the default here only covers callers that don't care."""
    if not present_cards:
        return ""

    from engine.story_sandbox.prompt import recent_turns_block

    system = _draft_sys(turn_count) + _cards_block(present_cards, related_cards)
    system += f"\n\n最近的正文记录：\n{recent_turns_block(turns)}"
    system += f"\n\n各角色当前状态：{json.dumps(character_states, ensure_ascii=False)}"
    user = instruction if instruction.strip() else "本轮无特别指令，请直接续写。"
    raw = await call_llm(system, user)
    draft = raw.strip()
    logger.info(
        "[story_sandbox] dialogue_draft:\n{}", draft or "（本轮判断不适合安排对话，返回空）",
    )
    return draft
