"""Setting up the conversational agent's per-novel long-term memory: decision distillation library read/write/merge + pre_model_hook."""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, TypedDict, cast

from langchain_core.messages import SystemMessage, ToolMessage

from engine.setup_chat.skill_activation import _ACTIVATION_HEADER, build_skill_activations


class RepairMode(StrEnum):
    """How to act on a dangling tool declaration (spec §4)."""

    PAIR = "pair"      # keep declaration, synthesize failure answers (D8)
    RESUME = "resume"  # drop the dangling AI message entirely (D6)


INTERRUPTED_MARKER = "（此处的工具调用因中断未执行）"
INTERRUPTED_TOOL_RESULT = "该调用因中断未执行，操作未生效。如需继续请重新调用本工具。"


@dataclass
class RepairReport:
    changed: bool = False
    dangling_ids: set[str] = field(default_factory=set)
    dangling_tools: list[str] = field(default_factory=list)


class DecisionDomain(StrEnum):
    WORLD = "world"
    CAST = "cast"
    PLOT = "plot"
    STYLE = "style"
    MISC = "misc"


class AlertKind(StrEnum):
    VETO = "veto"
    MANDATE = "mandate"


class Decision(TypedDict):
    id: str
    domain: DecisionDomain
    text: str
    status: Literal["active", "superseded"]
    alert: AlertKind | None
    ts: float


def _new_decision_id() -> str:
    return uuid.uuid4().hex[:8]


def _upgrade_v1_decisions(raw: list) -> list[Decision]:
    """Old flat-string decisions upgrade to domain=misc, alert=None, status=active
    on read; already-upgraded dict entries pass through unchanged."""
    now = time.time()
    out: list[Decision] = []
    for d in raw:
        if isinstance(d, dict) and "domain" in d:
            out.append(cast(Decision, d))
            continue
        text = str(d).strip()
        if text:
            out.append({
                "id": _new_decision_id(), "domain": DecisionDomain.MISC, "text": text,
                "status": "active", "alert": None, "ts": now,
            })
    return out


_MEM_DOC_KEY = "setup_chat_memory"
_log = logging.getLogger(__name__)

#Background distillation task handle (strong reference to prevent GC) + solo mark (according to persist path)
_bg_tasks: set[asyncio.Task] = set()
_inflight: set[str] = set()

_DISTILL_SYS = (
    "你是设定记账员，负责维护一份【决策账本】。账本记录的不是正面设定本身"
    "（那些已经写进 world/cast/plot 档案），只记录否决项、偏好，以及尚未落盘的决策。"
    "你会看到当前账本里所有生效中的条目（带 id/所属域/内容），以及一段新对话。"
    "对照两者输出一个 JSON 对象：\n"
    '{"add": [{"text": "...", "domain": "world|cast|plot|style|misc", '
    '"alert": "veto"|"mandate"|null}], '
    '"supersede": [{"id": "被替换条目的id", "replacement": "新文本", '
    '"domain": "...", "alert": "veto"|"mandate"|null}]}\n'
    "add 用于对话里出现的、账本里还没有的新决策；supersede 用于对话表明用户推翻/修改了某条"
    "已有决策——同一件事上说法变了，必须 supersede 旧条目，不能同时新增一条造成两条互相矛盾。"
    "alert 只在这条是硬约束时填：用户明确否决某个方向填 veto，明确要求必须如此填 mandate；"
    "普通偏好/尚未拍板的想法填 null。只输出 JSON，不要额外文字。"
)


class DistillOps(TypedDict):
    add: list[dict]
    supersede: list[dict]


def _novel_id_from_persist_dir(persist_dir: str) -> str:
    return os.path.basename(os.path.dirname(persist_dir.rstrip(os.sep)))


def _memory_store(persist_dir: str):
    from repositories.sqlite_store import SqliteStore

    return SqliteStore(_novel_id_from_persist_dir(persist_dir))


