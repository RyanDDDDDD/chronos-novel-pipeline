"""Generic SQLite-backed vector store: upsert (vectorize) + query (recall) + delete + count,
parameterized by collection name + db path. Backs the two RAG-only consumers -- setup_research
and sandbox_vector_memory -- see repositories/vector_repositories.py. Replaces the prior
embedded vector DB implementation (2026-08-08 migration, see docs/superpowers/specs/2026-08-08-
chroma-to-sqlite-vector-store-migration-design.md): both collections are small enough
(hundreds to low-thousands of rows per novel) that a brute-force cosine scan beats paying for
a second embedded-database dependency (legacy HNSW index + embedding-function identity
bookkeeping) alongside the project's own per-novel SQLite store.

CRUD runs through the VectorChunk SQLModel table; query() is a plain numpy cosine scan over
the collection's embedding blobs (not SQL) and stays as-is."""
from __future__ import annotations

from array import array
from typing import Any

import numpy as np
from repositories.engine import engine_for_path
from repositories.models import VectorChunk
from sqlalchemy import delete, func
from sqlmodel import Session, col, select


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

    def _session(self) -> Session:
        return Session(engine_for_path(self._db_path))

    def upsert(
        self, ids: list[str], documents: list[str], metadatas: list[dict[str, Any]],
    ) -> int:
        if not ids:
            return self.count()
        vectors = self._embedding_function()(documents)
        with self._session() as s:
            for i, d, m, v in zip(ids, documents, metadatas, vectors, strict=True):
                row = s.get(VectorChunk, (self._collection_name, i))
                if row is None:
                    s.add(VectorChunk(
                        collection=self._collection_name, id=i, document=d,
                        metadata_json=m, embedding=pack_embedding(v),
                    ))
                else:
                    row.document = d
                    row.metadata_json = m
                    row.embedding = pack_embedding(v)
            s.commit()
        return self.count()

    def _all_rows(self) -> list[tuple[str, str, dict[str, Any], bytes]]:
        with self._session() as s:
            rows = s.exec(
                select(
                    VectorChunk.id, VectorChunk.document,
                    VectorChunk.metadata_json, VectorChunk.embedding,
                ).where(col(VectorChunk.collection) == self._collection_name)
            ).all()
        return [(r[0], r[1], dict(r[2]), r[3]) for r in rows]

    def query(self, text: str, top_k: int) -> list[dict[str, Any]]:
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
                "metadata": row[2], "distance": float(1.0 - sims[int(idx)]),
            })
        return out

    def get_ids(self, where: dict[str, Any]) -> list[str]:
        return [r[0] for r in self._all_rows() if _matches(where, r[2])]

    def get(self, where: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"id": r[0], "document": r[1], "metadata": r[2]}
            for r in self._all_rows()
            if _matches(where, r[2])
        ]

    def delete(self, where: dict[str, Any] | None = None, ids: list[str] | None = None) -> None:
        if not where and not ids:
            return
        target_ids = ids if ids else self.get_ids(where or {})
        if not target_ids:
            return
        with self._session() as s:
            s.exec(
                delete(VectorChunk).where(
                    col(VectorChunk.collection) == self._collection_name,
                    col(VectorChunk.id).in_(target_ids),
                )
            )
            s.commit()

    def count(self) -> int:
        with self._session() as s:
            n = s.exec(
                select(func.count()).select_from(VectorChunk)
                .where(col(VectorChunk.collection) == self._collection_name)
            ).one()
        return int(n)
