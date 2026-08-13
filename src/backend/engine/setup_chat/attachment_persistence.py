"""Per-novel on-disk store for setup-chat attachments (survives memory pop / process restart)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from utils.paths import novel_attachments_dir

from engine.setup_chat.attachments import IMAGE_EXTENSIONS

_INDEX_FILENAME = "index.json"


@dataclass(frozen=True)
class PersistedAttachmentMeta:
    attachment_id: str
    filename: str
    kind: str
    size_bytes: int
    uploaded_at: str
    has_description: bool = False


def _index_path(novel_id: str) -> str:
    return os.path.join(novel_attachments_dir(novel_id), _INDEX_FILENAME)


def _safe_filename(filename: str) -> str:
    name = Path(filename).name.replace("\\", "_").replace("/", "_").strip()
    return name or "attachment"


def _stored_basename(attachment_id: str, filename: str) -> str:
    return f"{attachment_id}_{_safe_filename(filename)}"


def _attachment_file_path(novel_id: str, attachment_id: str, filename: str) -> str:
    return os.path.join(novel_attachments_dir(novel_id), _stored_basename(attachment_id, filename))


def _description_file_path(novel_id: str, attachment_id: str) -> str:
    return os.path.join(novel_attachments_dir(novel_id), f"{attachment_id}_description.txt")


def _natural_sort_key(filename: str) -> list[str | int]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", filename)]


def _kind_for_filename(filename: str) -> str:
    return "image" if filename.lower().endswith(IMAGE_EXTENSIONS) else "text"


def _read_index(novel_id: str) -> list[dict]:
    from repositories.sqlite_store import SqliteStore

    data = SqliteStore(novel_id).get_doc("attachments_index", "")
    if not isinstance(data, dict):
        return []
    items = data.get("attachments")
    return list(items) if isinstance(items, list) else []


def _write_index(novel_id: str, entries: list[dict]) -> None:
    from repositories.sqlite_store import SqliteStore

    SqliteStore(novel_id).save_doc("attachments_index", "", {"attachments": entries})


def persist_attachment(novel_id: str, attachment_id: str, filename: str, raw: bytes) -> None:
    """Write attachment bytes and append/update index entry."""
    _purge_duplicate_filenames(novel_id, filename, keep_id=attachment_id)
    root = novel_attachments_dir(novel_id)
    os.makedirs(root, exist_ok=True)
    file_path = _attachment_file_path(novel_id, attachment_id, filename)
    with open(file_path, "wb") as f:
        f.write(raw)

    entries = [e for e in _read_index(novel_id) if e.get("attachment_id") != attachment_id]
    entries.append({
        "attachment_id": attachment_id,
        "filename": filename,
        "kind": _kind_for_filename(filename),
        "size_bytes": len(raw),
        "uploaded_at": datetime.now(UTC).isoformat(),
    })
    _write_index(novel_id, entries)


def persist_image_description(novel_id: str, attachment_id: str, description: str) -> None:
    """Write vision-model description text for one image attachment (1:1 sidecar file)."""
    root = novel_attachments_dir(novel_id)
    os.makedirs(root, exist_ok=True)
    path = _description_file_path(novel_id, attachment_id)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(description)
    os.replace(tmp, path)


def load_image_description(novel_id: str, attachment_id: str) -> str | None:
    path = _description_file_path(novel_id, attachment_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    return text if text.strip() else None


def find_persisted_attachment_id_by_filename(novel_id: str, filename: str) -> str | None:
    target = _safe_filename(filename)
    for entry in _read_index(novel_id):
        if not isinstance(entry, dict):
            continue
        fn = entry.get("filename")
        aid = entry.get("attachment_id")
        if isinstance(fn, str) and isinstance(aid, str) and _safe_filename(fn) == target:
            return aid
    return None


def clear_image_description(novel_id: str, attachment_id: str) -> None:
    path = _description_file_path(novel_id, attachment_id)
    try:
        os.remove(path)
    except OSError:
        pass


def _purge_duplicate_filenames(novel_id: str, filename: str, *, keep_id: str) -> None:
    """Remove older index entries that share the same basename -- comic re-uploads reuse one slot."""
    target = _safe_filename(filename)
    for entry in list(_read_index(novel_id)):
        if not isinstance(entry, dict):
            continue
        aid = entry.get("attachment_id")
        fn = entry.get("filename")
        if not isinstance(aid, str) or aid == keep_id:
            continue
        if isinstance(fn, str) and _safe_filename(fn) == target:
            delete_persisted_attachment(novel_id, aid)


def delete_persisted_attachment(novel_id: str, attachment_id: str) -> None:
    entries = _read_index(novel_id)
    kept: list[dict] = []
    removed_filename: str | None = None
    for entry in entries:
        if entry.get("attachment_id") == attachment_id:
            removed_filename = entry.get("filename")
            continue
        kept.append(entry)
    if removed_filename is None:
        return
    _write_index(novel_id, kept)
    file_path = _attachment_file_path(novel_id, attachment_id, removed_filename)
    try:
        os.remove(file_path)
    except OSError:
        pass
    desc_path = _description_file_path(novel_id, attachment_id)
    try:
        os.remove(desc_path)
    except OSError:
        pass


def list_persisted_attachments(novel_id: str) -> list[PersistedAttachmentMeta]:
    metas = [
        PersistedAttachmentMeta(
            attachment_id=str(entry["attachment_id"]),
            filename=str(entry["filename"]),
            kind=str(entry.get("kind") or _kind_for_filename(str(entry["filename"]))),
            size_bytes=int(entry.get("size_bytes") or 0),
            uploaded_at=str(entry.get("uploaded_at") or ""),
            has_description=load_image_description(novel_id, str(entry["attachment_id"])) is not None,
        )
        for entry in _read_index(novel_id)
        if isinstance(entry, dict) and entry.get("attachment_id") and entry.get("filename")
    ]
    return sorted(metas, key=lambda m: _natural_sort_key(m.filename))


def load_persisted_attachment_bytes(novel_id: str, attachment_id: str) -> tuple[str, bytes] | None:
    for entry in _read_index(novel_id):
        if entry.get("attachment_id") != attachment_id:
            continue
        filename = entry.get("filename")
        if not isinstance(filename, str) or not filename:
            return None
        file_path = _attachment_file_path(novel_id, attachment_id, filename)
        if not os.path.isfile(file_path):
            return None
        try:
            with open(file_path, "rb") as f:
                return filename, f.read()
        except OSError:
            return None
    return None


def find_persisted_attachment(novel_id: str, attachment_id: str) -> PersistedAttachmentMeta | None:
    for meta in list_persisted_attachments(novel_id):
        if meta.attachment_id == attachment_id:
            return meta
    return None


def load_attachment_parsed_content(novel_id: str, attachment_id: str) -> str | None:
    """Vision description for images; UTF-8 body for text attachments."""
    loaded = load_persisted_attachment_bytes(novel_id, attachment_id)
    if loaded is None:
        return None
    filename, raw = loaded
    if _kind_for_filename(filename) == "image":
        return load_image_description(novel_id, attachment_id)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return text if text.strip() else None
