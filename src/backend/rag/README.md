# `rag/` — 向量化 + 召回

按小说隔离的 ChromaDB 向量库：`vector_store.py` 是通用的 upsert/query/delete 原语，具体每个消费方
（研究资料、sandbox 事件片段）的 id 策略/字段映射/embedding 结果消费都在
`repositories/chroma_repositories.py` 里，不在这个包内。库不存在或为空时召回返回 `[]`（按需增长，
无离线预建）。

| 文件 | 作用 | 关键符号 |
|------|------|----------|
| `embedding.py` | Embedding 函数单例（Chroma 注入用）。 | `get_embedding_function` |
| `vector_store.py` | 通用 Chroma collection 封装：upsert（向量化）+ query（召回）+ delete + count。 | `ChromaVectorStore` |

消费方：`repositories/chroma_repositories.py::ChromaResearchRepository`（研究资料，
`data/novels/<id>/rag/research_index`）、`SandboxVectorMemoryRepository`（sandbox 事件片段，
`sandbox_vector_memory_dir()`）。accessor：`repositories.get_research_repo()` /
`repositories.get_sandbox_vector_memory_repo()`。pytest 见 `tests/rag/test_vector_store.py` +
`tests/repositories/test_chroma_repositories.py`。

`embedding.py` 底层是 `fastembed`（ONNX Runtime），非 `sentence-transformers`/`torch`——历史上持久化的
旧库若带着不同引擎身份的 collection，`ChromaVectorStore._collection()` 会自愈重建（读出原始行 → 删库 →
用当前引擎重新写入），业务侧无感知。

不在此包内：tool_router.py 的 embedding 路由（无持久化/collection，纯内存 cosine 排序）、
记忆层压缩（`author_loop/dialogue_mode` 的 `_llm_view` 折叠、`setup_chat/memory.py::distill_decisions`）。