def load_memory(persist_dir: str) -> dict:
    data = _memory_store(persist_dir).get_doc(_MEM_DOC_KEY, "")
    if isinstance(data, dict) and isinstance(data.get("decisions"), list):
        return {**data, "decisions": _upgrade_v1_decisions(data["decisions"])}
    return {"decisions": []}


def save_memory(persist_dir: str, mem: dict) -> None:
    _memory_store(persist_dir).save_doc(_MEM_DOC_KEY, "", mem)


def _valid_domain(v: object) -> DecisionDomain | None:
    if not isinstance(v, str):
        return None
    try:
        return DecisionDomain(v)
    except ValueError:
        return None


def _valid_alert(v: object) -> AlertKind | None:
    if not isinstance(v, str):
        return None
    try:
        return AlertKind(v)
    except ValueError:
        return None


def apply_distill_ops(prev: dict, ops: DistillOps) -> dict:
    """Append-only ledger: supersede flips the old entry's status and appends its
    replacement as a new entry (never edits history in place). Unknown/already-superseded
    ids in supersede are silently skipped — no delete-by-id, only status flips."""
    decisions: list[Decision] = list(prev.get("decisions") or [])
    by_id = {d["id"]: d for d in decisions if isinstance(d, dict)}
    now = time.time()

    for s in ops.get("supersede", []):
        sid = s.get("id")
        if not isinstance(sid, str):
            continue
        old = by_id.get(sid)
        if old is None or old.get("status") != "active":
            continue
        old["status"] = "superseded"
        decisions.append({
            "id": _new_decision_id(),
            "domain": _valid_domain(s.get("domain")) or old["domain"],
            "text": str(s.get("replacement") or "").strip(),
            "status": "active",
            "alert": _valid_alert(s.get("alert")),
            "ts": now,
        })

    for a in ops.get("add", []):
        decisions.append({
            "id": _new_decision_id(),
            "domain": _valid_domain(a.get("domain")) or DecisionDomain.MISC,
            "text": str(a["text"]).strip(),
            "status": "active",
            "alert": _valid_alert(a.get("alert")),
            "ts": now,
        })

    return {**prev, "decisions": decisions}


PER_DOMAIN_QUOTA = 20


def _domains_over_quota(mem: dict) -> list[DecisionDomain]:
    counts: dict[str, int] = {}
    for d in mem.get("decisions") or []:
        if d.get("status") == "active":
            counts[d["domain"]] = counts.get(d["domain"], 0) + 1
    return [DecisionDomain(k) for k, n in counts.items() if n > PER_DOMAIN_QUOTA]


_CONSOLIDATE_SYS = (
    "你是设定记账员，负责压缩账本里某个域下过多的决策条目。"
    "以下条目都不是硬约束，把语义重复或可以合并表达的条目合并成更少、更精炼的条目，"
    '不丢失任何实际信息，只去冗余。输出 JSON：{"merged": ["条目1", "条目2", ...]}，'
    "条目数量必须明显少于输入。只输出 JSON。"
)


async def _consolidate_domain(
    persist: str, domain: DecisionDomain, call_llm: Callable[[str, str], Awaitable[str]],
) -> None:
    """LLM compresses one domain's active entries down to <= PER_DOMAIN_QUOTA. alert=veto/
    mandate entries are excluded from the prompt and copied through verbatim — never
    rewritten, so hard-constraint wording can't drift during compression."""
    mem = load_memory(persist)
    in_domain = [
        d for d in mem.get("decisions") or []
        if d.get("status") == "active" and d.get("domain") == domain
    ]
    if len(in_domain) <= PER_DOMAIN_QUOTA:
        return
    mergeable = [d for d in in_domain if not d.get("alert")]
    if not mergeable:
        return
    body = "\n".join(f"- {d['text']}" for d in mergeable)
    try:
        raw = await call_llm(_CONSOLIDATE_SYS, body)
    except Exception:  # noqa: BLE001
        return
    from engine.execution.embed_json import parse_embed_json

    parsed = parse_embed_json(raw or "")
    merged_texts = [
        t for t in ((parsed[0] if parsed else {}).get("merged") or []) if str(t).strip()
    ]
    if not merged_texts:
        return
    mem = load_memory(persist)  # re-read latest to avoid overwriting concurrent writes
    mergeable_ids = {d["id"] for d in mergeable}
    kept = [d for d in mem.get("decisions") or [] if d.get("id") not in mergeable_ids]
    now = time.time()
    kept.extend({
        "id": _new_decision_id(), "domain": domain, "text": t,
        "status": "active", "alert": None, "ts": now,
    } for t in merged_texts)
    save_memory(persist, {**mem, "decisions": kept})


