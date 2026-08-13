"""Extract style excerpts (verbatim, per category: environment/dialogue/action/sex/interiority)
from imported novels' original text chunks and synthesize an auto-generated prose style preset --
parallel to, and independent of, novel_import.py's distillation branch (which deliberately
discards raw sentences and isn't reusable here): this module instead requires verbatim
extraction and forbids paraphrasing.

The synthesis stage (synthesize_style_card) produces a full card isomorphic to the static
presets in skills/prose-styles/*.md (title/opening/techniques/examples/taboos), and is allowed
to quote the excerpts above directly -- this is per-novel, gitignored, never-versioned data, not
bound by the static presets' "desensitize" rule.

Per docs/superpowers/specs/2026-07-22-prose-style-card-unification-design.md."""
from __future__ import annotations

import asyncio
import hashlib
import os

from context.content_packs import active_prose_style_extraction_prompt
from utils.paths import prose_styles_dir

from engine.execution.embed_json import parse_embed_json
from engine.execution.prose_style import render_prose_style_card
from engine.setup_chat.novel_import import TextChunk

_CATEGORIES: tuple[str, ...] = ("环境", "台词", "动作", "亲密描写", "心理")

_EXTRACT_SYSTEM_PROMPT = (
    "你是小说文风素材抽取助手。阅读下面这一段小说原文节选，从原文中逐字摘录（禁止改写、"
    "禁止复述、禁止生成新内容）属于以下类别的句子或片段，输出严格 JSON（不要 markdown 围栏），"
    "结构为 {\"环境\": [string], \"台词\": [string], \"动作\": [string], \"亲密描写\": [string], "
    "\"心理\": [string]}。环境=环境/场景描写；台词=角色说出的对白原句；动作=动作/身体动作描写；"
    "亲密描写=亲密/情感/交互片段；心理=心理活动/内心独白。某类没有就给空数组，每条摘录必须是原文中真实"
    "存在的连续片段，不得拼接、不得添加任何原文没有的文字。"
)

_MAX_ATTEMPTS = 3  # 1 attempt + up to 2 retries, mirrors novel_import.py's _MAP_MAX_ATTEMPTS


class ChunkStyleError(Exception):
    def __init__(self, chunk_index: int):
        self.chunk_index = chunk_index
        super().__init__(f"chunk {chunk_index} 文风抽取失败（已重试 {_MAX_ATTEMPTS - 1} 次）")


def _coerce_category_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str) and v.strip()]


def _coerce_examples(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        out.append({"label": str(item.get("label") or "").strip(), "text": text})
    return out


def _bound_llm():
    """Pipeline-configured client for prose_style_extraction (对话 tab import_llm_params)."""
    from llm.factory import get_cloud_llm

    from engine.modes.author_loop_skill_prefs import bind_node_llm, load_dialogue_prefs

    return bind_node_llm(
        get_cloud_llm(), "prose_style_extraction", load_dialogue_prefs()["import_llm_params"],
    )


async def extract_style_chunk(chunk: TextChunk, *, llm) -> dict[str, list[str]]:
    from langchain_core.messages import HumanMessage, SystemMessage

    system_prompt = active_prose_style_extraction_prompt() or _EXTRACT_SYSTEM_PROMPT
    last_exc: Exception | None = None
    for _attempt in range(_MAX_ATTEMPTS):
        try:
            resp = await llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=chunk.text),
            ])
            content = resp.content if hasattr(resp, "content") else str(resp)
            parsed = parse_embed_json(content if isinstance(content, str) else str(content))
            if parsed:
                obj = parsed[0]
                return {cat: _coerce_category_list(obj.get(cat)) for cat in _CATEGORIES}
            last_exc = ValueError("empty/unparseable JSON")
        except Exception as exc:  # noqa: BLE001 -- retried below; final failure raises ChunkStyleError
            last_exc = exc
    raise ChunkStyleError(chunk.index) from last_exc


async def run_style_map_stage(
    chunks: list[TextChunk], *, llm, concurrency: int | None,
) -> list[dict[str, list[str]]]:
    """Fan-out mirrors novel_import.py::run_map_stage, but callers here don't need per-chunk
    progress/failed-index reporting (only novel_import's distillation branch drives the WS
    progress bar) -- failed chunks are just skipped."""
    total = len(chunks)
    sem = asyncio.Semaphore(concurrency or total or 1)
    results_by_index: dict[int, dict[str, list[str]]] = {}

    async def _guarded(chunk: TextChunk) -> None:
        async with sem:
            try:
                results_by_index[chunk.index] = await extract_style_chunk(chunk, llm=llm)
            except ChunkStyleError:
                pass

    await asyncio.gather(*(_guarded(c) for c in chunks))
    return [results_by_index[i] for i in sorted(results_by_index)]


_MIN_LEN = 30
_MAX_LEN = 200
_HARD_CAP = 400
_MAX_SAMPLES_PER_CATEGORY = 5
_SENTENCE_ENDERS = "。！？"


