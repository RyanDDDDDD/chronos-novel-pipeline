import numpy as np

from rag.embedding import get_embedding_function


def test_get_embedding_function_is_cached_singleton():
    a = get_embedding_function()
    b = get_embedding_function()
    assert a is b


def test_embedding_function_returns_vectors_for_texts():
    fn = get_embedding_function()
    vectors = fn(["赛博都市由七大企业统治", "主角在雨夜的天台上独自练剑"])
    assert len(vectors) == 2
    assert len(vectors[0]) == 512
    assert all(isinstance(x, (float, np.floating)) for x in vectors[0])