def _text_of(m: object) -> str:
    c = getattr(m, "content", "")
    return c if isinstance(c, str) else str(c)


def _last_human_text_for_routing(msgs: list) -> str:
    for m in reversed(msgs):
        if getattr(m, "type", None) == "human":
            c = getattr(m, "content", "")
            return c if isinstance(c, str) else ""
    return ""


def _routing_embed_fn():
    from rag.embedding import get_embedding_function

    return get_embedding_function()


async def distill_decisions(
    old_messages: list,
    active_decisions: list[Decision],
    call_llm: Callable[[str, str], Awaitable[str]],
) -> DistillOps:
    """Reconciliation-style distillation: feeds the current active ledger (with ids)
    alongside the unprocessed conversation slice, gets back {add, supersede} ops.
    Failure/unparseable output -> empty ops (downgrade, don't block, don't advance)."""
    empty: DistillOps = {"add": [], "supersede": []}
    if not old_messages:
        return empty
    convo = "\n".join(
        f"{getattr(m, 'type', '')}: {_text_of(m)}" for m in old_messages if _text_of(m)
    )
    if not convo.strip():
        return empty
    ledger = "\n".join(
        f"[{d['id']}|{d['domain']}] {d['text']}" for d in active_decisions
    ) or "(账本为空)"
    try:
        raw = await call_llm(_DISTILL_SYS, f"## 现有决策账本\n{ledger}\n\n## 待处理对话\n{convo}")
    except Exception:  # noqa: BLE001 — 蒸馏纯增益，失败不阻塞
        return empty
    from engine.execution.embed_json import parse_embed_json

    parsed = parse_embed_json(raw or "")
    ops = parsed[0] if parsed else {}
    return {
        "add": [
            a for a in (ops.get("add") or [])
            if isinstance(a, dict) and str(a.get("text") or "").strip()
        ],
        "supersede": [
            s for s in (ops.get("supersede") or [])
            if isinstance(s, dict) and s.get("id")
        ],
    }


MEMORY_DISPLAY_HEADER = "## 已确立的设定决策（务必延续，勿与之矛盾）"
_MEMORY_INTERNAL_TAG = "## 内部决策备忘（禁止向用户复述或逐条列出）"


_ALWAYS_INJECTED_DOMAINS = {DecisionDomain.WORLD, DecisionDomain.STYLE, DecisionDomain.MISC}
_DOMAIN_ORDER = (DecisionDomain.WORLD, DecisionDomain.CAST, DecisionDomain.PLOT,
                  DecisionDomain.STYLE, DecisionDomain.MISC)


def _in_scope_domains() -> set[DecisionDomain]:
    from engine.setup_chat import skeleton_pipeline, world_pipeline

    scope: set[DecisionDomain] = set()
    if skeleton_pipeline.active_chapter() is not None:
        scope.add(DecisionDomain.PLOT)
    if world_pipeline.active_timeline_target() is not None:
        scope.add(DecisionDomain.CAST)
    return scope


def _visible_decisions(mem: dict) -> list[Decision]:
    active = [d for d in mem.get("decisions") or [] if d.get("status") == "active"]
    scope = _in_scope_domains()
    if not scope:
        return active
    return [
        d for d in active
        if d.get("alert") or d["domain"] in scope or d["domain"] in _ALWAYS_INJECTED_DOMAINS
    ]


