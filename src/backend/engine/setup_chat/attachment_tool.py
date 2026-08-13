"""read_attachment tool: reads an uploaded text attachment once and returns an
LLM-distilled summary (world/cast/plot-shaped highlights) instead of the raw text.
The summary is also upserted into the same research_repo recall_research already
reads (per web_search's precedent) so later setup-chat turns building world/cast/
plot can ground details in what the imported novel actually said, instead of the
summary only living in this one ephemeral chat turn.

The pre-cut chunks are also cached (engine/setup_chat/style_source_cache.py) so a later,
agent-initiated call to build_prose_style_from_import can run the style-extraction branch
(engine/setup_chat/prose_style_extraction.py) without needing the raw text again. This used
to be a parallel branch run unconditionally inside read_attachment; it is now decoupled so
importing a novel doesn't always trigger style generation -- the agent decides when to call
build_prose_style_from_import (normally after asking the user via present_choices). See
docs/superpowers/specs/2026-07-23-novel-import-prose-style-decouple-design.md.

Per docs/superpowers/specs/2026-07-07-setup-chat-file-import-design.md §5: the inner
extraction call is a separate, stateless, no-history LLM invocation (not the main
conversational agent) -- this keeps the persisted conversation history small, and mirrors
the "deterministic, single-source retrieval doesn't need a ReAct sub-agent" lesson already
applied to recall_research/web_search (see engine/setup_chat/research.py)."""
from __future__ import annotations

from langchain_core.tools import tool

from engine.setup_chat.attachments import (
    pop_attachment_bytes,
    pop_attachment_images_batch,
    pop_attachment_text,
)
from engine.setup_chat.tool_args import ReadAttachmentArgs, ReadAttachmentBatchArgs


@tool(args_schema=ReadAttachmentArgs)
async def read_attachment(attachment_id: str) -> str:
    """读取一个已上传的文本附件（txt/md），分片提炼世界观/角色性格口癖/剧情要点并写入
    检索库，返回摘要；只能读取一次，读取后附件即从内存丢弃。"""
    from api.routes import _hub_instance
    from llm.factory import get_cloud_llm
    from utils.config import get_config
    from utils.paths import active_novel_id

    from engine.setup_chat import style_source_cache
    from engine.setup_chat.novel_import import chunk_text, run_distillation_from_chunks

    popped = pop_attachment_text(attachment_id)
    if popped is None:
        return "附件不存在或已被读取，请重新上传。"
    filename, text = popped
    cfg = get_config()["novel_import"]
    llm = get_cloud_llm()
    from engine.modes.author_loop_skill_prefs import bind_node_llm, load_dialogue_prefs

    llm = bind_node_llm(llm, "text_recognition", load_dialogue_prefs()["import_llm_params"])
    hub = _hub_instance()
    novel_id = active_novel_id()

    chunks = chunk_text(text, cfg["chunk_size"])
    style_source_cache.store_chunks(novel_id, chunks)
    await hub.note_novel_import_text_start(novel_id, len(chunks))

    async def _on_progress(completed: int, total: int, ok: bool, error: str | None) -> None:
        await hub.note_novel_import_text_progress(
            novel_id, index=completed, total=total, ok=ok, error=error,
        )

    n_chunks, failed = await run_distillation_from_chunks(
        chunks, source=filename, compaction_interval=cfg["compaction_interval"], llm=llm,
        on_progress=_on_progress,
    )
    await hub.note_novel_import_text_done(novel_id)

    failed_note = f"（{len(failed)} 个分片提炼失败已跳过）" if failed else ""
    return (
        f"[附件 {filename} 提炼完成]已生成 {n_chunks} 条检索片段{failed_note}，"
        f"可用 recall_research 做语义查询；如需穷举全部角色/世界观/剧情条目，"
        f"改用 list_characters / get_character / get_world_facts / get_plot_points。"
        f"可用 present_choices 询问用户是否要基于这部小说原文生成专属文风预设；"
        f"用户确认后调用 build_prose_style_from_import。"
    )


