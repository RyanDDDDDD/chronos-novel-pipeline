"""Ephemeral in-memory store for setup-chat file attachments.

Per docs/superpowers/specs/2026-07-07-setup-chat-file-import-design.md §4/§7: attachments
live only in process memory, are read exactly once by read_attachment, and are never
persisted to disk or a vector index. A process restart clears everything; that is an
accepted tradeoff, not a bug. Raw bytes are kept as-is (decoding to text is deferred to
pop_attachment_text) so a future image attachment kind can reuse this same store without
a rewrite."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

ALLOWED_EXTENSIONS = (".txt", ".md", ".png", ".jpg", ".jpeg", ".webp")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


@dataclass
class _Attachment:
    filename: str
    raw: bytes


_ATTACHMENTS: dict[str, _Attachment] = {}


def store_attachment(filename: str, raw: bytes) -> str:
    """Store raw bytes under an attachment_id and return that id.

    Re-uploading the same filename replaces the prior entry (same id, fresh bytes) so
    comic page batches do not accumulate duplicate rows in the library."""
    from utils.paths import active_novel_id

    from engine.setup_chat.attachment_persistence import (
        clear_image_description,
        find_persisted_attachment_id_by_filename,
        persist_attachment,
    )

    novel_id = active_novel_id()
    existing_id = find_persisted_attachment_id_by_filename(novel_id, filename)
    attachment_id = existing_id or uuid.uuid4().hex
    if existing_id:
        from engine.setup_chat.image_upload_async import cancel_image_upload

        cancel_image_upload(attachment_id)
        clear_image_description(novel_id, attachment_id)
    _ATTACHMENTS[attachment_id] = _Attachment(filename=filename, raw=raw)
    persist_attachment(novel_id, attachment_id, filename, raw)
    return attachment_id


def store_image_attachment(filename: str, raw: bytes) -> str:
    """Preprocess image bytes locally (resize + JPEG) then store; keeps original filename."""
    from engine.setup_chat.image_preprocess import prepare_image_for_vision

    return store_attachment(filename, prepare_image_for_vision(raw))


def finalize_image_attachment(
    novel_id: str, attachment_id: str, filename: str, raw: bytes
) -> None:
    """Complete an async image upload: memory store + disk persist with a pre-assigned id."""
    _ATTACHMENTS[attachment_id] = _Attachment(filename=filename, raw=raw)
    from engine.setup_chat.attachment_persistence import persist_attachment

    persist_attachment(novel_id, attachment_id, filename, raw)


def is_image_attachment_ready(attachment_id: str) -> bool:
    """True when the attachment is stored and not still compressing in the background."""
    from engine.setup_chat.image_upload_async import get_image_upload_status

    status = get_image_upload_status(attachment_id)
    if status is not None:
        return False
    return attachment_id in _ATTACHMENTS


def pop_attachment_text(attachment_id: str) -> tuple[str, str] | None:
    """One-time read: remove the entry and return (filename, decoded_text), or None if
    the id is unknown (already read, deleted, or never existed). Decoding happens here,
    not at store time, so this is the only place that assumes "text"."""
    att = _ATTACHMENTS.pop(attachment_id, None)
    if att is None:
        return None
    return att.filename, att.raw.decode("utf-8", errors="replace")


def pop_attachment_bytes(attachment_id: str) -> tuple[str, bytes] | None:
    """One-time read like pop_attachment_text, but returns raw bytes undecoded --
    for image attachments where UTF-8 decoding would corrupt the payload."""
    att = _ATTACHMENTS.pop(attachment_id, None)
    if att is None:
        return None
    return att.filename, att.raw


def pop_attachment_images_batch(attachment_ids: list[str]) -> list[tuple[str, str, bytes]] | None:
    """Pop multiple image attachments in natural filename order.

    Returns None if any id is missing or not an image file. All ids are consumed
    atomically on success; on failure nothing is popped. Each item is
    (attachment_id, filename, raw_bytes)."""
    ordered_ids = _present_attachment_ids_natural_order(attachment_ids)
    if len(ordered_ids) != len(attachment_ids):
        return None
    pending: list[tuple[str, str, bytes]] = []
    for aid in ordered_ids:
        att = _ATTACHMENTS.get(aid)
        if att is None or not att.filename.lower().endswith(IMAGE_EXTENSIONS):
            return None
        pending.append((aid, att.filename, att.raw))
    for aid, _, _ in pending:
        _ATTACHMENTS.pop(aid, None)
    return [(aid, filename, raw) for aid, filename, raw in pending]


def evict_attachment_memory(attachment_id: str) -> None:
    """Drop in-memory bytes without touching disk (used when replacing an upload in-flight)."""
    _ATTACHMENTS.pop(attachment_id, None)


def delete_attachment(attachment_id: str) -> None:
    """Drop an attachment without reading it (e.g. user removed the chip before sending).
    No-op if the id is unknown."""
    from engine.setup_chat.image_upload_async import cancel_image_upload

    cancel_image_upload(attachment_id)
    _ATTACHMENTS.pop(attachment_id, None)
    from utils.paths import active_novel_id

    from engine.setup_chat.attachment_persistence import delete_persisted_attachment

    delete_persisted_attachment(active_novel_id(), attachment_id)


def _natural_sort_key(filename: str) -> list[str | int]:
    """Split filename into alternating text/integer chunks for natural ordering."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", filename)]


def _present_attachment_ids_natural_order(attachment_ids: list[str]) -> list[str]:
    """Return still-present ids sorted by filename (1.jpg before 10.jpg)."""
    present = [aid for aid in attachment_ids if aid in _ATTACHMENTS]
    return sorted(present, key=lambda aid: _natural_sort_key(_ATTACHMENTS[aid].filename))


def count_pending_images(attachment_ids: list[str]) -> int:
    """Count how many of the given (still-present, not-yet-popped) attachment ids are
    image files -- lets the caller size an aggregate image-recognition progress bar
    up front, before the agent decides how many read_attachment_image calls to make."""
    return sum(
        1 for aid in _present_attachment_ids_natural_order(attachment_ids)
        if _ATTACHMENTS[aid].filename.lower().endswith(IMAGE_EXTENSIONS)
    )


def describe_attachments(attachment_ids: list[str]) -> str:
    """Format a manifest listing filename+id for each attachment still present (does not
    consume them — read_attachment does that). Unknown ids are silently skipped.
    Returns '' if none of the given ids are present."""
    lines = [
        f"- id={aid} filename={_ATTACHMENTS[aid].filename}"
        for aid in _present_attachment_ids_natural_order(attachment_ids)
    ]
    if not lines:
        return ""
    return "[已上传附件，可用 read_attachment 工具读取]\n" + "\n".join(lines)
