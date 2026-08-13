"""Rolling-summary fold: one LLM call per turn, merging this round's own text into the running
summary. Also extracts (in the same call, no extra LLM round-trip) a structured event entry for
later keyword recall -- see
docs/superpowers/specs/2026-07-14-story-sandbox-event-log-realtime-and-vector-memory-design.md
§5.7 (event_name/category retired along with story_sandbox's core_events registry dependency).
This codebase usually prefers zero-LLM continuity aids (see the retired chapter-summary agent,
dropped for AI-flavor drift), but sandbox sessions have no cheap non-LLM substitute available (no
pre-written skeleton text the way author_loop's beats have), so an LLM fold was chosen here
deliberately, accepting the tradeoff for this feature specifically."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

CallLLM = Callable[[str, str], Awaitable[str]]

_FOLD_SYS = (
    "你是剧情摘要助手。把「旧摘要」和「新发生的一段」合并，输出一个 JSON 对象，字段：\n"
    "summary：覆盖式合并摘要，只保留继续写作需要的关键事实（人物位置、状态变化、关键动作、"
    "关键台词要点），不要文学化改写，不要评论。\n"
    "event：这一段本身（不含旧摘要）的一句话事件描述。涉及的人物一律用本名（如「阿明」），"
    "严禁使用「他/她/你/我/主角」等代词或泛称——这段话会被单独摘出展示和检索，脱离上下文后"
    "代词无法回指，会造成指代不明。\n"
    "time：这段发生的场景/时刻描述（如「阿明向阿婉摊牌之后」），同样一律用本名，不用代词。\n"
    "location：这段实际发生的具体地点描述（如「阿明家的书房」），没有明确地点则留空字符串。\n"
    "characters：这段实际出场/涉及的角色本名字符串数组，不含代词、不含旁白式泛称，没有则空数组。\n"
    "entities：这段涉及的实体名字符串数组，人物用本名。\n"
    "只输出这一个 JSON 对象，不要任何多余文字。"
)


@dataclass
class FoldResult:
    """summary 始终有值（降级时也是纯文本兜底）；event/time/location/entities 仅在 LLM 输出合法
    JSON 且带 summary 字段时才非空（location 例外：可能是合法的空字符串，一律归一化为 None）——
    解析失败或缺字段一律视为「这轮没有可回收的事件」。characters 同 entities，缺省为空列表。"""

    summary: str
    event: str | None = None
    time: str | None = None
    location: str | None = None
    entities: list[str] = field(default_factory=list)
    characters: list[str] = field(default_factory=list)


async def fold_turn_into_summary(
    prev_summary: str, aged_out_text: str, call_llm: CallLLM, *, present: list[str] | None = None,
) -> FoldResult:
    from engine.story_sandbox.llm_json import extract_json_dict

    roster_hint = (
        f"这轮在场角色（叙述里请一律用这个写法，不要用代词或简称）：{'、'.join(present)}\n\n"
        if present else ""
    )
    user = f"{roster_hint}旧摘要：{prev_summary or '（无）'}\n\n新发生的一段：{aged_out_text}"
    raw = (await call_llm(_FOLD_SYS, user)).strip()

    obj = extract_json_dict(raw)
    if not obj:
        return FoldResult(summary=raw)
    summary = str(obj.get("summary") or "").strip()
    if not summary:
        return FoldResult(summary=raw)

    entities_raw = obj.get("entities")
    entities = (
        [str(e).strip() for e in entities_raw if str(e).strip()]
        if isinstance(entities_raw, list) else []
    )
    characters_raw = obj.get("characters")
    characters = (
        [str(c).strip() for c in characters_raw if str(c).strip()]
        if isinstance(characters_raw, list) else []
    )
    return FoldResult(
        summary=summary,
        event=str(obj.get("event") or "").strip() or None,
        time=str(obj.get("time") or "").strip() or None,
        location=str(obj.get("location") or "").strip() or None,
        entities=entities,
        characters=characters,
    )


@dataclass
class EventResult:
    """FoldResult minus summary semantics -- summary stays (default empty) so event_log.py::
    build_entry's scan_entities(f"{result.event} {result.summary}") works unchanged for both
    FoldResult and EventResult via the _EventLike Protocol."""

    event: str | None = None
    time: str | None = None
    location: str | None = None
    entities: list[str] = field(default_factory=list)
    characters: list[str] = field(default_factory=list)
    summary: str = ""


_SUMMARY_FOLD_SYS = (
    "你是剧情摘要助手。把「旧摘要」和「新发生的一段」合并，输出合并后的摘要——只保留继续写作需要的"
    "关键事实（人物位置、状态变化、关键动作、关键台词要点），不要文学化改写，不要评论。"
    "直接输出摘要文本本身，不要 JSON 包裹，不要任何多余的解释或标题。"
)

_EVENT_EXTRACT_SYS = (
    "你是事件摘要助手。根据「新发生的一段」，识别其中值得单独归档的记忆事件——同一回合里若"
    "有多段彼此独立、可分开检索的回忆/转折（例如不同角色各自回忆不同过去），应拆成多条；若"
    "只有一件核心事件则只输出一条。输出一个 JSON 对象，字段：\n"
    "events：事件数组，每项含 event/time/location/characters/entities 五个字段——\n"
    "  event：该条事件本身的一句话描述。涉及的人物一律用本名（如「阿明」），严禁使用"
    "「他/她/你/我/主角」等代词或泛称——这段话会被单独摘出展示和检索，脱离上下文后代词无法回指。\n"
    "  time：该条事件发生的场景/时刻描述，同样一律用本名，不用代词。\n"
    "  location：该条事件实际发生的具体地点描述，没有明确地点则留空字符串。\n"
    "  characters：该条实际出场/涉及的角色本名字符串数组，没有则空数组。\n"
    "  entities：该条涉及的实体名字符串数组，人物用本名。\n"
    "没有任何值得归档的事件时输出 {\"events\": []}。只输出这一个 JSON 对象，不要任何多余文字。"
)


def _event_result_from_obj(obj: dict) -> EventResult | None:
    event = str(obj.get("event") or "").strip() or None
    if not event:
        return None
    entities_raw = obj.get("entities")
    entities = (
        [str(e).strip() for e in entities_raw if str(e).strip()]
        if isinstance(entities_raw, list) else []
    )
    characters_raw = obj.get("characters")
    characters = (
        [str(c).strip() for c in characters_raw if str(c).strip()]
        if isinstance(characters_raw, list) else []
    )
    return EventResult(
        event=event,
        time=str(obj.get("time") or "").strip() or None,
        location=str(obj.get("location") or "").strip() or None,
        entities=entities,
        characters=characters,
    )


def _parse_extract_events_payload(obj: dict) -> list[EventResult]:
    events_raw = obj.get("events")
    if isinstance(events_raw, list):
        out: list[EventResult] = []
        for item in events_raw:
            if isinstance(item, dict):
                parsed = _event_result_from_obj(item)
                if parsed is not None:
                    out.append(parsed)
        return out
    single = _event_result_from_obj(obj)
    return [single] if single is not None else []


async def fold_summary(prev_summary: str, aged_out_text: str, call_llm: CallLLM) -> str:
    user = f"旧摘要：{prev_summary or '（无）'}\n\n新发生的一段：{aged_out_text}"
    raw = (await call_llm(_SUMMARY_FOLD_SYS, user)).strip()
    return raw


async def extract_events(aged_out_text: str, call_llm: CallLLM) -> list[EventResult]:
    from engine.story_sandbox.llm_json import extract_json_dict

    user = f"新发生的一段：{aged_out_text}"
    raw = (await call_llm(_EVENT_EXTRACT_SYS, user)).strip()
    obj = extract_json_dict(raw)
    if not obj:
        return []
    return _parse_extract_events_payload(obj)


async def extract_event(aged_out_text: str, call_llm: CallLLM) -> EventResult:
    """Legacy single-event entry point -- returns the first extracted event, or empty."""
    results = await extract_events(aged_out_text, call_llm)
    return results[0] if results else EventResult()