def _render_memory(mem: dict) -> str:
    visible = _visible_decisions(mem)
    if not visible:
        return ""
    by_domain: dict[str, list[str]] = {}
    for d in visible:
        by_domain.setdefault(d["domain"], []).append(d["text"])
    lines = [_MEMORY_INTERNAL_TAG]
    for domain in _DOMAIN_ORDER:
        texts = by_domain.get(domain)
        if texts:
            lines.append(f"### {domain}")
            lines.extend(f"- {t}" for t in texts)
    return "\n".join(lines)


def strip_memory_for_display(content: str) -> str:
    """
Remove the long-term memory block (including the title line) that is occasionally repeated by the model; it is only for front-end display and does not affect the checkpoint."""
    for header in (MEMORY_DISPLAY_HEADER, _MEMORY_INTERNAL_TAG):
        if header not in content:
            continue
        lines = content.split("\n")
        i = 0
        if lines and (
            lines[0].strip().startswith("## 已确立的设定决策")
            or lines[0].strip().startswith("## 内部决策备忘")
        ):
            i = 1
            while i < len(lines) and (
                not lines[i].strip()
                or lines[i].lstrip().startswith("- ")
                or lines[i].lstrip().startswith("### ")
            ):
                i += 1
        content = "\n".join(lines[i:]).lstrip()
    return content


def _normalize_decision_line(line: str) -> str:
    return line.strip().lstrip("-• ").strip()


def _line_echoes_decision(line: str, decisions: list[Decision]) -> bool:
    norm = _normalize_decision_line(line)
    if not norm:
        return False
    for d in decisions:
        d_norm = _normalize_decision_line(d.get("text", ""))
        if not d_norm:
            continue
        if norm == d_norm:
            return True
        if len(norm) < 6:
            continue
        shorter, longer = (norm, d_norm) if len(norm) <= len(d_norm) else (d_norm, norm)
        if len(shorter) >= 10 and shorter in longer:
            if len(shorter) / len(norm) >= 0.65:
                return True
    return False


def strip_decision_echoes(content: str, decisions: list[Decision]) -> str:
    """Remove the memory.json decisions that are repeated one by one in the text (often without headers)."""
    if not content or not decisions:
        return content
    kept: list[str] = []
    for line in content.split("\n"):
        if _line_echoes_decision(line, decisions):
            continue
        kept.append(line)
    text = "\n".join(kept).strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text


def strip_internal_for_display(content: str, decisions: list[Decision] | None = None) -> str:
    """
Merge strip: memory title block + known decision line recap."""
    text = strip_memory_for_display(content)
    if decisions:
        text = strip_decision_echoes(text, decisions)
    return text.strip()


def sanitize_assistant_for_display(content: str, persist_dir: str) -> str:
    """Assistant text display/disk purification: memory retelling + novel setting injection block + stage activation block."""
    from engine.setup_chat.novel_context import strip_novel_context_for_display
    from engine.setup_chat.skill_activation import strip_activation_for_display

    decisions = load_memory(persist_dir).get("decisions") or []
    text = strip_internal_for_display(content, decisions)
    text = strip_novel_context_for_display(text)
    return strip_activation_for_display(text).strip()


def display_strip_header_prefixes() -> list[str]:
    """
Several types of internal block header prefixes (for streaming purposes) that can be displayed and purified "stripped from block header to segment end"."""
    from engine.setup_chat.novel_context import _LEGACY_CONTEXT_HEADER_PREFIX, _STATUS_HEADER_PREFIX
    from engine.setup_chat.skill_activation import _ACTIVATION_HEADER

    return [
        _STATUS_HEADER_PREFIX,
        _LEGACY_CONTEXT_HEADER_PREFIX,
        "## 已确立的设定决策",
        "## 内部决策备忘",
        _ACTIVATION_HEADER,
    ]


