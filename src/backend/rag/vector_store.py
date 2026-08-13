"""Generic SQLite-backed vector store: upsert (vectorize) + query (recall) + delete + count,
parameterized by collection name + db path. Backs the two RAG-only consumers -- setup_research
and sandbox_vector_memory -- see repositories/vector_repositories.py. Replaces the prior
embedded vector DB implementation (2026-08-08 migration, see docs/superpowers/specs/2026-08-08-
chroma-to-sqlite-vector-store-migration-design.md): both collections are small enough
(hundreds to low-thousands of rows per novel) that a brute-force cosine scan beats paying for
a second embedded-database dependency (legacy HNSW index + embedding-function identity
bookkeeping) alongside the project's own per-novel SQLite store."""
from __future__ import annotations

from array import array
from typing import Any

import numpy as np
from repositories.sqlite_store import _WRITE_LOCK, get_connection


def pack_embedding(vector: list[float]) -> bytes:
    return array("f", vector).tobytes()


def unpack_embedding(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def _matches(where: dict[str, Any], metadata: dict[str, Any]) -> bool:
    """Minimal where-matcher covering only the two shapes this codebase's callers actually
    use (repositories/vector_repositories.py): a flat equality dict, or one level of $and
    of equality dicts. Not a general query engine -- YAGNI."""
    if "$and" in where:
        return all(_matches(cond, metadata) for cond in where["$and"])
    return all(metadata.get(k) == v for k, v in where.items())


class SqliteVectorStore:
    def __init__(
        self, collection_name: str, db_path: str, embedding_fn: Any = None,
    ) -> None:
        self._collection_name = collection_name
        self._db_path = db_path
        self._embedding_fn = embedding_fn

    def _embedding_function(self) -> Any:
        if self._embedding_fn is not None:
            return self._embedding_fn
        from rag.embedding import get_embedding_function
        return get_embedding_function()

    def _conn(self):  # noqa: ANN201 -- sqlite3.Connection, kept untyped to avoid import-only-for-annotation
        return get_connection(self._db_path)

    def upsert(
        self, ids: list[str], documents: list[str], metadatas: list[dict[str, Any]],
    ) -> int:
        if not ids:
            return self.count()
        # Legacy callers may pass empty metadata dicts; json.dumps({}) round-trips fine,
        # no coercion needed (unlike the old empty-dict rejection in the prior vector store).
        import json

        vectors = self._embedding_function()(documents)
        conn = self._conn()
        with _WRITE_LOCK:
            conn.executemany(
                "INSERT OR REPLACE INTO vector_chunks "
                "(collection, id, document, metadata_json, embedding) VALUES (?, ?, ?, ?, ?)",
                [
                    (self._collection_name, i, d, json.dumps(m, ensure_ascii=False), pack_embedding(v))
                    for i, d, m, v in zip(ids, documents, metadatas, vectors, strict=True)
                ],
            )
            conn.commit()
        return self.count()

    def _all_rows(self) -> list[tuple[str, str, str, bytes]]:
        rows = self._conn().execute(
            "SELECT id, document, metadata_json, embedding FROM vector_chunks WHERE collection = ?",
            (self._collection_name,),
        ).fetchall()
        return list(rows)

    def query(self, text: str, top_k: int) -> list[dict[str, Any]]:
        import json

        rows = self._all_rows()
        if not rows:
            return []
        query_vec = np.asarray(self._embedding_function()([text])[0], dtype=np.float32)
        mat = np.stack([unpack_embedding(r[3]) for r in rows])
        norms = np.linalg.norm(mat, axis=1) * np.linalg.norm(query_vec)
        norms[norms == 0] = 1e-12
        sims = (mat @ query_vec) / norms
        order = np.argsort(-sims)[:top_k]
        out: list[dict[str, Any]] = []
        for idx in order:
            row = rows[int(idx)]
            out.append({
                "id": row[0], "document": row[1],
                "metadata": json.loads(row[2]), "distance": float(1.0 - sims[int(idx)]),
            })
        return out

    def get_ids(self, where: dict[str, Any]) -> list[str]:
        import json

        return [
            r[0] for r in self._all_rows() if _matches(where, json.loads(r[2]))
        ]

    def get(self, where: dict[str, Any]) -> list[dict[str, Any]]:
        import json

        out: list[dict[str, Any]] = []
        for r in self._all_rows():
            meta = json.loads(r[2])
            if _matches(where, meta):
                out.append({"id": r[0], "document": r[1], "metadata": meta})
        return out

    def delete(self, where: dict[str, Any] | None = None, ids: list[str] | None = None) -> None:
        if not where and not ids:
            return
        target_ids = ids if ids else self.get_ids(where or {})
        if not target_ids:
            return
        conn = self._conn()
        with _WRITE_LOCK:
            placeholders = ",".join("?" * len(target_ids))
            conn.execute(
                f"DELETE FROM vector_chunks WHERE collection = ? AND id IN ({placeholders})",
                (self._collection_name, *target_ids),
            )
            conn.commit()

    def count(self) -> int:
        row = self._conn().execute(
            "SELECT COUNT(*) FROM vector_chunks WHERE collection = ?",
            (self._collection_name,),
        ).fetchone()
        return int(row[0]) if row else 0
