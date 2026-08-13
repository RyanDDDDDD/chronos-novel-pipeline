"""Ephemeral in-memory cache of a novel import's pre-cut text chunks, keyed by novel_id.

Per docs/superpowers/specs/2026-07-23-novel-import-prose-style-decouple-design.md: decouples
prose-style generation from read_attachment -- read_attachment stores the chunks it just cut
here, and the agent-initiated build_prose_style_from_import tool reads them back later,
without needing the raw attachment text again (which read_attachment already discarded via
attachments.py's one-time pop).

Differs from attachments.py's one-time-pop semantics: entries here are NOT cleared on read,
because build_prose_style_from_import is an independent tool call that may need to be retried
(e.g. after a transient LLM failure) without forcing the user to re-upload the attachment. An
entry is only replaced by the next read_attachment call for the same novel_id. Like
attachments.py, this is in-process memory only -- a process restart clears everything, an
accepted tradeoff, not a bug."""
from __future__ import annotations

from engine.setup_chat.novel_import import TextChunk

_STYLE_SOURCE_CHUNKS: dict[str, list[TextChunk]] = {}


def store_chunks(novel_id: str, chunks: list[TextChunk]) -> None:
    """Cache the chunks from a novel's most recent import, replacing any prior entry for
    the same novel_id."""
    _STYLE_SOURCE_CHUNKS[novel_id] = chunks


def get_chunks(novel_id: str) -> list[TextChunk] | None:
    """Return the most recently imported chunks for novel_id, or None if this novel has
    never been imported (or the process restarted since). Does not clear the entry."""
    return _STYLE_SOURCE_CHUNKS.get(novel_id)
