"""Slash-triggered plot-extension skill suggestions for story-sandbox: `/skill-name` typed
into the regenerate-suggestions hint runs that skill's own tools (if any) through a one-shot
ReAct call instead of the plain suggest_directions LLM call, degrading to [] on any failure --
same "a bad regenerate call must never break the session" philosophy as suggest_directions.
Kept as its own module (not folded into graph.py) because it pulls in the setup_chat skill
registry, which graph.py otherwise has no reason to depend on."""
from __future__ import annotations

import json
from typing import Protocol

from engine.story_sandbox.llm_json import extract_json_list
from engine.story_sandbox.state import CharacterState

_MAX_SKILL_SUGGESTIONS = 8

_OUTPUT_CONTRACT = (
    "你现在在「故事沙盒」里被调用，产出的是给场外导演挑选的候选建议，不是骨架/beat 结构——"
    "忽略下面 skill 正文里任何关于 present_choices/patch_chapter/beat 字段之类具体调用方式的"
    "描述，改成：只输出最终答案，形如 JSON 字符串数组 [\"候选一\", \"候选二\", ...]，不要输出"
    "数组外的文字。每个候选可以是多行文本（比如分拍的动作画面+生理感受），导演选中后会原样"
    "拼进下一轮指令。只用你被绑定的工具；没有工具就直接从下面的正文内容里挑契合的条目。"
)


class RunSkillAgent(Protocol):
    """Real implementation (a one-shot, checkpointer-less create_react_agent call) lives in
    message_hub.py -- mirrors graph.py's WriteTurn/CallLLM Protocol split, keeping this module
    free of any direct LLM client import."""

    async def __call__(self, system: str, user: str, tools: list) -> str: ...


def parse_skill_hint(hint: str) -> tuple[str | None, str]:
    """`/skill-name rest of hint` -> (skill-name, rest) only if skill-name is a registered
    kind=plot-extension skill; otherwise (None, hint unchanged) so the caller falls back to
    plain suggest_directions. A `/` followed by an unregistered or non-plot-extension name is
    treated as ordinary hint text, not an error."""
    from engine.setup_chat import skills as _skills
    from engine.setup_chat.skill_activation import parse_slash_command

    name = parse_slash_command(hint)
    if name is None:
        return None, hint
    index = _skills.list_skill_index(_skills.setup_chat_skill_dirs())
    match = next(
        (it for it in index if it["name"] == name and it.get("kind") == "plot-extension"), None,
    )
    if match is None:
        return None, hint
    rest = hint.strip()[len(name) + 1:].strip()
    return name, rest


def _cards_block(cards: list[dict] | None, related_cards: list[dict] | None = None) -> str:
    if not cards and not related_cards:
        return ""
    body = ""
    if cards:
        body += "\n\n角色人设档案：\n" + "\n\n".join(c["card"] for c in cards)
    if related_cards:
        body += (
            "\n\n相关角色档案（不在场，仅供背景/关系参考——默认不要让他们出现或行动）：\n"
            + "\n\n".join(c["card"] for c in related_cards)
        )
    return body


def _core_xp_block(core_xp: list[str] | None) -> str:
    items = [str(x).strip() for x in (core_xp or []) if str(x).strip()]
    if not items:
        return ""
    return "\n\n本章题材基调：" + "、".join(items)


def _recall_block_section(recall_block: str) -> str:
    """recall_block already carries its own "## 相关历史/设定回收" header (see
    memory_recall.recall.recall_relevant_context) -- just gate on emptiness and prepend a
    separating blank line, no extra header needed here."""
    text = (recall_block or "").strip()
    return f"\n\n{text}" if text else ""


async def run_skill_suggestion(
    skill_name: str,
    finalized_text: str,
    character_states: dict[str, CharacterState],
    run_skill_agent: RunSkillAgent,
    *,
    hint: str = "",
    core_xp: list[str] | None = None,
    cards: list[dict] | None = None,
    related_cards: list[dict] | None = None,
    recall_block: str = "",
) -> list[str]:
    """Run one plot-extension skill's own tools (if any) through run_skill_agent to produce a
    fresh suggestions list. Degrades to [] if the skill body can't be loaded, or the agent's
    final answer isn't a valid JSON string array -- never raises, mirrors suggest_directions.

    related_cards (background/relationship context for characters connected to whoever's
    present, but not themselves present -- see cast.py::resolve_related_cast) mirrors
    direction_suggest.py::suggest_directions's own present-vs-related split.

    recall_block is this same turn's already-computed recall context (see
    memory_recall.recall.recall_relevant_context) -- passed through, not freshly recalled, so a
    skill-generated candidate never contradicts a setting/event the prose just relied on."""
    from utils.paths import SETUP_CHAT_SKILLS_DIR

    from engine.setup_chat import skills as _skills

    body = _skills.load_skill_body(skill_name, _skills.setup_chat_skill_dirs())
    if not body:
        return []
    tools = _skills.collect_single_skill_tools(SETUP_CHAT_SKILLS_DIR, skill_name)

    system = f"{_OUTPUT_CONTRACT}\n\n{body}"
    user = f"刚写完的正文：{finalized_text}"
    user += _cards_block(cards, related_cards)
    user += _core_xp_block(core_xp)
    user += f"\n\n各角色当前状态：{json.dumps(character_states, ensure_ascii=False)}"
    user += _recall_block_section(recall_block)
    if hint.strip():
        user += f"\n\n导演的补充提示：{hint.strip()}"

    raw = await run_skill_agent(system, user, tools)
    parsed = extract_json_list(raw)
    if parsed is None:
        return []
    items = [str(item).strip() for item in parsed if isinstance(item, str) and item.strip()]
    return items[:_MAX_SKILL_SUGGESTIONS]