def safe_stream_emit_len(cleaned: str) -> int:
    """The length of the stream that can be safely sent out: If the last line is the true prefix (positive shape) of a peelable block, the line will be withheld and not sent out.

    Display purification "strips the internal `##` block header from the block header to the end of the segment; while the streaming increment only increases but never removes - half of the block header will leak in first.
    After the live and block pieces were formed, the final version was peeled off, causing "flash and then disappear". Accordingly, hold down the forming block prefix and wait for it to take shape.
    (stripped off) or longer than all prefixes (proven to be an ordinary title) before being released; the finalized message is still sent in full and purified, without losing the content."""

    nl = cleaned.rfind("\n")
    last_line = cleaned[nl + 1:]
    if not last_line:
        return len(cleaned)
    for header in display_strip_header_prefixes():
        if header.startswith(last_line) and last_line != header:
            return nl + 1 if nl >= 0 else 0
    return len(cleaned)


def _is_tool_message(m: object) -> bool:
    return isinstance(m, ToolMessage) or getattr(m, "type", None) == "tool"


def _is_ai_message(m: object) -> bool:
    from langchain_core.messages import AIMessage

    return isinstance(m, AIMessage) or getattr(m, "type", None) == "ai"


def _tool_call_ids(m: object) -> set[str]:
    """
Collect all tool_call ids declared by this message.

    You must look at three places at the same time: `.tool_calls` (parsed), `.invalid_tool_calls` (arguments caused by streaming interruption)
    incomplete, parsing failed), `additional_kwargs['tool_calls']` (original OpenAI format). The latter two are in `.tool_calls`
    When empty, it will still be resurrected as assistant's tool_calls when transferred to payload by langchain_openai - only see `.tool_calls`
    This kind of suspension application will be missed, resulting in verification and release, and ultimately DeepSeek will report 400."""

    out: set[str] = set()
    for tc in getattr(m, "tool_calls", None) or []:
        if isinstance(tc, dict) and tc.get("id"):
            out.add(str(tc["id"]))
    for tc in getattr(m, "invalid_tool_calls", None) or []:
        if isinstance(tc, dict) and tc.get("id"):
            out.add(str(tc["id"]))
    ak = getattr(m, "additional_kwargs", None) or {}
    for tc in ak.get("tool_calls") or []:
        if isinstance(tc, dict) and tc.get("id"):
            out.add(str(tc["id"]))
    return out


def _tool_call_names(m: object) -> list[str]:
    """Best-effort tool names from all three declaration sites (for reporting)."""
    out: list[str] = []
    for tc in list(getattr(m, "tool_calls", None) or []) + list(getattr(m, "invalid_tool_calls", None) or []):
        if isinstance(tc, dict) and tc.get("name"):
            out.append(str(tc["name"]))
    for tc in (getattr(m, "additional_kwargs", None) or {}).get("tool_calls") or []:
        if isinstance(tc, dict):
            name = (tc.get("function") or {}).get("name") if isinstance(tc.get("function"), dict) else tc.get("name")
            if name:
                out.append(str(name))
    return out


def _valid_tool_call_ids(m: object) -> set[str]:
    """Ids that survived parsing (executable declarations only)."""
    return {
        str(tc["id"]) for tc in (getattr(m, "tool_calls", None) or [])
        if isinstance(tc, dict) and tc.get("id")
    }