@tool
async def build_prose_style_from_import() -> str:
    """基于当前小说导入源文本抽取环境/台词/动作/亲密描写/心理五类真实片段并合成专属
    文风预设，落盘后自动设为当前小说的激活文风（保留原有 custom_addendum）。

    导入源优先读进程内缓存；缓存因重启清空时，会从落盘文本附件或已识别的图片视觉描述
    自动重建分片（无需重新上传或调视觉模型）。建议先用 present_choices 问过用户。"""
    from api.services.novels import get_novel_name, get_prose_style, set_prose_style
    from utils.config import get_config
    from utils.paths import active_novel_id

    from engine.setup_chat import style_source_cache
    from engine.setup_chat.prose_style_extraction import run_style_extraction_pipeline
    from engine.setup_chat.style_source_rebuild import rebuild_style_source_chunks_from_persisted

    novel_id = active_novel_id()
    cfg = get_config()["novel_import"]
    chunks = style_source_cache.get_chunks(novel_id)
    if chunks is None:
        chunks = rebuild_style_source_chunks_from_persisted(
            novel_id, chunk_size=cfg["chunk_size"],
        )
        if chunks is not None:
            style_source_cache.store_chunks(novel_id, chunks)

    if chunks is None:
        return (
            "没有可用的导入原文，请先用 read_attachment 或 read_attachment_image(s) "
            "导入附件并完成识别。"
        )

    try:
        style_preset = await run_style_extraction_pipeline(
            chunks,
            novel_id=novel_id,
            novel_title=get_novel_name(novel_id),
            concurrency=cfg["concurrency"],
        )
    except Exception as exc:  # noqa: BLE001 -- agent-initiated call, surface failure instead of swallowing it
        return f"文风抽取失败：{exc}"

    if style_preset is None:
        return "未能从原文抽出足够素材，未生成文风预设。"

    current = get_prose_style(novel_id)
    set_prose_style(novel_id, preset=style_preset["id"], custom_addendum=current["custom_addendum"])
    return f"已生成并启用小说专属文风预设「{style_preset['name']}」。"


async def _distill_image_text(
    description: str,
    *,
    source: str,
    text_llm,
    track_turn_progress: bool,
    hub,
) -> tuple[int, list[int]]:
    """Stage 2: chunk + Map-Reduce distillation for consolidated/plain image text."""
    from utils.config import get_config
    from utils.paths import active_novel_id

    from engine.setup_chat import style_source_cache
    from engine.setup_chat.novel_import import chunk_text, run_distillation_from_chunks

    cfg = get_config()["novel_import"]
    novel_id = active_novel_id()
    chunks = chunk_text(description, cfg["chunk_size"])
    style_source_cache.store_chunks(novel_id, chunks)
    n_chunks, failed = await run_distillation_from_chunks(
        chunks, source=source, compaction_interval=cfg["compaction_interval"], llm=text_llm,
    )
    if track_turn_progress:
        await hub.advance_image_recognition_progress(ok=not failed)
    return n_chunks, failed


def _format_image_import_result(
    *,
    label: str,
    source: str,
    n_chunks: int,
    failed_distill: list[int],
    failed_pages: list[int],
    page_count: int,
) -> str:
    notes: list[str] = []
    if failed_distill:
        notes.append(f"{len(failed_distill)} 个分片提炼失败已跳过")
    if failed_pages:
        notes.append(f"{len(failed_pages)}/{page_count} 页视觉识别失败已跳过")
    failed_note = f"（{'；'.join(notes)}）" if notes else ""
    return (
        f"[{label} {source} 识别完成]已生成 {n_chunks} 条检索片段{failed_note}，"
        f"可用 recall_research 做语义查询；如需穷举全部角色/世界观/剧情条目，"
        f"改用 list_characters / get_character / get_world_facts / get_plot_points。"
    )


def _persist_image_descriptions(
    novel_id: str,
    images: list[tuple[str, str, bytes]],
    *,
    single_description: str | None = None,
    pages: list | None = None,
) -> None:
    """Save 1:1 attachment_id -> vision description sidecars after recognition."""
    from engine.setup_chat.attachment_persistence import persist_image_description

    if single_description is not None and len(images) == 1:
        persist_image_description(novel_id, images[0][0], single_description)
        return
    if not pages:
        return
    by_index = {page.index: page.text.strip() for page in pages if page.text.strip()}
    for idx, (attachment_id, _filename, _raw) in enumerate(images):
        text = by_index.get(idx)
        if text:
            persist_image_description(novel_id, attachment_id, text)


