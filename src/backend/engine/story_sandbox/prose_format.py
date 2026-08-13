"""Sandbox prose output-format enforcement: code-side half of the `【正文】：` marker contract
declared in prompt.py's `_OUTPUT_FORMAT_CONTRACT` (see that module for why the marker text
mirrors _progress_block's history rendering). Prompt instructions alone don't stop models from
prefixing out-of-character preamble ("好的，导演，以下接续正文——") before the real prose;
strip_prose_preamble buffers the start of the token stream, discards everything up to and
including the marker, and passes every later token through untouched -- so neither the frontend
stream nor the persisted round ever sees the noise. Pure logic, no LLM/websocket ties (same
split as style_guard.py: prompt asks nicely, this enforces).
"""
from __future__ import annotations

import re
from collections.abc import AsyncIterator

PROSE_MARKER_RE = re.compile(r"【正文】[：:]\s*")

# Fallback for completions that drop the colon and go straight to a paragraph break
# ("【正文】\n\n..."). Only applied at the fail-open boundary below (never in the eager
# per-token search above), because matching it eagerly would fire the instant "【正文】"
# lands in buf -- before a same-or-next-token colon has had a chance to arrive -- and
# strand that colon as leaked output instead (see the split-across-tokens regression test).
_PROSE_MARKER_NO_COLON_RE = re.compile(r"^【正文】\s*")

# Fail-open bounds: if the marker hasn't shown up by either of these, stop waiting and flush the
# buffer as prose -- covers models that never adopt the marker (older prompts cached before this
# contract, or non-compliant models) without swallowing their output. The paragraph-break check
# matters even more than the char ceiling: guarded_stream (message_hub.py's downstream consumer)
# flushes eagerly on "\n\n" so mid-turn cancellation can record() partial progress promptly --
# withholding a whole first paragraph behind an unmet marker would silently defeat that.
_PREAMBLE_MAX_CHARS = 80


async def strip_prose_preamble(token_iter: AsyncIterator[str]) -> AsyncIterator[str]:
    """Wrap a raw LLM token stream: drop any out-of-character preamble before the `【正文】：`
    marker, then yield everything after it unchanged, token by token."""
    buf = ""
    marker_found = False
    async for piece in token_iter:
        if marker_found:
            yield piece
            continue
        buf += piece
        m = PROSE_MARKER_RE.search(buf)
        if m:
            marker_found = True
            remainder = buf[m.end():]
            if remainder:
                yield remainder
            continue
        if len(buf) > _PREAMBLE_MAX_CHARS or "\n\n" in buf:
            marker_found = True
            buf = _PROSE_MARKER_NO_COLON_RE.sub("", buf, count=1)
            if buf:
                yield buf
    if not marker_found and buf:
        yield _PROSE_MARKER_NO_COLON_RE.sub("", buf, count=1)
