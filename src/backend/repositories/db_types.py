"""Custom column types for the repository layer."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator


class JSONText(TypeDecorator[Any]):
    """A TEXT column holding one JSON value, serialized with ensure_ascii=False.

    The payloads here are Chinese-heavy (character/plot/world data). SQLAlchemy's
    built-in JSON type serializes with json.dumps defaults (ASCII-escaped), which
    bloats the db file and makes it unreadable when inspecting directly. This
    matches the pre-ORM `json.dumps(..., ensure_ascii=False)` used everywhere."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None
