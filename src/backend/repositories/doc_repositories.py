"""Single document domain repo: world_bible/relationship_graph.

Entire JSON document, sending and receiving dict (thin passthrough, no Pydantic entities). Both reading and writing are written through the SqliteStore universal document.
SqliteStore.reset() has cleared archive cache when cutting novels, and each repo will be reloaded from the new active path the next time it is read."""
from __future__ import annotations

from utils.paths import world_bible_path

from repositories.sqlite_store import SqliteStore


class WorldRepository:
    def __init__(self, store: SqliteStore) -> None:
        self._store = store

    def get(self, path: str | None = None) -> dict | None:
        p = path if path is not None else world_bible_path()
        return self._store.get_doc("world_bible", p)

    def save(self, data: dict, path: str | None = None) -> None:
        p = path if path is not None else world_bible_path()
        self._store.save_doc("world_bible", p, data)
