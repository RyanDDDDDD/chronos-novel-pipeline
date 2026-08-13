"""Novel import: chunked Map extraction with serial context carry-forward and periodic compaction.

Per docs/superpowers/specs/2026-07-16-novel-import-chunked-mapreduce-design.md and
docs/superpowers/specs/2026-07-22-novel-import-sequential-map-context-design.md.
Replaces the previous single-shot whole-text distillation in attachment_tool.py --
arbitrary-length input, paragraph-aligned chunking, serial Map with periodic reduce + RAG write."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from llm.retry import RATE_LIMIT_BACKOFF_S, RATE_LIMIT_ERRORS
from loguru import logger
from repositories import get_research_repo
from repositories.entities import ResearchCategory, ResearchChunk

from engine.execution.embed_json import parse_embed_json

_MAP_SYSTEM_PROMPT = (
    "你是小说设定提炼助手。阅读下面这一段小说原文节选，输出严格的 JSON（不要 markdown 围栏），"
    "结构为 {\"world\": [string], \"characters\": [{\"name\": string, \"personality\": string, "
    "\"verbal_tic\": string}], \"plot\": [string]}。world 是本段出现的世界观/设定要点；"
    "characters 只收本段出现的角色的性格与口癖，不要摘抄台词原句；plot 是本段的关键剧情点。"
    "没有的类别给空数组。"
)

_CONTEXT_PREAMBLE = (
    "\n\n已知设定（前面分片提炼的阶段性结果，可能不完整，供参考——"
    "避免把已出现的角色当成新角色重复识别或改名）：\n"
)

_REDUCE_SYSTEM_PROMPT = (
    "你是小说设定合并助手。下面是同一部小说按原文顺序切出的若干分片各自的提炼结果（JSON 数组，"
    "每项对应一个分片，数组顺序即原文先后顺序）。请合并去重成一份，输出严格 JSON（不要 markdown "
    "围栏），结构与输入单项一致：{\"world\": [string], \"characters\": [{\"name\": string, "
    "\"personality\": string, \"verbal_tic\": string}], \"plot\": [string]}。"
    "同一角色在不同分片重复出现时合并成一条，personality/verbal_tic 若随情节演变，"
    "用一句话概括其变化而非简单拼接；plot 按原文先后顺序排列，去掉重复表述。"
)

_MAP_MAX_ATTEMPTS = 3  # 1 attempt + up to 2 retries (spec decision 14)


@dataclass
class TextChunk:
    index: int
    text: str


class ChunkMapError(Exception):
    def __init__(self, chunk_index: int, reason: str = ""):
        self.chunk_index = chunk_index
        self.reason = reason
        suffix = f"：{reason}" if reason else ""
        super().__init__(f"chunk {chunk_index} 提炼失败（已重试 {_MAP_MAX_ATTEMPTS - 1} 次）{suffix}")


def chunk_text(text: str, chunk_size: int) -> list[TextChunk]:
    """Split into ~chunk_size windows, snapping each cut point forward to the next
    newline so a chunk never ends mid-paragraph. Chunks are numbered from 0."""
    if not text:
        return []
    chunks: list[TextChunk] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            newline = text.find("\n", end)
            if newline != -1:
                end = newline + 1
        chunks.append(TextChunk(index=len(chunks), text=text[start:end]))
        start = end
    return chunks


async def map_chunk(chunk: TextChunk, *, llm, context: str = "") -> dict:
    from langchain_core.messages import HumanMessage, SystemMessage

    system_prompt = _MAP_SYSTEM_PROMPT
    if context:
        system_prompt += _CONTEXT_PREAMBLE + context

    last_exc: BaseException | None = None
    for attempt in range(_MAP_MAX_ATTEMPTS):
        try:
            resp = await llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=chunk.text),
            ])
            content = resp.content if hasattr(resp, "content") else str(resp)
            parsed = parse_embed_json(content if isinstance(content, str) else str(content))
            if parsed:
                obj = parsed[0]
                obj.setdefault("world", [])
                obj.setdefault("characters", [])
                obj.setdefault("plot", [])
                return obj
            last_exc = ValueError("empty/unparseable JSON")
        except RATE_LIMIT_ERRORS as exc:
            # Shared upstream pool saturated by other tenants -- an instant retry (the plain
            # `except Exception` path below) almost always re-hits the same 429, so this one
            # gets its own longer backoff before the next attempt.
            last_exc = exc
            if attempt < _MAP_MAX_ATTEMPTS - 1:
                await asyncio.sleep(RATE_LIMIT_BACKOFF_S[min(attempt, len(RATE_LIMIT_BACKOFF_S) - 1)])
        except Exception as exc:  # noqa: BLE001 -- retried below; final failure raises ChunkMapError
            last_exc = exc
    raise ChunkMapError(chunk.index, reason=str(last_exc)) from last_exc


def _render_context(accumulated: dict, pending: list[dict]) -> str:
    combined = {
        "world": [*accumulated.get("world", []), *(w for p in pending for w in p.get("world", []))],
        "characters": [
            *accumulated.get("characters", []),
            *(c for p in pending for c in p.get("characters", [])),
        ],
        "plot": [*accumulated.get("plot", []), *(pt for p in pending for pt in p.get("plot", []))],
    }
    if not combined["world"] and not combined["characters"] and not combined["plot"]:
        return ""
    return json.dumps(combined, ensure_ascii=False)


async def run_map_stage(
    chunks: list[TextChunk],
    *,
    llm,
    source: str,
    compaction_interval: int,
    on_progress: Callable[[int, int, bool, str | None], Awaitable[None]] | None = None,
) -> tuple[int, list[int]]:
    """Serial for-loop (spec decision 1): each chunk's Map call is given a JSON rendering of
    every world/character/plot fact extracted so far (spec decision 2), trading wall-clock
    time for cross-chunk entity/plot continuity -- a prior fully-parallel Map stage had zero
    visibility between chunks, causing duplicate/renamed characters and disjointed plot
    points. Every `compaction_interval` chunks -- and always after the final chunk -- folds
    the raw results collected since the last fold into `accumulated` via reduce_chunks (spec
    decision 3/5) and persists the result to RAG via replace_for_source_async (spec decision
    6/7).

    The RAG write does not block this loop: each compaction's write is dispatched via
    `asyncio.create_task` and the loop moves straight on to the next chunk's Map call. Writes
    for this call's `source` are serialized by a lock local to this call (never by awaiting
    the loop) because replace_for_source_async replaces the *entire* RAG state for `source` on
    every call -- if two writes for the same source landed out of order, the stale one would
    delete facts the newer one just wrote. All dispatched writes are awaited via
    `asyncio.gather` before this function returns, so callers can still rely on "returned means
    RAG is up to date for this source"; a write failure therefore only surfaces once every
    chunk has been mapped, not as soon as it happens. See
    docs/superpowers/specs/2026-07-22-novel-import-rag-write-concurrency-design.md."""
    total = len(chunks)
    interval = max(1, compaction_interval)
    accumulated: dict = {"world": [], "characters": [], "plot": []}
    pending: list[dict] = []
    failed: list[int] = []
    completed = 0
    written = 0
    write_lock = asyncio.Lock()
    pending_writes: list[asyncio.Task[int]] = []
    character_mentions: dict[str, int] = {}

    async def _write(fine_chunks: list[ResearchChunk]) -> int:
        async with write_lock:
            return await get_research_repo().replace_for_source_async(source, fine_chunks)

    for chunk in chunks:
        context = _render_context(accumulated, pending)
        try:
            result = await map_chunk(chunk, llm=llm, context=context)
            for c in result.get("characters", []):
                name = (c.get("name") or "").strip()
                if name:
                    character_mentions[name] = character_mentions.get(name, 0) + 1
            pending.append(result)
            ok, error = True, None
        except ChunkMapError as exc:
            failed.append(chunk.index)
            ok, error = False, str(exc)
            # source (filename) + reason logged here because the caller's return value only
            # carries failed *counts*, and read_attachment_image doesn't even wire on_progress
            # (see attachment_tool.py) -- without this, a failed chunk's actual cause (e.g. a
            # rate limit that outlasted the retry backoff) was silently unrecoverable.
            logger.warning("[novel-import] chunk {} of {!r} failed: {}", chunk.index, source, exc)
        completed += 1
        if on_progress is not None:
            await on_progress(completed, total, ok, error)

        if pending and (completed % interval == 0 or completed == total):
            accumulated = await reduce_chunks([accumulated, *pending], llm=llm)
            pending = []
            fine_chunks = split_fine_grained(accumulated, source=source, character_mentions=character_mentions)
            written = len(fine_chunks)
            pending_writes.append(asyncio.create_task(_write(fine_chunks)))

    if pending_writes:
        await asyncio.gather(*pending_writes)

    return written, failed


async def reduce_chunks(chunk_results: list[dict], *, llm) -> dict:
    from langchain_core.messages import HumanMessage, SystemMessage

    payload = json.dumps(chunk_results, ensure_ascii=False)
    resp = await llm.ainvoke([
        SystemMessage(content=_REDUCE_SYSTEM_PROMPT),
        HumanMessage(content=payload),
    ])
    content = resp.content if hasattr(resp, "content") else str(resp)
    parsed = parse_embed_json(content if isinstance(content, str) else str(content))
    if not parsed:
        return {"world": [], "characters": [], "plot": []}
    obj = parsed[0]
    obj.setdefault("world", [])
    obj.setdefault("characters", [])
    obj.setdefault("plot", [])
    return obj


def split_fine_grained(
    merged: dict, *, source: str, character_mentions: dict[str, int] | None = None,
) -> list[ResearchChunk]:
    """Fine-grained RAG chunks from a compacted snapshot -- one per world fact / character /
    plot point (spec decision: granularity unchanged from the 2026-07-16 design).

    character_mentions (raw per-chunk occurrence counts collected during the map stage, see
    run_map_stage) is a best-effort proxy for how prominent a character is in the source --
    reduce_chunks may have renamed/merged the character's canonical name, in which case the
    exact-string lookup below misses and mention_count silently defaults to 1. That's an
    accepted approximation (see design doc), not a bug."""
    chunks: list[ResearchChunk] = []
    for fact in merged.get("world", []):
        if fact.strip():
            chunks.append(ResearchChunk(text=fact, topic="世界观", source=source, category=ResearchCategory.WORLD))
    for char in merged.get("characters", []):
        name = (char.get("name") or "").strip()
        if not name:
            continue
        text = f"性格：{char.get('personality') or '（无）'}\n口癖：{char.get('verbal_tic') or '（无）'}"
        mention_count = (character_mentions or {}).get(name, 1)
        chunks.append(ResearchChunk(
            text=text, topic=name, source=source, category=ResearchCategory.CHARACTER,
            mention_count=mention_count,
        ))
    for point in merged.get("plot", []):
        if point.strip():
            chunks.append(ResearchChunk(text=point, topic="剧情", source=source, category=ResearchCategory.PLOT))
    return chunks


async def run_distillation_from_chunks(
    chunks: list[TextChunk],
    *,
    source: str,
    compaction_interval: int,
    llm,
    on_progress: Callable[[int, int, bool, str | None], Awaitable[None]] | None = None,
) -> tuple[int, list[int]]:
    return await run_map_stage(
        chunks, llm=llm, source=source, compaction_interval=compaction_interval, on_progress=on_progress,
    )


async def run_novel_import_pipeline(
    text: str,
    *,
    source: str,
    chunk_size: int,
    compaction_interval: int,
    llm,
    on_progress: Callable[[int, int, bool, str | None], Awaitable[None]] | None = None,
    on_start: Callable[[int], Awaitable[None]] | None = None,
) -> tuple[int, list[int]]:
    chunks = chunk_text(text, chunk_size)
    if on_start is not None:
        await on_start(len(chunks))
    return await run_distillation_from_chunks(
        chunks, source=source, compaction_interval=compaction_interval, llm=llm, on_progress=on_progress,
    )