async def _run_image_import_pipeline(
    images: list[tuple[str, str, bytes]],
    *,
    source: str,
    track_turn_progress: bool,
) -> str:
    from api.routes import _hub_instance
    from llm.factory import get_cloud_llm
    from llm.retry import RATE_LIMIT_ERRORS
    from utils.config import get_config
    from utils.paths import active_novel_id

    from engine.modes.author_loop_skill_prefs import (
        bind_node_llm,
        load_dialogue_prefs,
        resolve_image_recognition_params,
    )
    from engine.setup_chat.image_batch_consolidator import (
        recognize_image,
        run_vision_and_consolidation_pipeline,
    )

    hub = _hub_instance()
    novel_id = active_novel_id()
    import_params = load_dialogue_prefs()["import_llm_params"]
    image_params = resolve_image_recognition_params(import_params)
    image_payloads = [(filename, raw) for _aid, filename, raw in images]
    if not image_params.get("model_ref"):
        return "图片识别能力节点尚未配置视觉模型，请先去「对话」tab 选中「图片识别」节点绑定一个支持图片输入的模型。"

    if track_turn_progress:
        await hub.begin_image_recognition_progress(len(images))

    base_llm = get_cloud_llm()
    import_params_with_image = {**import_params, "image_recognition": image_params}
    image_llm = bind_node_llm(base_llm, "image_recognition", import_params_with_image)
    vision_llm = consolidator_llm = image_llm
    text_llm = bind_node_llm(base_llm, "text_recognition", import_params)
    cfg = get_config()["novel_import"]
    batch_size = int(cfg.get("image_batch_size", 10))
    overlap = int(cfg.get("image_batch_overlap", 2))

    async def _on_image_done(index: int, total: int, ok: bool, error: str | None) -> None:
        if track_turn_progress:
            await hub.advance_image_recognition_progress(ok=ok, error=error)

    if len(images) == 1:
        _attachment_id, filename, raw = images[0]
        try:
            description = await recognize_image(filename, raw, vision_llm=vision_llm)
        except RATE_LIMIT_ERRORS:
            if track_turn_progress:
                await hub.advance_image_recognition_progress(ok=False, error="视觉模型服务商临时限流")
            return f"[附件 {filename}] 视觉模型服务商临时限流（已自动重试仍失败），请稍后重新上传这张图片重试。"
        if not description:
            if track_turn_progress:
                await hub.advance_image_recognition_progress(ok=False, error="视觉模型未返回有效描述")
            return f"[附件 {filename}] 视觉模型未返回有效描述，未生成设定。"
        consolidated_text = description
        failed_pages: list[int] = []
        _persist_image_descriptions(novel_id, images, single_description=description)
    else:
        consolidated_text, failed_pages, ordered_pages = await run_vision_and_consolidation_pipeline(
            image_payloads,
            vision_llm=vision_llm,
            consolidator_llm=consolidator_llm,
            batch_size=batch_size,
            overlap=overlap,
            on_image_done=_on_image_done if track_turn_progress else None,
        )
        if not consolidated_text.strip():
            return f"[图片附件 {source}] 全部 {len(images)} 页视觉识别失败，未生成设定。"
        _persist_image_descriptions(novel_id, images, pages=ordered_pages)

    n_chunks, failed_distill = await _distill_image_text(
        consolidated_text,
        source=source,
        text_llm=text_llm,
        track_turn_progress=track_turn_progress and len(images) == 1,
        hub=hub,
    )
    return _format_image_import_result(
        label="图片附件" if len(images) == 1 else f"图片批次({len(images)}页)",
        source=source,
        n_chunks=n_chunks,
        failed_distill=failed_distill,
        failed_pages=failed_pages,
        page_count=len(images),
    )


async def _recognize_image_bytes(
    attachment_id: str,
    filename: str,
    raw: bytes,
    *,
    track_turn_progress: bool,
) -> str:
    return await _run_image_import_pipeline(
        [(attachment_id, filename, raw)],
        source=filename,
        track_turn_progress=track_turn_progress,
    )


@tool
async def list_persisted_attachments() -> str:
    """列出当前小说已落盘保存的全部附件（图片/文档），含 attachment_id 与 filename，
    供后续二次调阅；图片若已有视觉描述会标注 described=yes。按文件名自然排序。"""
    from utils.paths import active_novel_id

    from engine.setup_chat.attachment_persistence import list_persisted_attachments as _list

    metas = _list(active_novel_id())
    if not metas:
        return "当前小说尚无已落盘附件。"
    lines = [
        (
            f"- id={m.attachment_id} filename={m.filename} kind={m.kind} "
            f"size={m.size_bytes}B"
            + (f" described={'yes' if m.has_description else 'no'}" if m.kind == "image" else "")
        )
        for m in metas
    ]
    return (
        "[已落盘附件，可用 read_persisted_attachment / get_image_description 按 id 二次调阅]\n"
        + "\n".join(lines)
    )


