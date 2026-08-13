"""Vector data repositories: wraps rag/vector_store.py's generic SQLite-backed vector primitive with
domain-specific id strategy + metadata field mapping + entity types, one repository per vector
collection (mirrors sqlite_repositories.py's one-file-per-storage-backend organization). Path
resolution happens per-call, not cached in __init__, since it depends on the currently active
novel."""
from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from utils.paths import novel_db_path

from repositories.entities import ResearchChunk, SandboxMemoryHit

_RESEARCH_COLLECTION = "setup_research"
_SANDBOX_MEMORY_COLLECTION = "sandbox_vector_memory"


def _sqlite_vector_store(collection_name: str):
    from rag.vector_store import SqliteVectorStore
    return SqliteVectorStore(collection_name, novel_db_path())


def _research_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


class ResearchRepository:
    """Set up a research library (grow on demand: check + write). The persist path is parsed each
    time according to the active novel."""

    def query(self, topic: str, top_k: int) -> list[ResearchChunk]:
        store = _sqlite_vector_store(_RESEARCH_COLLECTION)
        hits = store.query(topic, top_k)
        return [
            ResearchChunk(
                text=h["document"], topic=h["metadata"].get("topic", ""),
                source=h["metadata"].get("source", ""), category=h["metadata"].get("category", ""),
                score=h["distance"], mention_count=h["metadata"].get("mention_count", 1),
            )
            for h in hits
        ]

    def upsert(self, chunks: list[ResearchChunk]) -> int:
        """Idempotent upsert (dedup by sha1 of text)."""
        valid = [c for c in chunks if c.text]
        store = _sqlite_vector_store(_RESEARCH_COLLECTION)
        if not valid:
            return int(store.count())
        seen: dict[str, ResearchChunk] = {}
        for c in valid:
            seen[_research_id(c.text)] = c
        ids = list(seen)
        return int(store.upsert(
            ids=ids,
            documents=[seen[i].text for i in ids],
            metadatas=[
                {
                    "topic": seen[i].topic, "source": seen[i].source, "category": seen[i].category,
                    "mention_count": seen[i].mention_count,
                }
                for i in ids
            ],
        ))

    def get_chunks(self, category: str, topic: str | None = None) -> list[ResearchChunk]:
        """Exact metadata-filtered fetch, no relevance ranking -- topic=None returns every
        chunk in the category (world/plot enumeration), a given topic exact-matches a single
        entity (character lookup)."""
        where: dict[str, Any] = (
            {"category": category} if topic is None
            else {"$and": [{"category": category}, {"topic": topic}]}
        )
        store = _sqlite_vector_store(_RESEARCH_COLLECTION)
        rows = store.get(where=where)
        return [
            ResearchChunk(
                text=r["document"], topic=r["metadata"].get("topic", ""),
                source=r["metadata"].get("source", ""), category=r["metadata"].get("category", ""),
                mention_count=r["metadata"].get("mention_count", 1),
            )
            for r in rows
        ]

    def list_topics(self, category: str) -> list[str]:
        """Distinct topic values for a category (e.g. every character name) -- exact and
        exhaustive, unlike query()'s semantic top-k."""
        seen: dict[str, None] = {}
        for chunk in self.get_chunks(category):
            if chunk.topic:
                seen.setdefault(chunk.topic, None)
        return list(seen)

    def replace_for_source(self, source: str, chunks: list[ResearchChunk]) -> int:
        """Source-scoped replace: upsert the given chunks first, then delete whatever
        previously existed for this source and isn't among the new ids -- write-then-delete
        order so a mid-call failure never leaves a window with no data for this source (see
        docs/superpowers/specs/2026-07-22-novel-import-sequential-map-context-design.md
        decision 7)."""
        valid = [c for c in chunks if c.text]
        new_ids = {_research_id(c.text) for c in valid}
        written = self.upsert(valid)
        store = _sqlite_vector_store(_RESEARCH_COLLECTION)
        stale_ids = [i for i in store.get_ids(where={"source": source}) if i not in new_ids]
        if stale_ids:
            store.delete(ids=stale_ids)
        return written

    async def replace_for_source_async(self, source: str, chunks: list[ResearchChunk]) -> int:
        """Async wrapper around replace_for_source -- offloads the synchronous vector-store call to a
        thread so it doesn't block the event loop. Does not add any ordering guarantee across
        multiple calls for the same source; callers that need that (see
        engine/setup_chat/novel_import.run_map_stage) must serialize their own calls."""
        return await asyncio.to_thread(self.replace_for_source, source, chunks)


