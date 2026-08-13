"""Rebuild style-source text chunks from on-disk attachments after process restart.

style_source_cache is in-process only; this module rehydrates it from persisted
text attachment bytes or persisted per-image vision descriptions (natural filename
order), matching the import pipeline's concatenation shape without re-calling vision."""
from __future__ import annotations

from engine.setup_chat.attachment_persistence import (
    list_persisted_attachments,
    load_image_description,
    load_persisted_attachment_bytes,
)
from engine.setup_chat.novel_import import TextChunk, chunk_text


def load_style_source_text_from_persisted(novel_id: str) -> str | None:
    """Return concatenated import source text from disk, or None if nothing usable.

    Prefers text attachments (real novel prose) over image vision descriptions when
    both exist — better material for verbatim style excerpt extraction."""
    metas = list_persisted_attachments(novel_id)
    text_metas = [m for m in metas if m.kind == "text"]
    if text_metas:
        parts: list[str] = []
        for meta in text_metas:
            loaded = load_persisted_attachment_bytes(novel_id, meta.attachment_id)
            if loaded is None:
                continue
            _filename, raw = loaded
            text = raw.decode("utf-8", errors="replace").strip()
            if text:
                parts.append(text)
        if parts:
            return "\n\n".join(parts)

    image_metas = [m for m in metas if m.kind == "image" and m.has_description]
    if image_metas:
        parts = []
        for page_num, meta in enumerate(image_metas, start=1):
            description = load_image_description(novel_id, meta.attachment_id)
            if description:
                parts.append(f"=== 第{page_num}页 ({meta.filename}) ===\n{description.strip()}")
        if parts:
            return "\n\n".join(parts)

    return None


def rebuild_style_source_chunks_from_persisted(
    novel_id: str, *, chunk_size: int,
) -> list[TextChunk] | None:
    """Re-chunk persisted import source for build_prose_style_from_import."""
    text = load_style_source_text_from_persisted(novel_id)
    if text is None:
        return None
    chunks = chunk_text(text, chunk_size)
    return chunks or None
