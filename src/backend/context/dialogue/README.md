# `context/dialogue/` — 对话链共享脚手架

互称、声线门控等章节级注入文本；由 author_loop 经 `ContextRegistry` 解析后写入 prompt。

| 文件 | 作用 | 关键符号 |
|------|------|----------|
| `scaffold.py` | character_archive 解析（flat profile，无 stage 展开）。 | `parse_character_archives`、`expand_archives_to_stages` |
| `scene_aware.py` | 场景感知称呼解析：`address_ref` / `self_ref` 标签→显示名。 | `as_target_pool_map` |

台词 RAG 检索在 `rag/`（向量库），与本目录静态脚手架互补。
