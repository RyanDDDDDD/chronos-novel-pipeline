"""Small, tolerant JSON extraction for story-sandbox LLM calls: strips a leading/trailing
```json ... ``` markdown fence some models wrap output in despite being told "JSON only", and
falls back to slicing between the first/last bracket if the model added noise before/after the
JSON itself. Mirrors engine/execution/embed_json.py's parse_embed_json, scoped to the plain
list/dict shapes story-sandbox actually needs (that one is specialized for list-of-object
payloads)."""
from __future__ import annotations

import json
import re
from typing import Any

_JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)

# Chinese-prose-heavy completions occasionally close a JSON string with a typographic quote
# (” "..., ’ '...) instead of the required ASCII `"` -- the model slips into prose
# quoting habits right at the delimiter. Only rewrite a smart quote immediately before a `]`/`}`
# or before `, "`/`, }`-style continuations: those positions are unambiguous JSON-terminator
# slots. A smart quote anywhere else (e.g. mid-sentence dialogue, followed by more prose) is left
# alone since rewriting it there would corrupt real content instead of fixing the delimiter.
_SMART_QUOTE_TERMINATOR_RE = re.compile(r'[”’](?=\s*[\]}])|[”’](?=\s*,\s*["{])')


def _repair_smart_quote_terminators(s: str) -> str:
    return _SMART_QUOTE_TERMINATOR_RE.sub('"', s)


def _slice_bracketed(s: str, open_ch: str, close_ch: str) -> str:
    i, j = s.find(open_ch), s.rfind(close_ch)
    return s[i : j + 1] if 0 <= i < j else ""


def extract_json_list(raw: str) -> list[Any] | None:
    """Returns the parsed JSON list, or None if neither the fence-stripped text nor the
    first-[-to-last-] slice of it parses as a list."""
    cleaned = _repair_smart_quote_terminators(_JSON_FENCE_RE.sub("", (raw or "").strip()).strip())
    for candidate in (cleaned, _slice_bracketed(cleaned, "[", "]")):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return parsed
    return None


def extract_json_dict(raw: str) -> dict[str, Any] | None:
    """Returns the parsed JSON object, or None if neither the fence-stripped text nor the
    first-{-to-last-} slice of it parses as a dict."""
    cleaned = _repair_smart_quote_terminators(_JSON_FENCE_RE.sub("", (raw or "").strip()).strip())
    for candidate in (cleaned, _slice_bracketed(cleaned, "{", "}")):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None
