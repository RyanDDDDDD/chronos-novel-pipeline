"""回合渲染层:整章 messages 线程的两类文本——system 契约、整 stage 任务包。

自由度给文本、确定性留流程:system 定死主笔身份与创作义务,任务包每 stage 投喂
该 stage 全部拍的骨架(选中 beat-dialogue-design 拓展的拍已含台词)+角色卡。
状态直读 archive,按 stage 坐标自然演变。"""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from engine.author_loop.dialogue_mode.cards import render_character_card

CallLLM = Callable[..., Awaitable[tuple[str, int, int]]]

_SENTENCE_END_RE = re.compile(r"([。！？])")

def with_log(call_llm: CallLLM, *, step: int, agent: str) -> CallLLM:
    """给 call_llm 绑定 prompt 日志归属(拍号 + agent 名)。

    observer/seed 都靠它打日志:委托前包一层,把 _log_step/_log_agent 塞进 kwargs,
    直连节点也可直接传 kwargs。"""

    async def _c(system: str, user: str, *a, **k):  # noqa: ANN002, ANN003, ANN202
        k.setdefault("_log_step", step)
        k.setdefault("_log_agent", agent)
        return await call_llm(system, user, *a, **k)
    return _c

_BASE_SYS = (
    "你是主笔扩写师，负责把骨架拍写成正文。\n"
    "骨架是这一拍剧情的参考蓝本，不是必须逐条保底还原的下限——写作时可以按细节扩写需要，"
    "对骨架内容做适当的重写、合并、取舍，不必局限于把新内容插在骨架节点之间的空隙里。\n"
    "你的创作空间：①把符合角色人设的台词自然织入正文；②按细节扩写需要围绕骨架自由重写——"
    "新增动作、心理活动、表情/神态、呼吸等感官反应、过渡桥段，也可以调整骨架原有内容的写法，"
    "让这一拍写得足够丰满，这是主笔的核心职责，不是可有可无的点缀；③做必要的连接/过渡/文风打磨，"
    "让骨架的叙述更流畅。\n"
    "**骨架原句不是成稿**：骨架的原句不能直接誊抄进正文（哪怕骨架里已经写好了台词）——写到骨架"
    "已涉及的内容时，也要用你自己的措辞、句式重新表达，不能整句沿用骨架原文的字面表达。\n"
    "你要一次性写完这整个 stage 的正文，各拍之间可以自由安排段落节奏、自由穿插扩写内容\n"
    "写正文时只输出正文，不要解释、不要 JSON、不要 Markdown 小标题分节。\n"
)


def _core_xp_suffix(core_xp: list[str]) -> str:
    """本章题材基调(core_xp),整章一份,进 system,辅助创作走向——跟文风调色档同待遇,不是
    必须逐条兑现的大纲。"""
    items = [str(x).strip() for x in (core_xp or []) if str(x).strip()]
    if not items:
        return ""
    return "\n\n## 本章题材基调\n" + "、".join(items)


def _prose_style_suffix(prose_style: str) -> str:
    """文风调色档(含反 AI 腔反向卡)整卡进 system,吃前缀缓存,不与逐拍任务包混排。"""
    style = (prose_style or "").strip()
    if not style:
        return ""
    return f"\n\n## 文风调色档\n{style}"


def build_system_prompt(prose_style: str, core_xp: list[str] | None = None) -> str:
    """主笔身份 + 回合契约 + 题材基调 + 文风调色档(整章一份,进 messages[0])。"""
    return _BASE_SYS + _core_xp_suffix(core_xp or []) + _prose_style_suffix(prose_style)


def _sensation_notes_block(notes: list[str]) -> str:
    """体感软引导块:选定动作方案里的生理感受描述,仅供参考、非硬约束。"""
    items = [str(n).strip() for n in (notes or []) if str(n).strip()]
    if not items:
        return ""
    lines = "\n".join(f"- {n}" for n in items)
    return f"\n\n## 本拍体感参考\n{lines}"


def _dialogue_draft_block(draft: str) -> str:
    """构建期已生成的联合台词草稿（见 engine.setup_chat.dialogue_draft.draft_beat_dialogue）——
    措辞照搬 story_sandbox 的"必须缝合"框架，运行期零额外 LLM 调用直接渲染。"""
    text = (draft or "").strip()
    if not text:
        return ""
    return (
        "\n\n## 本拍台词草稿（必须缝合进这一拍正文，不是仅供参考——"
        "可以改写措辞、调整语序，但草稿里设计的对话交流本身不能整段跳过不用）\n"
        f"{text}"
    )


def _fragment_beat_text(text: str) -> str:
    """把整段 beat 正文按句末标点(。！？)后插入换行,渲染时零散化成逐句独立行——只是渲染呈现形式,
    不改标点本身、不改底稿存储,方便弱模型逐句定位注入/改写细节而非面对一整段无从下手。"""
    return _SENTENCE_END_RE.sub(r"\1\n", text).strip()


def _beat_section(n: int, beat: dict) -> str:
    """stage 任务包内单拍小节:第 N 拍骨架 + 该拍体感参考(若有) + 该拍台词草稿(若有)。"""
    text = _fragment_beat_text(str(beat.get("beat_intent") or "").strip())
    return (f"### 第 {n} 拍\n{text}"
            f"{_sensation_notes_block(beat.get('sensation_notes') or [])}"
            f"{_dialogue_draft_block(beat.get('dialogue_draft') or '')}")


def _character_cards_block(
    characters: list[str], chapter: int, stage: int,
    character_states: dict[str, dict] | None = None,
) -> str:
    """在场角色档案(人格+自称+当前动态状态):主笔据此写站位/台词/自称,不与身份错位。"""
    states = character_states or {}
    cards = "\n\n".join(
        render_character_card(c, chapter, stage, dynamic_state=states.get(c))
        for c in characters if c
    )
    if not cards.strip():
        return ""
    return "\n\n## 在场角色档案\n" + cards


def _recall_context_block(recall_context: str) -> str:
    """跨章记忆召回块(engine.memory_recall.recall.recall_relevant_context 的输出),已自带
    Markdown 标题,原样透传,空字符串时不渲染。"""
    text = (recall_context or "").strip()
    if not text:
        return ""
    return f"\n\n{text}"


def render_task_packet(
    *, stage: dict,
    character_states: dict[str, dict] | None = None, recall_context: str = "",
) -> str:
    """第 N 个 stage 任务包(N=stage['index']+1):在场角色档案在前，逐拍骨架在后（各拍按需附
    体感参考），跨章记忆召回块附在最后。"""
    n = int(stage.get("index", 0)) + 1
    chapter, stage_num = int(stage.get("chapter", 0)), int(stage.get("stage", 0))
    beats = [b for b in (stage.get("beats") or []) if isinstance(b, dict)]
    sections = "\n\n".join(
        _beat_section(i + 1, b) for i, b in enumerate(beats)
    )
    return (
        f"【第 {n} 个 stage 任务包】"
        f"{_character_cards_block(stage.get('characters') or [], chapter, stage_num, character_states)}\n\n"
        f"## 本 stage 骨架\n{sections}"
        f"{_recall_context_block(recall_context)}"
    )