class SandboxVectorMemoryRepository:
    """Archives story_sandbox event-log fragments into a per-novel vector collection and supports
    semantic recall over them -- absorbed from the retired
    engine/story_sandbox/vector_memory.py (see git history for the original design docs this
    still follows: docs/superpowers/specs/2026-07-14-story-sandbox-event-log-realtime-and-vector-
    memory-design.md §4.3/§5.5, docs/superpowers/specs/2026-07-14-story-sandbox-vector-memory-
    recall-design.md)."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    @staticmethod
    def _store():
        return _sqlite_vector_store(_SANDBOX_MEMORY_COLLECTION)

    @staticmethod
    def _embedding_text(entry: dict[str, Any]) -> str:
        """Embeds all four elements (event/time/location/characters) into one string so semantic
        search can match on any of them, not just the summary text."""
        time = str(entry.get("time") or "").strip()
        location = str(entry.get("location") or "").strip()
        summary = str(entry.get("summary") or "")
        header_bits = [b for b in (time, f"于{location}" if location else "") if b]
        header = "，".join(header_bits)
        text = f"{header}：{summary}" if header else summary
        characters = entry.get("characters") or []
        if characters:
            text += f"（人物：{'、'.join(characters)}）"
        return text

    def _archive_sync(self, entries: list[dict[str, Any]]) -> int:
        valid = [e for e in entries if e.get("id") and e.get("summary")]
        store = self._store()
        if not valid:
            return int(store.count())
        return int(store.upsert(
            ids=[e["id"] for e in valid],
            documents=[self._embedding_text(e) for e in valid],
            metadatas=[
                {
                    "chapter": int(e.get("chapter", 0)), "turn_index": int(e.get("turn_index", 0)),
                    "time": str(e.get("time") or ""), "location": str(e.get("location") or ""),
                    "characters": ",".join(e.get("characters") or []),
                    "entities": ",".join(e.get("entities") or []),
                    "summary": str(e.get("summary") or ""),
                    "branch_id": str(e.get("branch_id") or ""),
                    "origin": str(e.get("origin") or ""),
                }
                for e in valid
            ],
        ))

    async def archive(self, entries: list[dict[str, Any]]) -> int:
        async with self._lock:
            return await asyncio.to_thread(self._archive_sync, entries)

    def query(self, text: str, top_k: int) -> list[SandboxMemoryHit]:
        """Semantic recall over previously archived event fragments -- synchronous/blocking, same
        as the retired query_similar (see TODO.md's noted-but-unquantified hot-spot list)."""
        hits = self._store().query(text, top_k)
        out: list[SandboxMemoryHit] = []
        for h in hits:
            m = h["metadata"]
            entities_raw = str(m.get("entities") or "")
            characters_raw = str(m.get("characters") or "")
            out.append(SandboxMemoryHit(
                id=h["id"], chapter=m.get("chapter", 0), turn_index=m.get("turn_index", 0),
                time=m.get("time", ""), location=m.get("location", ""),
                summary=m.get("summary", ""),
                entities=entities_raw.split(",") if entities_raw else [],
                characters=characters_raw.split(",") if characters_raw else [],
                branch_id=str(m.get("branch_id") or ""),
                origin=str(m.get("origin") or ""),
            ))
        return out

    def _delete_chapter_sync(self, chapter: int, branch_id: str | None = None) -> None:
        if branch_id is None:
            self._store().delete(where={"chapter": chapter})
        else:
            self._store().delete(where={"$and": [{"chapter": chapter}, {"branch_id": branch_id}]})

    async def delete_chapter(self, chapter: int, branch_id: str | None = None) -> None:
        async with self._lock:
            await asyncio.to_thread(self._delete_chapter_sync, chapter, branch_id)

    def _copy_branch_sync(
        self, chapter: int, source_branch_id: str, dest_branch_id: str, id_remap: dict[str, str],
    ) -> None:
        rows = self._store().get(
            {"$and": [{"chapter": chapter}, {"branch_id": source_branch_id}]},
        )
        entries: list[dict[str, Any]] = []
        for r in rows:
            new_id = id_remap.get(r["id"])
            if not new_id:
                continue
            m = r["metadata"]
            entities_raw = str(m.get("entities") or "")
            characters_raw = str(m.get("characters") or "")
            entries.append({
                "id": new_id, "chapter": m.get("chapter", 0), "turn_index": m.get("turn_index", 0),
                "time": m.get("time", ""), "location": m.get("location", ""),
                "summary": m.get("summary", ""),
                "entities": entities_raw.split(",") if entities_raw else [],
                "characters": characters_raw.split(",") if characters_raw else [],
                "branch_id": dest_branch_id,
                "origin": m.get("origin", ""),
            })
        if entries:
            self._archive_sync(entries)

    async def copy_branch(
        self, chapter: int, source_branch_id: str, dest_branch_id: str, id_remap: dict[str, str],
    ) -> None:
        """Duplicates this branch's already-archived vector-memory entries named as keys in
        id_remap (produced by graph.py::fork_branch) into a new branch with the remapped ids --
        Vector upserts are keyed globally by id, so reusing the source's ids here would let the
        forked branch's later rewrites silently overwrite the source's archived memories (and
        vice versa). No-op when id_remap is empty."""
        if not id_remap:
            return
        async with self._lock:
            await asyncio.to_thread(
                self._copy_branch_sync, chapter, source_branch_id, dest_branch_id, id_remap,
            )