@tool(args_schema=ReadAttachmentArgs)
async def get_image_description(attachment_id: str) -> str:
    """按 attachment_id 读取已落盘的图片视觉描述（图片与描述 1:1），不调用视觉模型。
    若该图片尚未识别过，会提示先用 read_attachment_image 或 read_persisted_attachment。"""
    from utils.paths import active_novel_id

    from engine.setup_chat.attachment_persistence import (
        load_image_description,
        load_persisted_attachment_bytes,
    )
    from engine.setup_chat.attachments import IMAGE_EXTENSIONS

    novel_id = active_novel_id()
    loaded = load_persisted_attachment_bytes(novel_id, attachment_id)
    if loaded is None:
        return "附件不存在或未落盘，请先用 list_persisted_attachments 查看可用 id。"
    filename, _raw = loaded
    if not filename.lower().endswith(IMAGE_EXTENSIONS):
        return f"附件 {filename} 不是图片，请用 read_persisted_attachment 读取文本内容。"
    description = load_image_description(novel_id, attachment_id)
    if description is None:
        return (
            f"图片 {filename}（id={attachment_id}）尚无已落盘的视觉描述，"
            f"请先用 read_attachment_image 或 read_persisted_attachment 完成识别。"
        )
    return f"[图片 {filename} 视觉描述]\n{description}"


@tool(args_schema=ReadAttachmentArgs)
async def read_persisted_attachment(attachment_id: str) -> str:
    """从磁盘读取历史上传的附件。图片若已有落盘视觉描述则直接返回（不重复调视觉模型）；
    否则走视觉识别+提炼并落盘描述。文本直接返回原文内容（不重复提炼）。"""
    from utils.paths import active_novel_id

    from engine.setup_chat.attachment_persistence import (
        load_image_description,
        load_persisted_attachment_bytes,
    )
    from engine.setup_chat.attachments import IMAGE_EXTENSIONS

    novel_id = active_novel_id()
    loaded = load_persisted_attachment_bytes(novel_id, attachment_id)
    if loaded is None:
        return "附件不存在或未落盘，请先用 list_persisted_attachments 查看可用 id。"
    filename, raw = loaded
    if filename.lower().endswith(IMAGE_EXTENSIONS):
        cached = load_image_description(novel_id, attachment_id)
        if cached is not None:
            return f"[落盘附件 {filename} 视觉描述]\n{cached}"
        return await _recognize_image_bytes(
            attachment_id, filename, raw, track_turn_progress=False,
        )
    text = raw.decode("utf-8", errors="replace")
    return f"[落盘附件 {filename} 原文]\n{text}"


@tool(args_schema=ReadAttachmentArgs)
async def read_attachment_image(attachment_id: str) -> str:
    """读取一个已上传的图片附件（漫画/截图等），先用视觉模型生成文字描述，再走跟文本附件
    一样的分片提炼流程写入检索库；只能读取一次，读取后附件即从内存丢弃。调用前若"图片识别"
    能力节点未配置视觉模型，会提示先去"对话" tab 配置。"""
    popped = pop_attachment_bytes(attachment_id)
    if popped is None:
        return "附件不存在或已被读取，请重新上传。"
    filename, raw = popped
    return await _recognize_image_bytes(
        attachment_id, filename, raw, track_turn_progress=True,
    )


@tool(args_schema=ReadAttachmentBatchArgs)
async def read_attachment_images(attachment_ids: list[str]) -> str:
    """批量读取已上传的图片附件（漫画多页等），按文件名自然排序后依次视觉识别、
    跨页整合与分片提炼；第二批及以后会带上前一批最后 1-2 页作为视觉/整合上下文，
    避免同一角色被拆成两个实体。只能读取一次。"""
    popped = pop_attachment_images_batch(attachment_ids)
    if popped is None:
        return "附件不存在、已被读取、含非图片文件，或 id 列表不完整，请重新上传。"
    source = popped[0][1] if len(popped) == 1 else f"{popped[0][1]}…{popped[-1][1]}"
    return await _run_image_import_pipeline(popped, source=source, track_turn_progress=True)
