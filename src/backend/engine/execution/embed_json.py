"""LLM-JSON parsing (a retained tool extracted from the retired embed_splice).

The main author decision/skill selection (decision/build) and setup analysis (cast/plot/world) share parse_embed_json.
A pure string tool that has nothing to do with the theme and has nothing to do with the DAG sink machine."""
from __future__ import annotations

import json
import re

_JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
_OBJ_RE = re.compile(r"\{[^{}]*\}")


def parse_embed_json(raw: str) -> list[dict]:
    """
Parse the JSON object array output by LLM and tolerate multiple malformed formats of weak models:
    ① ```json fence ② Before and after noise ③ NDJSON / scattered object (no outer layer []) ④ Single object. If parsing fails, [] is returned."""

    s = (raw or "").strip()
    if not s:
        return []
    s = _JSON_FENCE_RE.sub("", s).strip()
    for candidate in (s, _slice_bracketed(s)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, list):
            return [it for it in data if isinstance(it, dict)]
        if isinstance(data, dict):
            return [data]
    out: list[dict] = []
    for m in _OBJ_RE.finditer(s):
        try:
            obj = json.loads(m.group(0))
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _slice_bracketed(s: str) -> str:
    """
Intercept the substring from the first '[' to the last ']' (tolerate json noise before and after)."""
    i, j = s.find("["), s.rfind("]")
    return s[i : j + 1] if 0 <= i < j else ""
