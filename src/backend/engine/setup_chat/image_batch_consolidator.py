"""Cross-image description consolidation between vision recognition and Map-Reduce distillation.

Per TODO.md Image Description Consolidation (2026-08-04): entity alignment across pages
(e.g. binding 'the burly swordsman' on pages 1-10 to the name 'Karl' on page 11) and
consistency audit before text_recognition distillation. Vision batches carry the last
`overlap` images from the previous batch as visual context when recognizing the next batch."""
from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from llm.retry import RATE_LIMIT_ERRORS
from loguru import logger

_VISION_SYSTEM_PROMPT = (
    "你是漫画/图片内容识别助手。仔细观察图片，用一段连贯的文字描述："
    "画面场景与环境、出现的角色外貌（重点描述服饰、样貌、体型）与动作、可读到的台词/文字内容、正在发生的剧情。"
    "尽量详尽但不要编造图片里没有的内容。"
)

_VISION_WITH_CONTEXT_SUFFIX = (
    "\n\n若消息中包含多张图片，前面的图片仅供理解跨页上下文，"
    "请重点描述**最后一张**图片的内容；可引用前文已出现但未命名的角色，"
    "但不要把前面图片的场景误当作当前图片的主场景。"
)

_VISION_BATCH_SYSTEM_PROMPT = (
    "你是漫画/图片内容识别助手。你会收到两组图片：一组是「上下文页」，仅用于理解跨页背景，"
    "不需要为它们单独输出描述；另一组是「新页」，需要逐张仔细观察并输出描述。\n\n"
    "对每一张新页，用一段连贯的文字描述：画面场景与环境、出现的角色外貌"
    "（重点描述服饰、样貌、体型）与动作、可读到的台词/文字内容、正在发生的剧情。"
    "尽量详尽但不要编造图片里没有的内容。可以参考上下文页理解背景，但不要把上下文页的场景"
    "误当作某一新页的内容。\n\n"
    "按顺序对每一张新页各自输出一个块，格式：\n"
    "=== 第N页 (filename) ===\n"
    "（该页描述正文）\n\n"
    "不要输出 JSON 或 markdown 代码围栏，也不要为上下文页单独输出块。"
)

_CONSOLIDATION_SYSTEM_PROMPT = (
    "你是漫画/多图内容整合与人设审查助手。输入是按页序排列的单页视觉描述，"
    "可能存在同一角色在不同页使用不同称呼、前后矛盾或身份漂移。\n\n"
    "任务：\n"
    "1. **跨页实体对齐**：将无名角色描述与后续出现的名字绑定为同一实体"
    "（例如前页的「魁梧剑士」= 后页出现的「卡尔」）\n"
    "2. **逻辑一致性审查**：消除前后矛盾，统一角色称谓，修正明显冲突\n"
    "3. **维护角色名册**：结合下方可能提供的「已知跨批角色名册」，产出一份更新后的完整名册——"
    "包含已具名角色（若曾用别的称呼，标注「曾用称呼：xxx」）与尚未具名但值得追踪的角色"
    "（用占位符如「配角A」代替姓名，附外貌/身份关键词），供后续批次继续沿用\n\n"
    "输出：\n"
    "按页序输出整合后的描述。每页以「=== 第N页 (filename) ===」开头，"
    "紧跟该页整合后的正文；若该页有角色台词/对话，在正文下方另起一行，以「角色台词（角色A：台词A；角色B：台词B）」的格式列出；"
    "若该页有对角色特征（服饰、样貌、体型等）的具体描写，另起一行，以「角色特征（角色A：特征描述）」的格式列出；"
    "所有页输出完后，另起一段以「=== 角色名册 ===」开头，逐行列出更新后的完整角色名册"
    "（每行格式：姓名或占位符（曾用称呼：xxx，如有）：外貌/身份关键词）；"
    "不要输出 JSON 或 markdown 代码围栏。"
)

_ROSTER_MARKER = "=== 角色名册 ==="


@dataclass(frozen=True)
class ImagePageDescription:
    index: int
    filename: str
    text: str