def repair_tool_call_sequence(
    msgs: list, *, mode: RepairMode = RepairMode.PAIR
) -> tuple[list, list, RepairReport]:
    """Fix incomplete tool rounds / orphaned ToolMessages (DeepSeek rejects both).

    PAIR keeps a fully-parseable declaration and appends synthesized failure
    answers so the model retains "I called X and it never ran". RESUME removes
    the dangling AI message entirely so a graph resume re-plans from clean state.
    Declarations with unparseable ids can't be paired -> rebuilt as plain text
    with an explicit interruption marker (never a fake acknowledgement).
    Returns (fixed list, checkpoint patches, report)."""
    from langchain_core.messages import RemoveMessage

    out: list = []
    patches: list = []
    report = RepairReport()
    i = 0
    while i < len(msgs):
        m = msgs[i]
        if _is_ai_message(m) and _tool_call_ids(m):
            needed = _tool_call_ids(m)
            j = i + 1
            seen: set[str] = set()
            while j < len(msgs) and needed - seen:
                tm = msgs[j]
                if not _is_tool_message(tm):
                    break
                tid = getattr(tm, "tool_call_id", None)
                if tid in needed:
                    seen.add(str(tid))
                    j += 1
                else:
                    break
            missing = needed - seen
            if missing:
                report.changed = True
                report.dangling_ids |= missing
                report.dangling_tools.extend(_tool_call_names(m))
                valid = _valid_tool_call_ids(m)
                if mode is RepairMode.RESUME:
                    if getattr(m, "id", None):
                        patches.append(RemoveMessage(id=m.id))
                    for k in range(i + 1, j):
                        if getattr(msgs[k], "id", None):
                            patches.append(RemoveMessage(id=msgs[k].id))
                    i = j
                    continue
                if missing <= valid:
                    out.append(m)
                    for k in range(i + 1, j):
                        out.append(msgs[k])
                    from langchain_core.messages import ToolMessage as _TM
                    for tid in sorted(missing):
                        synth = _TM(
                            content=INTERRUPTED_TOOL_RESULT,
                            tool_call_id=tid,
                            status="error",
                            id=f"synth-{tid}",
                        )
                        out.append(synth)
                        patches.append(synth)
                    i = j
                    continue
                content = m.content if isinstance(m.content, str) else ""
                from llm.message_utils import clone_ai_message

                fixed = clone_ai_message(
                    m,
                    content=content.strip() or INTERRUPTED_MARKER,
                    id=getattr(m, "id", None),
                    tool_calls=[],
                )
                out.append(fixed)
                if getattr(m, "id", None):
                    patches.extend([RemoveMessage(id=m.id), fixed])
                for k in range(i + 1, j):
                    if getattr(msgs[k], "id", None):
                        patches.append(RemoveMessage(id=msgs[k].id))
                i = j
                continue
            out.append(m)
            for k in range(i + 1, j):
                out.append(msgs[k])
            i = j
            continue
        if _is_tool_message(m):
            report.changed = True
            if getattr(m, "id", None):
                patches.append(RemoveMessage(id=m.id))
            i += 1
            continue
        out.append(m)
        i += 1
    return out, patches, report


def _cap_distilled_count(persist_dir: str, msg_count: int) -> None:
    """
The water level must not exceed the current number of messages, otherwise the feeding window will cross the limit."""
    mem = load_memory(persist_dir)
    w = _watermark(mem)
    if w > msg_count:
        mem["distilled_count"] = msg_count
        save_memory(persist_dir, mem)


async def ensure_checkpoint_messages_valid(
    agent, config: dict, persist_dir: str, *, mode: RepairMode = RepairMode.PAIR
) -> RepairReport:
    """Repair bad tool sequences persisted in the checkpoint; full-table rewrite
    on change. Returns the report (report.changed=False when nothing to fix)."""
    state = await agent.aget_state(config)
    if not state or not getattr(state, "values", None):
        return RepairReport()
    msgs = list(state.values.get("messages") or [])
    if not msgs:
        return RepairReport()
    repaired, _patches, report = repair_tool_call_sequence(msgs, mode=mode)
    if not report.changed:
        return report
    from langchain_core.messages import RemoveMessage
    from langgraph.graph.message import REMOVE_ALL_MESSAGES

    await agent.aupdate_state(
        config,
        {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *repaired]},
        as_node="agent",
    )
    _cap_distilled_count(persist_dir, len(repaired))
    _log.warning(
        "setup-chat checkpoint repaired (%s, %d -> %d msgs)",
        mode, len(msgs), len(repaired),
    )
    return report


def _has_tool_calls(m: object) -> bool:
    return bool(_tool_call_ids(m))


