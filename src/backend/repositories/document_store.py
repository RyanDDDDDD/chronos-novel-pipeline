"""Documents table primitives for arbitrary key-value JSON storage (world_bible, etc.)."""
from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm.exc import StaleDataError

from repositories.engine import session_for
from repositories.models import Document


def get_document(novel_id: str | None, key: str) -> Any | None:
    with session_for(novel_id) as s:
        doc = s.get(Document, key)
        return doc.data_json if doc is not None else None


def save_document(novel_id: str | None, key: str, data: Any) -> None:
    with session_for(novel_id) as s:
        doc = s.get(Document, key)
        if doc is None:
            s.add(Document(doc_key=key, data_json=data, version=1))
        else:
            doc.data_json = data
        s.commit()


def get_document_with_version(novel_id: str | None, key: str) -> tuple[Any, int] | None:
    with session_for(novel_id) as s:
        doc = s.get(Document, key)
        if doc is None:
            return None
        return doc.data_json, doc.version


def save_document_if_version_matches(
    novel_id: str | None, key: str, data: Any, expected_version: int
) -> int | None:
    with session_for(novel_id) as s:
        if expected_version == 0:
            existing = s.get(Document, key)
            if existing is not None:
                return None
            s.add(Document(doc_key=key, data_json=data, version=1))
            try:
                s.commit()
            except IntegrityError:
                s.rollback()
                return None
            return 1
        obj = s.get(Document, key)
        if obj is None or obj.version != expected_version:
            return None
        obj.data_json = data
        flag_modified(obj, "data_json")
        try:
            s.commit()
        except (StaleDataError, IntegrityError):
            s.rollback()
            return None
        s.refresh(obj)
        return int(obj.version) if obj.version is not None else None
