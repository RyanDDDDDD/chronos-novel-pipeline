"""Shared embedding singleton (bge-small-zh) -- FastEmbed (ONNX Runtime) backend. No longer
implements the retired EmbeddingFunction protocol (register_embedding_function/name()/
get_config()/build_from_config()/default_space()) -- those existed only so the old vector
store's get_or_create_collection(embedding_function=...) could persist and validate engine identity;
SqliteVectorStore (rag/vector_store.py) owns its embeddings directly and has no such
requirement (2026-08-08 vector-store migration, see docs/superpowers/specs/2026-08-08-
chroma-to-sqlite-vector-store-migration-design.md)."""
from __future__ import annotations

from functools import lru_cache

_MODEL_NAME = "BAAI/bge-small-zh-v1.5"


class FastEmbedFunction:
    def __init__(self, model_name: str = _MODEL_NAME) -> None:
        from fastembed import TextEmbedding

        self.model_name = model_name
        self._model = TextEmbedding(model_name=model_name)

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._model.embed(list(input))]


@lru_cache(maxsize=1)
def get_embedding_function() -> FastEmbedFunction:
    return FastEmbedFunction()