def _safe_tail_start(msgs: list, k: int) -> int:
    """
Take the nearest k starting indexes when feeding the model; if the cutoff point falls in the middle of the tool round, fall back to AI(tool_calls)."""
    if not msgs or k <= 0:
        return 0
    n = len(msgs)
    if n <= k:
        start = 0
    else:
        start = n - k
        while start > 0 and _is_tool_message(msgs[start]):
            start -= 1
    #History corruption: Window start remains orphaned tool → Skip to avoid DeepSeek 400
    while start < n and _is_tool_message(msgs[start]):
        start += 1
    return start


def _safe_tail_messages(msgs: list, k: int) -> list:
    if not msgs or k <= 0:
        return list(msgs)
    return list(msgs[_safe_tail_start(msgs, k) :])


def _watermark(mem: dict) -> int:
    """Number of steamed messages read (water mark); missing/illegal → 0."""
    try:
        return max(0, int(mem.get("distilled_count") or 0))
    except (TypeError, ValueError):
        return 0


def _feed_start(msgs: list, watermark: int) -> int:
    """
The starting point of the feeding window: starting from the water level; if it falls in the middle of the tool chain, it will fall back to AI (tool_calls), otherwise the isolated tool will be skipped."""
    n = len(msgs)
    start = min(max(watermark, 0), n)
    if start >= n or not _is_tool_message(msgs[start]):
        return start
    j = start - 1
    while j >= 0 and _is_tool_message(msgs[j]):
        j -= 1
    if j >= 0 and j >= watermark and _is_ai_message(msgs[j]) and _has_tool_calls(msgs[j]):
        return j
    while start < n and _is_tool_message(msgs[start]):
        start += 1
    return start


def _distill_cut(msgs: list, watermark: int, *, K: int, T: int) -> int | None:
    """Unsteamed tail (n-watermark) ≥ T → Return to the distillation end point cut (leaving the nearest ~K unsteamed and protecting the tool boundary);
    Insufficient tail or cut does not advance (no progress) → None."""
    if len(msgs) - watermark < T:
        return None
    cut = _safe_tail_start(msgs, K)
    return cut if cut > watermark else None


async def _run_distill(
    persist: str,
    old_slice: list,
    cut: int,
    call_llm: Callable[[str, str], Awaitable[str]],
) -> None:
    try:
        active = [
            d for d in load_memory(persist).get("decisions") or []
            if d.get("status") == "active"
        ]
        ops = await distill_decisions(old_slice, active, call_llm)
        if not ops["add"] and not ops["supersede"]:
            return
        mem = load_memory(persist)
        mem = apply_distill_ops(mem, ops)
        mem["distilled_count"] = cut
        save_memory(persist, mem)
        for domain in _domains_over_quota(mem):
            await _consolidate_domain(persist, domain, call_llm)
    except Exception:  # noqa: BLE001 — Distillation failure does not block or advance
        _log.exception("setup-chat 后台蒸馏失败")


def _spawn_distill(
    persist: str,
    old_slice: list,
    cut: int,
    call_llm: Callable[[str, str], Awaitable[str]],
) -> None:
    """
Background distillation on a single flight: the same persist is skipped on a fly; empty slices are skipped. Returns immediately after capturing the slice snapshot."""
    if not old_slice or persist in _inflight:
        return
    _inflight.add(persist)
    task = asyncio.create_task(_run_distill(persist, list(old_slice), cut, call_llm))
    _bg_tasks.add(task)

    def _done(t: asyncio.Task) -> None:
        _bg_tasks.discard(t)
        _inflight.discard(persist)

    task.add_done_callback(_done)