@dataclass(frozen=True)
class ImageBatchWindow:
    """One vision/consolidation window over a sorted image list."""

    batch_index: int
    new_start: int
    new_end: int
    overlap_start: int


def iter_batch_windows(
    total: int, *, batch_size: int, overlap: int,
) -> list[ImageBatchWindow]:
    """Split `total` pages into sequential batches. Batch 0 covers [0, batch_size);
    later batches cover the next `batch_size` new pages each, with `overlap` pages
    from the previous batch included as context (not re-counted as new pages)."""
    if total <= 0:
        return []
    batch_size = max(1, batch_size)
    overlap = max(0, min(overlap, batch_size - 1))
    windows: list[ImageBatchWindow] = []
    new_start = 0
    batch_index = 0
    while new_start < total:
        new_end = min(new_start + batch_size, total)
        overlap_start = max(0, new_start - overlap) if batch_index > 0 else new_start
        windows.append(ImageBatchWindow(
            batch_index=batch_index, new_start=new_start, new_end=new_end,
            overlap_start=overlap_start,
        ))
        if new_end >= total:
            break
        new_start = new_end
        batch_index += 1
    return windows


def _format_consolidation_input(pages: list[ImagePageDescription]) -> str:
    blocks = [
        f"=== 第{page.index + 1}页 ({page.filename}) ===\n{page.text.strip()}"
        for page in pages
        if page.text.strip()
    ]
    return "\n\n".join(blocks)


def _parse_page_markers(text: str) -> dict[tuple[int, str], str]:
    """Split text into blocks keyed by (page_num, filename) from
    '=== 第N页 (filename) ===' headers. Returns an empty dict if no marker is found."""
    by_key: dict[tuple[int, str], str] = {}
    current_key: tuple[int, str] | None = None
    current_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("=== 第") and "页 (" in line and line.rstrip().endswith(") ==="):
            if current_key is not None:
                by_key[current_key] = "\n".join(current_lines).strip()
            header = line.removeprefix("=== ").removesuffix(" ===")
            page_part, filename_part = header.split("页 (", 1)
            page_num = int(page_part.removeprefix("第"))
            filename = filename_part.removesuffix(")")
            current_key = (page_num, filename)
            current_lines = []
        elif current_key is not None:
            current_lines.append(line)
    if current_key is not None:
        by_key[current_key] = "\n".join(current_lines).strip()
    return by_key


def _parse_consolidated_pages(raw: str, pages: list[ImagePageDescription]) -> list[ImagePageDescription]:
    """Best-effort parse of per-page markers; falls back to one block if markers missing."""
    text = raw.strip()
    if not text:
        return []
    by_key = _parse_page_markers(text)

    if not by_key:
        joined = text
        return [
            ImagePageDescription(index=page.index, filename=page.filename, text=joined)
            for page in pages
        ]

    out: list[ImagePageDescription] = []
    for page in pages:
        body = by_key.get((page.index + 1, page.filename), "").strip()
        if body:
            out.append(ImagePageDescription(index=page.index, filename=page.filename, text=body))
    return out


def _split_roster_block(raw: str) -> tuple[str, str]:
    """Split consolidation output into (per-page body, roster text). Returns an empty
    roster if the marker is absent -- caller falls back to the incoming roster."""
    text = raw.strip()
    marker_idx = text.find(_ROSTER_MARKER)
    if marker_idx == -1:
        return text, ""
    body = text[:marker_idx].strip()
    roster = text[marker_idx + len(_ROSTER_MARKER):].strip()
    return body, roster


