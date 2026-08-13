# Chronos Engine 项目 CPU Bound / 阻塞点盘点报告

> 基于 `TODO.md:46-57` 最后一个 ticket（`通用线程池设施` 及其 CPU 阻塞点清单），全仓库实测盘点后的最新结果。

---

## ⚡ 核心 CPU-Bound 重灾区：本地 Embedding 向量计算 (PyTorch / SentenceTransformer)

项目中使用 `src/backend/rag/embedding.py:10-13` 加载本地 PyTorch 模型 `BAAI/bge-small-zh-v1.5` 计算文本向量。每次生成向量需要数十到上百毫秒的 CPU 计算。

由于 ChromaDB 仓库底层的 `query` / `upsert` 为同步阻塞函数，在 `async` 协程中**如果没有扔进线程池 (`asyncio.to_thread`)**，就会直接卡死主 Event Loop 线程。

目前排查出以下 3 处仍在主线程同步触发 Embedding 的热路径：

### 1. 🔴 主笔范式 / 对话模式热路径
- **代码位置**：`src/backend/engine/author_loop/dialogue_mode/react_graph.py:141-145`
- **问题描述**：在 `async def` 节点的对话生成流程中，直接**同步**调用了 `src/backend/engine/memory_recall/recall.py:56-92`。该函数内部会执行 `get_sandbox_vector_memory_repo().query(text)`，每次主笔生成 Beat/Turn 时都会在主线程跑 PyTorch 模型生成向量，阻塞整个 Event Loop。

### 2. 🔴 Setup Chat 工具动态路由
- **代码位置**：`src/backend/engine/setup_chat/memory.py:597` 与 `src/backend/engine/setup_chat/tool_router.py:88`
- **问题描述**：Setup Chat 逐轮对话的 Pre-model hook 中，在无特定 pipeline focus 时，`src/backend/engine/setup_chat/tool_router.py:99-120` 会同步执行 `embed_fn([user_text])` 计算用户输入的 embedding。用户每发送一句话都会在主线程卡顿数十至上百毫秒。

### 3. 🟡 Setup Chat RAG 检索工具
- **代码位置**：`src/backend/engine/setup_chat/research.py:81` 与 `src/backend/engine/setup_chat/research.py:112`
- **问题描述**：
  - `@tool recall_research` 为同步函数，执行 `get_research_repo().query(topic)` 在主线程跑 embedding 检索。
  - `@tool async def web_search` 虽然是 `async def`，但在 L112 入库时直接同步调用 `get_research_repo().upsert(...)` 批量计算 embedding 并写入 ChromaDB。

---

## 💡 已完成异步线程池包装的路径 (复核确认已不在重灾区)

与 TODO.md 记录相比，部分模块**已经落地**了线程池异步化：

- **小说导入 Map-Reduce 批量入库**：`src/backend/engine/setup_chat/novel_import.py:168` 已使用 `get_research_repo().replace_for_source_async(...)` 封装 `asyncio.to_thread`，数十条 Chunk 批量入库时不会卡死主线程。
- **Story Sandbox 记忆召回**：`src/backend/engine/story_sandbox/graph.py:298`（`_build_recall_opening_node` / `_build_recall_node`）均已采用 `await asyncio.to_thread(recall_relevant_context, ...)` 异步化。
- **实体匹配 (Aho-Corasick)**：`src/backend/engine/memory_recall/entity_index.py` 使用了 C 扩展的 AC 自动机（`ahocorasick.Automaton`），多模式子串匹配为亚毫秒级耗时。

---

## 💾 次要同步阻塞点 (磁盘 I/O / SQLite)

1. **章级 Checkpoint 同步 SQLite 操作**
   - `src/backend/engine/author_loop/dialogue_mode/chapter_checkpoint.py:20` 直接同步使用原生 `sqlite3.connect` 打开磁盘文件读取。由于数据库文件较小，耗时一般在数毫秒级，但仍属同步磁盘 I/O。
2. **事件日志 & 召回 Cooldown 同步 JSON 读写**
   - `src/backend/engine/memory_recall/event_log.py` 在生成流程中频繁做同步 `json.load` / `json.dump` 文件读写。

---

## 📌 修复建议与优先级

1. **P0 (对话热路径)**：修改 `src/backend/engine/author_loop/dialogue_mode/react_graph.py:141`，将 `recall_relevant_context` 包装为 `await asyncio.to_thread(recall_relevant_context, ...)`。
2. **P0 (Setup Chat 逐轮热路径)**：在 `src/backend/engine/setup_chat/memory.py:597` 处将 `route_tool_names` 的向量推理过程异步化，或利用 `asyncio.to_thread` 丢入线程池。
3. **P1 (工具封装)**：在 `src/backend/repositories/chroma_repositories.py` 中为 `query` / `upsert` 提供统一的 `_async` 异步封装版本，避免各个消费方重复写 `asyncio.to_thread`。
