"""Single document domain repo: world_bible/relationship_graph.

Entire JSON document, sending and receiving dict (thin passthrough, no Pydantic entities).
"""
from __future__ import annotations

from typing import Any

from repositories.document_store import (
    get_document,
    get_document_with_version,
    save_document,
    save_document_if_version_matches,
)
from repositories.sqlite_store import SqliteStore


class WorldRepository:
    def __init__(self, novel_id_or_store: str | SqliteStore | None = None) -> None:
        if isinstance(novel_id_or_store, str):
            self._nid: str | None = novel_id_or_store
        elif novel_id_or_store is not None and hasattr(novel_id_or_store, "_novel_id"):
            self._nid = novel_id_or_store._novel_id
        else:
            self._nid = None

    def get(self, path: str | None = None) -> dict[str, Any] | None:
        del path
        data = get_document(self._nid, "world_bible")
        return data if isinstance(data, dict) else None

    def save(self, data: dict[str, Any], path: str | None = None) -> None:
        del path
        save_document(self._nid, "world_bible", data)

    def get_with_version(self) -> tuple[dict[str, Any], int] | None:
        res = get_document_with_version(self._nid, "world_bible")
        if res is None:
            return None
        data, ver = res
        return (data if isinstance(data, dict) else {}), ver

    def save_if_version_matches(self, data: dict[str, Any], expected_version: int) -> int | None:
        return save_document_if_version_matches(self._nid, "world_bible", data, expected_version)