async def recognize_image(
    filename: str,
    raw: bytes,
    *,
    vision_llm,
    context_images: list[tuple[str, bytes]] | None = None,
) -> str:
    """Run vision recognition on one image, optionally with prior-page images as context."""
    from langchain_core.messages import HumanMessage, SystemMessage

    system = _VISION_SYSTEM_PROMPT
    if context_images:
        system += _VISION_WITH_CONTEXT_SUFFIX

    content: list[str | dict[str, object]] = []
    for ctx_name, ctx_raw in context_images or []:
        b64 = base64.b64encode(ctx_raw).decode("ascii")
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })
        content.append({"type": "text", "text": f"[上下文页: {ctx_name}]"})
    b64 = base64.b64encode(raw).decode("ascii")
    content.append({
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
    })
    content.append({"type": "text", "text": f"[当前页: {filename}]"})

    resp = await vision_llm.ainvoke([
        SystemMessage(content=system),
        HumanMessage(content=content),
    ])
    description = resp.content if isinstance(resp.content, str) else str(resp.content)
    return description.strip()


def _parse_vision_batch_pages(
    raw: str, new_images: list[tuple[str, bytes]], *, new_start_index: int,
) -> list[ImagePageDescription]:
    """Split a batch vision response into per-page descriptions, one entry per new
    image (never dropped, so callers can detect per-page failure). Falls back to
    assigning the entire raw response to every page if no '=== 第N页 ===' markers
    are found (mirrors _parse_consolidated_pages' fallback)."""
    text = raw.strip()
    page_keys = [
        (new_start_index + offset, filename)
        for offset, (filename, _raw) in enumerate(new_images)
    ]
    if not text:
        return [ImagePageDescription(index=idx, filename=filename, text="") for idx, filename in page_keys]

    by_key = _parse_page_markers(text)
    if not by_key:
        return [ImagePageDescription(index=idx, filename=filename, text=text) for idx, filename in page_keys]

    return [
        ImagePageDescription(index=idx, filename=filename, text=by_key.get((idx + 1, filename), "").strip())
        for idx, filename in page_keys
    ]


async def recognize_image_batch(
    new_images: list[tuple[str, bytes]],
    *,
    vision_llm,
    new_start_index: int,
    context_images: list[tuple[str, bytes]] | None = None,
) -> list[ImagePageDescription]:
    """Recognize a batch of pages in one vision call, with optional overlap images from
    the previous batch as cross-batch visual context. new_images[i] is assigned page
    index new_start_index + i, matching the page numbering used throughout this module
    (page_num = index + 1)."""
    from langchain_core.messages import HumanMessage, SystemMessage

    content: list[str | dict[str, object]] = []
    for ctx_name, ctx_raw in context_images or []:
        b64 = base64.b64encode(ctx_raw).decode("ascii")
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })
        content.append({"type": "text", "text": f"[上下文页: {ctx_name}]"})
    for offset, (filename, raw) in enumerate(new_images):
        page_num = new_start_index + offset + 1
        b64 = base64.b64encode(raw).decode("ascii")
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })
        content.append({"type": "text", "text": f"[第{page_num}页: {filename}]"})

    resp = await vision_llm.ainvoke([
        SystemMessage(content=_VISION_BATCH_SYSTEM_PROMPT),
        HumanMessage(content=content),
    ])
    raw_text = resp.content if isinstance(resp.content, str) else str(resp.content)
    return _parse_vision_batch_pages(raw_text, new_images, new_start_index=new_start_index)


async def consolidate_descriptions(
    pages: list[ImagePageDescription],
    *,
    llm,
    prior_entity_context: str = "",
) -> tuple[list[ImagePageDescription], str]:
    """Entity alignment + consistency audit over a batch of per-page descriptions.

    Returns (aligned pages, updated rolling character roster). The roster is carried
    forward unchanged (not cleared) whenever this batch's response has no roster block,
    so a single malformed response doesn't erase everything learned so far."""
    if not pages:
        return [], prior_entity_context
    if len(pages) == 1 and not prior_entity_context.strip():
        return pages, prior_entity_context

    from langchain_core.messages import HumanMessage, SystemMessage

    system = _CONSOLIDATION_SYSTEM_PROMPT
    if prior_entity_context.strip():
        system += (
            "\n\n已知跨批角色名册（前一批产出，供延续绑定，勿与当前输入矛盾；"
            "请在此基础上补充本批新增/更新的角色，输出完整名册）：\n"
            + prior_entity_context.strip()
        )
    user = _format_consolidation_input(pages)
    resp = await llm.ainvoke([
        SystemMessage(content=system),
        HumanMessage(content=user),
    ])
    content = resp.content if isinstance(resp.content, str) else str(resp.content)
    body, roster = _split_roster_block(content)
    parsed = _parse_consolidated_pages(body, pages)
    if not parsed:
        logger.warning("[image_batch_consolidator] unparseable consolidation output, using raw input")
        parsed = pages
    return parsed, (roster if roster else prior_entity_context)


