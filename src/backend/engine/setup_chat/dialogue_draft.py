"""Per-beat joint dialogue draft, generated at construction time (write_chapter_skeleton) instead
of runtime -- mechanism ported from engine.story_sandbox.dialogue_draft.draft_dialogue (same
system-prompt style, same output format), grounded on what construction time actually has: this
beat's own just-generated text, persona cards (no dynamic_state -- that doesn't exist yet at
construction time), and the previous beat's text as recent context. Not exposed as a chat-agent
@tool -- called internally by tools.write_chapter_skeleton (via tools._fill_dialogue_drafts) the
same way skeleton_writer.generate_stage_beats is, guaranteeing per-beat coverage regardless of
whether the chat agent remembers to ask for it."""
from __future__ import annotations

import time

from loguru import logger

_DRAFT_SYS_PREFIX = (
    "根据下面这一拍的骨架正文、在场角色人设档案、上一拍（或上一段最后一拍）已写的正文，为这些角色写"
    "一段联合对话草稿——角色之间可以互相搭话、反驳、接话，也可以有人保持沉默；这段草稿只是给正式动笔的"
    "写作期主笔参考，不是最终成稿，目标写出约 {turn_count} 行台词，不必刻意凑数——判断这一拍确实不需要"
    "对话时仍可输出空字符串。\n"
)
#题材中性 baseline：意图构造引导 + few-shot 示例，内容包（如成人向）可经
#ContentPack.dialogue_intent_guidance 整段覆写，见 content_packs.py（与 story_sandbox/
#dialogue_draft.py 共用同一份覆写——两处 baseline 文案逐字相同，是姊妹版本）。
_DEFAULT_INTENT_GUIDANCE = (
    "每一句台词落笔前，先想清楚这个角色此刻真正想要什么、想通过这句话达成什么——意图是台词设计里最重要"
    "的一环，必须写出来，不能只是把台词字面意思换个说法重复一遍，要点出台词背后没直说的目的/算计/心理"
    "落差；台词意图须源于该角色人设档案里的因果锚点（创伤/执念/渴望等），符合其心理底线与算计方式。\n"
    "格式：逐行「角色名（意图：……；动作/心理：……）：台词」，例如：\n"
    "柚子（意图：想逼退对方又不想彻底撕破脸；动作/心理：后退半步，声音发紧）：你别过来。\n"
    "陆屿（意图：试探她的底线，看她会不会真的翻脸；动作/心理：伸手按住门框，笑意不达眼底）：我说了不听？\n"
)
_DRAFT_SYS_SUFFIX = (
    "只输出这样的台词草稿本身，不要输出任何解释或标题；如果判断这一拍不适合安排对话，直接输出空字符串。"
)


def _draft_sys(turn_count: int) -> str:
    from context.content_packs import active_dialogue_intent_guidance

    guidance = active_dialogue_intent_guidance() or _DEFAULT_INTENT_GUIDANCE
    body = _DRAFT_SYS_PREFIX + guidance + _DRAFT_SYS_SUFFIX
    return body.replace("{turn_count}", str(turn_count))


def _cards_block(characters: list[str], chapter: int, stage_num: int) -> str:
    from engine.author_loop.dialogue_mode.cards import render_character_card

    cards = "\n\n".join(
        render_character_card(name, chapter, stage_num, dynamic_state=None)
        for name in characters
    )
    return f"\n\n在场角色人设档案：\n{cards}"


async def _call_llm(system: str, user: str, *, meta: dict | None = None) -> str:
    """Stateless, non-streaming, no session binding -- routed through the
    "beat_dialogue_draft" import_llm_params node (对话 tab, distinct from sandbox
    dialogue_draft) like skeleton_writer._call_llm."""
    from domain.token_usage import extract_usage
    from langchain_core.messages import HumanMessage, SystemMessage
    from llm.factory import get_cloud_llm

    from engine.modes.author_loop_skill_prefs import bind_node_llm, load_dialogue_prefs

    llm = bind_node_llm(
        get_cloud_llm(), "beat_dialogue_draft", load_dialogue_prefs()["import_llm_params"],
    )
    t0 = time.perf_counter()
    resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
    elapsed_ms = (time.perf_counter() - t0) * 1000
    text = str(resp.content)
    tin, tout, tcached = extract_usage(resp)
    logger.info(
        "[setup_chat_perf] beat_dialogue_draft LLM | elapsed_ms={:.2f} | tokens_in={} "
        "tokens_out={} tokens_cached={} | meta={}",
        elapsed_ms, tin, tout, tcached, meta or {},
    )
    return text


async def draft_beat_dialogue(
    chapter: int, stage_num: int, beat_text: str, characters: list[str], prev_text: str,
) -> str:
    """单拍联合台词草稿。characters 为空时直接返回 ""，不发起调用（没有在场角色可安排台词）。
    失败静默降级为 ""，不向上抛异常——一拍的草稿生成失败不该阻断整批 write_chapter_skeleton。"""
    meta = {"chapter": chapter, "stage_num": stage_num, "character_count": len(characters)}
    if not characters:
        logger.info(
            "[setup_chat_perf] beat_dialogue_draft skipped (no characters) | meta={}", meta,
        )
        return ""
    turn_count = len(characters) + 1
    system = _draft_sys(turn_count)
    system += _cards_block(characters, chapter, stage_num)
    system += f"\n\n这一拍的骨架正文：\n{beat_text}"
    if prev_text:
        system += f"\n\n最近上下文（上一拍/上一段已写的正文）：\n{prev_text}"
    from utils.timer import setup_chat_step_timer

    async with setup_chat_step_timer("beat_dialogue_draft.draft_beat_dialogue", extra_meta=meta):
        try:
            raw = await _call_llm(
                system, "请给出这一拍的联合台词草稿。", meta={**meta, "turn_count": turn_count},
            )
        except Exception:  # noqa: BLE001 -- one beat's draft failing must not block the whole batch
            logger.exception(
                "[setup_chat_perf] beat_dialogue_draft failed | meta={}", meta,
            )
            return ""
        draft = raw.strip()
        logger.info(
            "[setup_chat_perf] beat_dialogue_draft completed | draft_chars={} meta={}",
            len(draft), meta,
        )
        return draft