def make_pre_model_hook(
    persist_dir_getter: Callable[[], str],
    call_llm: Callable[[str, str], Awaitable[str]],
    *,
    K: int = 20,
    T: int = 50,
):
    """Returns the pre_model_hook of create_react_agent.

    Synchronization per round (no LLM, no blocking): Feed model = [novel inheritance context] + [long-term memory] + unsteamed tail after the watermark.
    The unsteamed tail has accumulated enough T bars → asynchronously steam the oldest section in the background into the long-term storage (leave the latest ~K without steaming), and advance the water level; hook does not wait for it.
    Only controls feeding model messages and does not change the persistence history."""
    async def hook(state: dict) -> dict:
        try:
            msgs = list(state.get("messages") or [])
            persist = persist_dir_getter()

            repaired_msgs, _patches, report = repair_tool_call_sequence(msgs, mode=RepairMode.PAIR)
            #The water level must never exceed the current number of messages: clamp first in each round. Fix shortening history, or background distillation concurrency to convert old cuts
            #It will happen when the writeback is out of bounds; without clamping, the feeding window will continue to degrade to only memory until the number of messages catches up with the out-of-bounds water mark.
            _cap_distilled_count(persist, len(repaired_msgs))

            mem = load_memory(persist)
            watermark = _watermark(mem)

            cut = _distill_cut(repaired_msgs, watermark, K=K, T=T)
            if cut is not None:
                _spawn_distill(persist, repaired_msgs[watermark:cut], cut, call_llm)

            feed_start = _feed_start(repaired_msgs, watermark)
            tail = repaired_msgs[feed_start:]
            fed: list = []
            from engine.setup_chat.tool_args import refresh_character_tool_args_schemas

            refresh_character_tool_args_schemas()
            from engine.setup_chat.novel_context import build_inherited_setup_context

            ctx = build_inherited_setup_context()
            if ctx:
                fed.append(SystemMessage(content=ctx))
            mem_block = _render_memory(mem)
            if mem_block:
                fed.append(SystemMessage(content=mem_block))
            from engine.setup_chat.skills import setup_chat_skill_dirs

            for body in build_skill_activations(repaired_msgs, setup_chat_skill_dirs()):
                fed.append(SystemMessage(content=_ACTIVATION_HEADER + "\n\n" + body))
            from engine.setup_chat.plan_runner import build_plan_activation

            plan_act = build_plan_activation()
            if plan_act:
                fed.append(SystemMessage(content=_ACTIVATION_HEADER + "\n\n" + plan_act))
            from engine.setup_chat import skeleton_pipeline

            seed_inj = skeleton_pipeline.active_seed_injection()
            if seed_inj:
                fed.append(SystemMessage(content=_ACTIVATION_HEADER + "\n\n" + seed_inj))
            from engine.setup_chat import world_pipeline

            tl_seed_inj = world_pipeline.active_timeline_seed_injection()
            if tl_seed_inj:
                fed.append(SystemMessage(content=_ACTIVATION_HEADER + "\n\n" + tl_seed_inj))
            from engine.setup_chat.mode import AUTO_MODE_BANNER, MANUAL_MODE_BANNER, is_auto_mode

            if is_auto_mode():
                fed.append(SystemMessage(content=_ACTIVATION_HEADER + "\n\n" + AUTO_MODE_BANNER))
            else:
                fed.append(SystemMessage(content=_ACTIVATION_HEADER + "\n\n" + MANUAL_MODE_BANNER))
            from engine.setup_chat import tool_router
            from engine.setup_chat.agent import all_registered_tools, tool_vectors_cache

            routed = await asyncio.to_thread(
                tool_router.route_tool_names,
                _last_human_text_for_routing(repaired_msgs),
                all_registered_tools(),
                embed_fn=_routing_embed_fn(),
                tool_vectors=tool_vectors_cache(),
            )
            fed.extend(tail)
            out: dict = {"llm_input_messages": fed or repaired_msgs, "routed_tool_names": sorted(routed)}
            if report.changed:
                from langchain_core.messages import RemoveMessage
                from langgraph.graph.message import REMOVE_ALL_MESSAGES

                out["messages"] = [RemoveMessage(id=REMOVE_ALL_MESSAGES), *repaired_msgs]
            return out
        except Exception:  #noqa: BLE001 — hook Never hang up the conversation; keep the latest K
            repaired, _, _ = repair_tool_call_sequence(state.get("messages") or [], mode=RepairMode.PAIR)
            return {"llm_input_messages": _safe_tail_messages(repaired, K)}
    return hook