async def run_vision_and_consolidation_pipeline(
    images: list[tuple[str, bytes]],
    *,
    vision_llm,
    consolidator_llm,
    batch_size: int,
    overlap: int,
    on_image_done: Callable[[int, int, bool, str | None], Awaitable[None]] | None = None,
) -> tuple[str, list[int], list[ImagePageDescription]]:
    """Stage 1 (batched vision) + stage 1.5 (consolidation with a rolling character
    roster) for a sorted image list.

    Returns (consolidated_plain_text, failed_page_indices, ordered_page_descriptions).
    The plain text is prefixed with the final character roster (if any) so that
    novel_import.py's text distillation inherits alias bindings (e.g. "Karl" = the
    earlier-anonymous "burly swordsman") even for pages the roster wasn't able to
    retroactively rewrite."""
    if not images:
        return "", [], []

    windows = iter_batch_windows(len(images), batch_size=batch_size, overlap=overlap)
    consolidated_by_index: dict[int, ImagePageDescription] = {}
    known_roster = ""
    failed: list[int] = []

    for window in windows:
        overlap_images = images[window.overlap_start:window.new_start]
        new_images = images[window.new_start:window.new_end]

        try:
            raw_descriptions = await recognize_image_batch(
                new_images, vision_llm=vision_llm, new_start_index=window.new_start,
                context_images=overlap_images if overlap_images else None,
            )
        except RATE_LIMIT_ERRORS:
            for idx in range(window.new_start, window.new_end):
                failed.append(idx)
                if on_image_done is not None:
                    await on_image_done(idx, len(images), False, "视觉模型服务商临时限流")
            continue

        batch_pages: list[ImagePageDescription] = []
        for page in raw_descriptions:
            ok = bool(page.text.strip())
            if not ok:
                failed.append(page.index)
            if on_image_done is not None:
                await on_image_done(
                    page.index, len(images), ok, None if ok else "视觉模型未返回有效描述",
                )
            if ok:
                batch_pages.append(page)

        # Overlap pages were already consolidated in the previous batch; reuse that
        # cleaned text (rather than re-recognizing them) as extra grounding alongside
        # this batch's new pages -- only new-page results get committed below.
        overlap_pages = [
            consolidated_by_index[idx]
            for idx in range(window.overlap_start, window.new_start)
            if idx in consolidated_by_index
        ]
        all_pages_for_consolidation = overlap_pages + batch_pages
        if not all_pages_for_consolidation:
            continue

        try:
            consolidated, known_roster = await consolidate_descriptions(
                all_pages_for_consolidation, llm=consolidator_llm, prior_entity_context=known_roster,
            )
        except RATE_LIMIT_ERRORS:
            logger.warning("[image_batch_consolidator] consolidation rate-limited, using raw descriptions")
            consolidated = all_pages_for_consolidation
        except Exception as exc:  # noqa: BLE001 -- fall back to raw vision text rather than abort import
            logger.warning("[image_batch_consolidator] consolidation failed: {}", exc)
            consolidated = all_pages_for_consolidation

        for page in consolidated:
            if page.index >= window.new_start:
                consolidated_by_index[page.index] = page

    ordered = [consolidated_by_index[i] for i in sorted(consolidated_by_index)]
    if not ordered:
        return "", failed, []
    body = "\n\n".join(
        f"=== 第{page.index + 1}页 ({page.filename}) ===\n{page.text.strip()}"
        for page in ordered
    )
    plain = f"[人物名册]\n{known_roster.strip()}\n\n{body}" if known_roster.strip() else body
    return plain, failed, ordered