def _truncate_to_sentence_end(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    window = text[:limit]
    cut = max((window.rfind(ch) for ch in _SENTENCE_ENDERS), default=-1)
    return window if cut == -1 else window[: cut + 1]


def _score(text: str) -> tuple[int, int]:
    in_band = _MIN_LEN <= len(text) <= _MAX_LEN
    return (0 if in_band else 1, -len(text))


def reduce_style_samples(chunk_results: list[dict[str, list[str]]]) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {cat: [] for cat in _CATEGORIES}
    seen: dict[str, set[str]] = {cat: set() for cat in _CATEGORIES}
    for result in chunk_results:
        for cat in _CATEGORIES:
            for raw in result.get(cat) or []:
                text = _truncate_to_sentence_end(raw.strip(), _HARD_CAP)
                if not text:
                    continue
                key = hashlib.sha1(text.encode("utf-8")).hexdigest()
                if key in seen[cat]:
                    continue
                seen[cat].add(key)
                merged[cat].append(text)
    return {
        cat: sorted(texts, key=_score)[:_MAX_SAMPLES_PER_CATEGORY]
        for cat, texts in merged.items()
    }


_CARD_SYSTEM_PROMPT = (
    "你是小说文风分析助手。下面是从同一部小说原文中逐字摘录、按类别分组的真实片段（不是你自己"
    "生成的内容，来自用户自己上传的小说，允许直接引用）。请仔细阅读这些片段体现出的遣词造句习惯、"
    "句式节奏、叙事视角、修辞偏好，产出一份「语感调色档」，严格输出 JSON（不要 markdown 围栏），"
    "结构为 {\"title\": string, \"opening\": string, \"techniques\": [string], "
    "\"examples\": [{\"label\": string, \"text\": string}], \"taboos\": [string]}。"
    "title=4-8字的中文风格名（不含「语感调色：」前缀）；"
    "opening=3-5句开场定位，讲清这套的核心技法、适合的场面/关系/节奏，并用一个类比收尾；"
    "techniques=4-6条发挥方向，每条一个独立手法，格式「**手法名**：具体规则，并引用至少1个来自"
    "下方片段的原文作为「示例」」；"
    "examples=2-3条风格样例，每条 label 是场景标签（如「开场铺垫」「高潮收尾」）、text 直接使用"
    "下方片段中的真实原文（可截取但不得改写、不得拼接）；"
    "taboos=2-3条这套忌讳，格式「忌……：为什么」。"
)


async def synthesize_style_card(
    selected_samples: dict[str, list[str]], *, novel_title: str, llm,
) -> dict:
    """Synthesize structured prose-style card fields (title/opening/techniques/examples/taboos)
    for render_prose_style_card to render. On unparseable LLM output, falls back to default
    values per field instead of failing the whole call."""
    from langchain_core.messages import HumanMessage, SystemMessage

    lines = [f"《{novel_title}》原文摘录（按类别分组）："]
    for cat, texts in selected_samples.items():
        for text in texts:
            lines.append(f"[{cat}] {text}")
    resp = await llm.ainvoke([
        SystemMessage(content=_CARD_SYSTEM_PROMPT),
        HumanMessage(content="\n".join(lines)),
    ])
    content = resp.content if hasattr(resp, "content") else str(resp)
    parsed = parse_embed_json(content if isinstance(content, str) else str(content))
    obj = parsed[0] if parsed else {}
    return {
        "title": str(obj.get("title") or "").strip() or f"{novel_title}风格",
        "opening": str(obj.get("opening") or "").strip(),
        "techniques": _coerce_category_list(obj.get("techniques")),
        "examples": _coerce_examples(obj.get("examples")),
        "taboos": _coerce_category_list(obj.get("taboos")),
    }


def _has_any_sample(samples: dict[str, list[str]]) -> bool:
    return any(texts for texts in samples.values())


async def run_style_extraction_pipeline(
    chunks: list[TextChunk],
    *,
    novel_id: str,
    novel_title: str,
    llm=None,
    concurrency: int | None,
) -> dict | None:
    resolved = llm if llm is not None else _bound_llm()
    chunk_results = await run_style_map_stage(chunks, llm=resolved, concurrency=concurrency)
    if not chunk_results:
        return None
    selected = reduce_style_samples(chunk_results)
    if not _has_any_sample(selected):
        return None
    card_fields = await synthesize_style_card(selected, novel_title=novel_title, llm=resolved)
    card = render_prose_style_card(
        title=card_fields["title"],
        opening=card_fields["opening"],
        techniques=card_fields["techniques"],
        examples=card_fields["examples"],
        taboos=card_fields["taboos"],
    )
    out_dir = prose_styles_dir()
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"auto-{novel_id}.md")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(card)
    os.replace(tmp, path)
    return {"id": f"auto-{novel_id}", "name": card_fields["title"]}
