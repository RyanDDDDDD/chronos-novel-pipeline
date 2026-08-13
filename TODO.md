# 项目开发看板 (Chronos Engine · 主笔范式)

> 旧 DAG 流水线（synthesis / dialogue_weaver / 多 rubric window_judge / TAG 标注师 / manifest 节点编排）已退役，
> 主笔逐段写作循环（architect 骨架 → 逐 beat 决策/skill/落字/细节修缮 + 状态滚动）为当前范式。
> 2026-06-23 盘点：已删除引用退役代码（`window_judge_batch`/`refine_manager`/`synthesis_rewrite`/
> `is_annotator`/`tagging_base`/`langgraph` 等）的过时 ticket，及已落地项（React Query/Router、beat 级断点续跑）。

---

## 📅 当前 Sprint

### ⚫ T0 — 一致性 / 未完成迁移

### 🔴 P0 — 创作质量（主笔范式热路径）

- [ ] **能力节点（剧情选项生成等）身份设定可配置化与 Hook 覆写机制（2026-08-04 记）**：目前 `direction_suggest.py` (`suggest` 节点) 等节点的 Prompt 缺失独立的角色身份设定，且硬编码在代码中无法修改。参照 `setup_chat` 中 `chat_identity` 节点的范式，将能力节点的 System Persona（身份设定）全面进行可配置化改造。
  - **UI 可视化配置暴露**：在流水线/沙盒的节点配置抽屉面板中，增加「身份设定/系统 Prompt 覆写」自定义编辑框，允许创作者随时修改或覆盖该节点模型的专家角色定位；
  - **Hook 覆写支持 (Hook Integration)**：接入 Hook 钩子体系（参照 `hooks/content_packs/`），允许插件或内容包（如特定题材向内容包）通过 Hook 动态注入或替代节点的身份设定 Prompt；
  - **优雅降级与默认预设**：未配置自定义覆写或 Hook 时，自动降级并应用内置的精修专家身份预设（如 `你是一位精通戏剧冲突、故事张力与网文节奏的资深剧情规划师...`）。

### 🟡 P1 — 资产与体验

- [ ] **多小说运行环境子进程 (Subprocess Worker) 隔离与物理内存彻底回收机制（2026-08-04 记）**：针对 CPython 内存释放后因 PyMalloc Arena 碎片化难以直接将物理内存 (RSS) 归还给 OS 的底层特性，引入**子进程隔离架构 (Process-per-Novel Worker / Pool)**：
  - **子进程 Worker 隔离与销毁 (彻底归还 OS 内存)**：将每本小说的运行/加载环境下沉至独立的 Subprocess / Worker Process 中。LRU 触发淘汰时直接 `terminate()` / 销毁该小说对应的子进程。依靠 OS 级进程销毁机制彻底回收该进程占用的 100% 物理内存 (RSS 归零)，从根本上解决 CPython 内存驻留与碎片化痛点；
  - **进程间通信 (IPC) 与状态同步**：主进程保留无状态轻量调度与 REST/WS API 网关，与小说 Worker 子进程间通过轻量 IPC / JSON 消息管道通信。
- [ ] **小说目录栏设定菜单新增「问题与意见反馈」与公钥加密邮件发送（2026-08-03 记）**：在侧边栏小说目录（NovelRail）底部的「设定」按钮（`NovelRailSettings.tsx`）弹出菜单中新增「问题与意见反馈」选项：① **前端 Modal 交互与密文打包**：弹出 Feedback Modal 模态框，包含文本反馈框、反馈类型选择，以及“是否包含运行日志”勾选框。发送前在本地使用**开发者公钥（Public Key）**将反馈内容与日志统一加密成不可读的密文文本（Base64/Ciphertext）；② **后端无状态邮件发送**：新增 `POST /api/feedback/submit` 路由，将密文发往项目专用邮箱。**接收邮箱及 SMTP 凭据绝对禁止硬编码在前端或后端源码中**，必须通过系统环境变量（如 `FEEDBACK_TO_EMAIL`, `FEEDBACK_SMTP_USER`, `FEEDBACK_SMTP_PASS`）在运行时安全读取；③ **开发者本地解密**：开发者在专用邮箱收到密文后，在本地电脑使用对应的**私钥（Private Key）**进行解密与日志分析，实现兼顾宣传公信度、防爬虫骚扰与端到端隐私安全。
- [ ] **流水线节点拓扑图扩充可配置节点（草稿/伏笔RAG/反AI腔/实体提取）（2026-08-03 记）**：对 `features/pipeline/` 下三大 Tab 视图（主笔 runtime、对话 skeleton、故事沙盒 sandbox）拓扑节点进行完整扩充与显式暴露：① **主笔 Tab**：新增 `dialogue_draft`（对话草稿预拟节点，支持独立配置轻量模型）、`context_rag`（伏笔/记忆召回节点，支持配置向量 Top-K 与冷启动间隔）、`style_guard`（反 AI 腔硬件拦截节点，支持配置过滤级别与重试上限）；② **对话 Tab**：新增 `entity_extractor`（大纲设定实体提纯落盘节点）；③ **沙盒 Tab**：在 `prose` 前可视化展现草稿与 RAG 的真实并发拓扑。
- [ ] **图生文 (Vision) 模型与本地 ComfyUI 引擎接入方案（2026-08-10 记）**：前端/后端 UI 与 API 配置接口已准备好，后续需完成与本地 ComfyUI 引擎的真实对接：
  - **图生文 (Vision) 识别与 Tag 提纯**：接入视觉模型（Vision Model）处理多页参考图/角色插图，自动提纯视觉特征并生成角色 Visual Tags；
  - **本地 ComfyUI 通信适配器**：基于 HTTP/WebSocket 实现本地 ComfyUI 客户端 Provider（支持工作流 Prompt 动态填充、任务提交、进度监听/轮询、生成图片落盘与角色立绘绑定）。
- [ ] **故事沙盒剧情扩展 Skill 建议迁移为单次 LLM 调用（2026-08-10 记）**：目前 `message_hub.py` 中的 `_run_skill_agent`（配合 `skill_suggest.py`）使用无状态的 `create_react_agent` 执行剧情扩展 `/skill-name` 命令。后续参照 `fix_agent_runner.py` 范式，将其重构迁移为单次 LLM 调用（High-Effort Thinking + 并行 Tool Call / 单次提取），彻底消除 ReAct 递归与不必要的中间轮次开销。
- [ ] **Author Loop / Story Sandbox 剧情插画生成（Novita API 生图，2026-08-10 记）**：基于现有 Novita 生图基础设施，在主笔（Author Loop）及故事沙盒（Story Sandbox）视图中接入剧情插画生成能力：支持自动从当前场景/段落提取 Prompt，调取 Novita 异步生成剧情插画，并在正文与沙盒交互流中进行关联呈现与落盘。
- [ ] **基于 IP-Adapter + 结构化 Visual Tags 的角色插画形象一致性控制（2026-08-10 记）**：在 Novita / 生图 API 调用链中引入多重一致性锁定机制，防止剧情插画中角色形象偏离：① **参考图特征注入 (IP-Adapter)**：在 Task Payload 中挂载角色参考图 URL 及 IP-Adapter 权重，直接在 Attention 层注入面部与造型特征；② **结构化 Visual Tags 锚点**：基于 Vision LLM 提纯的固定特征 Tag 组合，在插画生成时自动拼接作为 Prompt 强约束锚点；③ **区域提示控制 (Regional Prompting)**：支持多角色共存插画场景下的掩码控制，避免角色间视觉特征混淆与污染。
- [ ] **基于单图 Multi-View 渲染 + OpenPose 骨架约束 + 智能切片的角色卡多视角设定图生成（2026-08-10 记）**：在角色卡创建与精修环节，支持一次性生成统一形象的多视角（正面、侧面、背面、全身）角色设定图：① **单图 Multi-View 同屏渲染**：采用 Model Sheet 提示词与宽屏分辨率（如 2048x1024），确保所有视角在同一 Latent 潜空间内共享 Feature Map 避免细节画偏；② **OpenPose 骨架姿态强约束**：通过 ControlNet 传入预设的 3/4 视图骨架模板，物理级限定正/侧/背姿态布局；③ **后端 Smart Crop 自动切片**：生成横版大图后，后端自动进行图像目标识别与按比例裁切，输出 `front.png`, `side.png`, `back.png`, `full_body.png` 并关联绑定角色卡。
- [ ] **Visual Tags 视觉标签体系升级：多模态图反推与 LoRA 扩展元数据（2026-08-10 记）**：升级现有 `visual_tags.py` 与 `CastCharacter` 数据结构：① **Vision 多模态反推**：支持传入参考图直接由 Vision LLM 反推抽取精准 Tag 并写入 `portrait_visual_tags`；② **LoRA 静默装配元数据扩展**：在角色模型中扩展 `lora_config` 与 `reference_image_url` 字段，实现生图链路对自定义 LoRA 与参考图的自动组装。

---

## 🧪 运维与测试

---

## 🌌 未来演进

### 待实现设计（spec 在库未落地）

- [ ] **通用线程池设施（原「EventScheduler 支持多进程执行」，2026-07-14 记，2026-07-16 补充具体场景，仍先不做）**：现状 `api/services/scheduler.py::EventScheduler` 单进程单 event loop，靠协程切换（非并行）实现并发。2026-07-14 记录时的判断是"当下无具体场景"——2026-07-16 讨论小说导入分片提炼时找到了一个**真实存在的阻塞点**：`rag/embedding.py::get_embedding_function()` 是本地跑的 `SentenceTransformer`（`BAAI/bge-small-zh-v1.5`），`rag/research_index.py::upsert_research` 同步调用它做 embedding 计算，整条链路（`repositories/chroma_repositories.py::ChromaResearchRepository.upsert` → `upsert_research` → embedding function）没有一处 `await`，是实打实会占住唯一 event loop 的同步阻塞计算（`engine/setup_chat/attachment_tool.py::_store_summary_for_recall` 现在就是这样直接同步调用）。当下量小（一条 ResearchChunk）感觉不出来，但小说导入分片方案（见 `docs/superpowers/specs/2026-07-16-novel-import-chunked-mapreduce-design.md`）一旦落地要一次性 upsert 几十条细粒度 chunk，阻塞时长会线性增长。**技术结论（已讨论清楚,实现时直接用）**：这类同步阻塞代码需要的是 `loop.run_in_executor()` 配 `ThreadPoolExecutor`（PyTorch 张量运算会在计算阶段释放 GIL，线程池足够，不需要进程池——进程池还要考虑 SentenceTransformer 模型在每个子进程重新加载一份的代价，没必要）；跟"EventScheduler 该不该支持多进程"是两个问题——EventScheduler 是定时器（`when` 堆排+periodic重排/once丢弃语义），跟"同步阻塞代码要不要扔进线程池"是正交的两件事，不要把两者耦合进同一个"升级"里。**范围仍然是"以后做"**：这次小说导入分片方案的 spec 里不顺带做这个线程池包装（用户 2026-07-16 明确拍板留到以后，归为"要不要给项目加通用线程池设施"这个更大话题），只在这里记录已经想清楚的技术结论，避免以后重新分析一遍。

**概念澄清（同一次讨论敲定）——问题本质是"排队等待"不是"IO等待"**：单进程单线程下，其他协程的"等待"分两种性质完全不同：①真·IO 等待（网络请求已发出，等对方返回，不占用这个线程，多个协程的这类等待可以完全重叠——Map-Reduce 阶段并发发多个 LLM 请求就是吃这个红利，不需要线程池）；②排队等待（IO 已经好了，但线程正被另一个同步阻塞的协程占着，只能干等它让出）。真正需要线程池解决的只有第②种——而第②种之所以会发生，根源就是有协程在执行同步阻塞的重 CPU 代码（没有一处 `await`，不会主动让出线程）。

**2026-08-04 最新全仓盘点结论（详见 [`CPU_BOUND_ANALYSIS.md`](CPU_BOUND_ANALYSIS.md)）**：
1. 🔴 **主笔范式 / 对话模式热路径** (`engine/author_loop/dialogue_mode/react_graph.py` L141)：`recall_relevant_context` 同步调用 `SandboxVectorMemoryRepository.query()`，在协程节点内同步跑 PyTorch Embedding。
2. 🔴 **Setup Chat 工具动态路由** (`engine/setup_chat/memory.py` L597 & `tool_router.py` L88)：Pre-model hook 每轮对话同步跑 Embedding。
3. 🟡 **Setup Chat RAG 工具** (`engine/setup_chat/research.py` L81 / L112)：`recall_research`（同步工具）和 `web_search` 入库阶段同步跑 Embedding。
4. 💡 **已优化/不在重灾区**：`novel_import.py` 已用 `replace_for_source_async` 异步化；`story_sandbox/graph.py` 召回节点已包 `asyncio.to_thread`；`entity_index.py` 已使用 AC 自动机（亚毫秒级）。

- [ ] **`auto_build_setup` 批量草稿审查机制与新版后台 fix agent 机制不统一（2026-08-09 记，
  `docs/superpowers/specs/2026-08-09-setup-review-fix-agent-design.md` 落地时明确排除，以后看看怎么
  优化）**：`_draft_one_character`（`auto_construct.py`）走的是"草稿-审查-重试"循环——角色未落盘前
  先在内存里反复生成草稿、送 `gate_character` 审查，不过就把 rubric 拼回 prompt 重新生成，通过了才
  一次性写盘（schema 校验失败与质量评审不过各自独立计数重试，各有上限）；而上面那份新 spec 落地后，
  交互式 `add_character`/`edit_character`/世界观维度写入/剧情骨架整章审查会统一变成"写入前移 → 后台
  review（沿用既有 map-reduce）→ 专用单轮 fix agent 就地修 → 无论结果都通知 chat agent"。两者共用同
  一套评分 hook（如人物的 `SETUP_CAST_HOOK_NAMES` 四维度），但外层控制流是两套不同的机制，长期看是
  重复维护。当时决定批量草稿阶段不动，是因为：① 批量构建下游步骤（如
  `generate_edges_for_new_character` 生成关系边、种族名要匹配世界观声明的种族）依赖"已定稿角色"这个
  前提，若改成先写后台修，这些下游步骤要么要跟着改造成后台任务链、要么继续基于一个"暂定版"角色跑，
  链路会变复杂；② 批量构建本身就是一整个异步工具调用，用户是在等它跑完，不存在"卡住交互轮次"的问题，
  新机制要解决的痛点在这里不成立。以后若想统一，需要先想清楚上面①这个依赖时序问题怎么处理。
- [x] **后端统一缓存层（`utils/cache.py`，2026-08-10 记，四个阶段全部完成merge dev，第⑤阶段
  用户拍板明确不做）**：现状后端缓存全是各模块手写的"模块级变量+懒加载+显式 reset 函数"，无共享
  抽象，重复但**不是正确性问题**（不引入 Redis——单进程单 event loop 架构下没有跨进程共享缓存的
  真实场景，Redis 解决的是多进程/多机共享，代价（外部服务、用户本地要装要起）相对于当前需求不成
  比例）。**全量盘点（10 处）最终结果**：
  1. ✅ `utils/config.py::get_config()` — 迁移到 `LazyCache`，`path` 参数"只在首次加载生效"的
     现状怪癖原样保留未修（`2026-08-10-unified-cache-layer-config-content-packs-design.md`，
     commit `a571f7e0`，merge `34dcb1b5`）；
  2. ✅ `llm/factory.py::_cloud_llm_cache`（原 `_cloud_llm_instance`）— 迁移到 `LazyCache`，
     `reset_cloud_llm_cache()` 级联清空 style_guard 缓存的行为不变
     （`2026-08-10-unified-cache-layer-llm-factory-design.md`，commit `3f133354`，merge `e5c27ad2`）；
  3. ✅ `llm/factory.py::_local_node_llm_cache` — 迁移到 `KeyedCache`（同上 commit）；
  4. ✅ `llm/factory.py::_registry_llm_cache` — 迁移到 `KeyedCache`（同上 commit）；
  5. ✅ `llm/factory.py::_style_guard_llm_cache`（原 `_style_guard_llm_instance`）— 迁移到
     `LazyCache`（同上 commit）；
  6. ✅ `repositories/sqlite_store.py::_connections`（原 `_clients`）— 按 db 路径键控的
     `sqlite3.Connection`，迁移到 `KeyedCache`（`on_evict=conn.close`），`get_connection`/
     `close_connection`/`SqliteStore.close()` 外部行为零改动
     （`2026-08-10-unified-cache-layer-sqlite-migration-design.md`，commit `6bea6233`）；
  7. ✅ `context/content_packs.py::_packs_cache`（原 `_CACHE`）— 迁移到 `LazyCache`
     （同①的 commit `a571f7e0`）；
  8. ✅ `engine/memory_recall/entity_index.py::_automaton_cache`/`_character_automaton_cache` —
     两个按 novel_id 键控的 AC 自动机迁移到 `KeyedCache`；配套磁盘快照记账簿
     `_persisted_entries`（每次构建/恢复都无条件覆盖写入，不是"懒加载"形状）与临时构建期上下文
     标志 `_building_character_names`（不是缓存）**有意不迁移**，继续留作模块级 dict/global；
     `restore_persisted_automata` 的写入方式从"无条件覆盖"改成 `KeyedCache.get()` 的"只在 miss
     时才加载"——有意的、范围极窄且只会更安全的行为偏差（原实现在"warmup 还没轮到但已有实时请求
     抢先建好缓存"这个极窄竞态窗口里会用可能陈旧的磁盘快照覆盖新鲜的实时构建结果，新写法直接
     排除了这个风险）。`KeyedCache` 顺带新增了 `clear()`（供测试模拟冷重启用）
     （`2026-08-10-unified-cache-layer-entity-index-design.md`，commit `7af9bdae`）；
  9. ❌ `rag/embedding.py::get_embedding_function()` — **确认不迁移**；
  10. ❌ `engine/execution/style_guard.py` 的 `forbidden_words_text()`/`get_compiled_patterns()`
      ×2 — **确认不迁移**。

  **9/10 不迁移的原因（2026-08-10 用户拍板）**：这三处跟 1-8 性质不同——`get_embedding_function()`
  的模型名是硬编码常量，`forbidden_words_text()`/`get_compiled_patterns()` 的输入是硬编码的
  `WORD_THRESHOLDS`/`_NEGATIVE_SENTENCE_PATTERNS` 模块级常量，三者都不读 config/disk/用户输入，
  只能靠改源码+重启才能变——不存在"运行期需要失效"这个场景，`@lru_cache(maxsize=1)` 已经是
  完全合适的实现，迁移到 `LazyCache` 不会带来任何失效能力上的收益，纯粹是风格统一，不值得再起
  一轮 spec+plan+Cursor 派发的成本，维持现状。

  **✅ 缓存层接口本体**：`src/backend/utils/cache.py` —— `LazyCache[T]`（懒加载单例，可选
  `on_evict` 钩子，`get()` 支持按次调用 loader 覆盖）+ `KeyedCache[K, T]`（按 key 索引，loader
  按次调用传入而非构造时固定，另有 `invalidate`/`discard_if`/`clear`）。两个都只做 sync
  （`AsyncLazyCache` **明确不建**——全部落地的 8 处 loader 都是同步快操作，YAGNI）。

  **实际执行顺序跟最初设想不同**：原计划①是先用 config.py/content_packs.py 两个最简单单例场景
  验证接口，后来因为"要不要把 on_evict 也用来救 Novita 目录刷新"这个讨论，改成直接拿 sqlite 连接
  缓存（真实需要 eviction 钩子）当第一阶段验证场景，config.py/content_packs.py 变成第二阶段才做。
  Novita 目录缓存**确认不接入**这套抽象——它是"外部事件主动推"而非"lazy get-or-load"，语义跟
  `on_evict`（表达"清空之后"）对不上，维持自己的模块级 `_cache`
  （`2026-08-10-novita-model-catalog-cache-design.md`）。

  **sync/async 接口设计已实测调研，结论：两套对称接口（`LazyCache` sync + `AsyncLazyCache` async），
  不做"全部 async 化"**。曾考虑过统一成 async-only（省得维护两套），实测调用点发现风险不对称：
  `get_config()` 的同步调用方集中在 `llm/factory.py` 四个懒加载单例缓存 + `main.py` CLI 入口，浅、
  可控；但 `content_packs.py` 的同步调用方有好几条**多层同步调用链**——`cast_validator.py` 的角色
  校验树、`tool_args.py::_build_character_fields_args()`（用 `custom_fields()` 等动态构建 Pydantic
  `Field(description=...)`，docstring 明确写着"绝不能缓存，每次都要重建"，这种上下文塞 `await` 很
  别扭）、以及 `cards.py::render_custom_fields_block()` 打头的角色卡渲染树（贯穿 8+ 个同步 prompt
  构建文件）。把这些都改 async 会级联穿透 validator/Pydantic schema 构建/正文渲染这几块核心逻辑，
  代价远超"给缓存换个写法"本身，故维持两套接口分工。`AsyncLazyCache` 最终没有建（YAGNI，全部
  落地阶段的 loader 也都是同步的）。
- [ ] **本地模型 Offloading 策略**：LOCAL 执行已通；完整云→本地分流（模型选型 / VRAM 预算）待定。`docs/notes/local_model_offloading_strategy.md`。

### 参考 spark-arc-studio（2026-08-02 调研，同类多智能体创作 IDE，候选方向未拍板）

调研对象：https://github.com/letmeow/spark-arc-studio（Python+FastAPI+LangGraph 后端 / Vue3+Tauri2 前端，编剧/小说创作 IDE）。以下几点和我们现有痛点/待办直接对得上号，按价值排序：

- [ ] **叙事 GraphRAG（`docs/narrative-graphrag-optimization-2026.zh-CN.md`）——最值得深挖**：用 MultiDiGraph 建模实体/事件/状态变化/知识秘密/关系变化/线程（伏笔目标），每条边带 `valid_from/valid_to`、来源、置信度、极性，支持"按章节截断查询"防止未来剧情泄露，显式追踪"知情边界"（谁在何时知道什么），自动诊断"缺失桥接/循环因果/结果无诱因/长期未推进线程"。检索走分层混合路由：简单问题走语义+BM25，复杂多跳（跨章因果/知情边界/长期线程）才落到图查询，返回"原文证据包"而非固定答案，Agent 保留最终判断权。直接命中我们现在用补丁式方案在应付的两处：[[sandbox-chapter-scope-guard-fix-and-reset-caveat]]（未来章节记忆泄漏，靠 state-gating 补丁）和 [[novel-import-exhaustive-retrieval-tools-status]]（穷举检索答不全）——他们把"时效裁剪+知情边界"做成图的一等属性，比我们事后补 guard 更系统。**未拍板**：是否值得为此引入图数据库/图查询层，还是先在现有 `LoreRepository`/`ContextRegistry` 上加时效字段做轻量版。

- [ ] **三模态 Prompt 协议（system/chat_system/pipeline_system）——直接对应 [[author-chat-agent-todo]]**：同一个 agent 的 yaml 里声明三种互斥模态——`system` 服务业务路由结构化输出，`chat_system` 服务聊天路由自然对话，`pipeline_system` 服务"导演委派、一次落盘+简报"，路由层按入口选择，委派场景强制走 pipeline_system（首句须声明受众是导演而非用户，防止 LLM 错入对话模式）。我们悬而未决的"主笔改造成 chat agent"待办本质就是要让同一个 author agent 既能聊天软锁交互、又能被 plan_runner 一次性委派落盘——这套三模态收口是现成的参考实现模式，比我们目前空白的设计更具体。

- [ ] **风格克隆自我对抗闭环（`docs/architecture.md`）**：长文本切 30k tokens 块 → 统一分析器逐块 7 维度分析、块间传"剧情概括"保持上下文 → ValidatorAgent 自己仿写 → 若生成文字带 AI 特征，自动生成负向约束（禁用特定转折词/句式）→ 图灵回测循环迭代收敛。本质是把我们现在**人工**做的事自动化：[[style-guard-negative-pattern-curation]] 目前靠用户贴 AI 腔例句手动泛化成 DSL 正则塞进 `style_guard.py::_NEGATIVE_SENTENCE_PATTERNS`。如果要减少人工维护负担，"生成→检测→固化约束"的自对抗循环值得参考，但要先评估我们的负例库量级是否已经到了值得自动化发现新模式的地步（目前是"用户偶尔贴例句"驱动，不是持续痛点）。

- [ ] **StoryMemoryFacade 防写坏模式**：存档时立即写确定性快照保证下一场即时可见，后台异步 LLM 结构化抽取用"来源哈希校验"防止旧结果覆盖新状态，抽取失败不阻断主写作流程。是个通用的异步补写防御模式——我们目前状态推演是同步 in-loop（`derive_states`），没有类似的异步抽取竞态问题，但如果以后给状态系统加后台/异步抽取（比如 [[state-system-theme-decoupling-roadmap]] 演进方向），这个"哈希校验防 stale 回写"的模式直接可以搬。

- [ ] **`search_chat_history` 只读检索工具**：字面搜索+正则搜索双模式（正则限 1000 字符/200ms 超时），checkpoint 和系统消息排除在检索范围外防止回查再撑爆上下文，返回前 8 个命中的相邻对话轮次带消息 ID 和分页游标。我们的 `_llm_view` 压缩（>2 拍前整拍坍缩为骨架概要）目前没有对应的"翻旧账"工具——概念简单，如果以后压缩后的信息丢失成为真实痛点（目前未观察到），可以照此加一个。

- [ ] **Critic 的 S/A/B/C/D 分级呈现（非评估机制本身）**：不用伪精确分数，每条批评都挂原文引用+具体修改建议，维度含"AI 味感知"（解释腔、段尾升华）。跟我们的判官（[[prose-guard-semantic-style-judge-status]]）比，价值在于**呈现层**——分级+可追溯建议比单纯 pass/fail 对用户更友好，但这属于"要不要给用户暴露质量反馈 UI"这个更大的产品决策，非纯引擎改动，暂不单列执行方向。

**明确不借鉴（已验证不适合我们）**：Director SupervisorGraph 多 agent 委派（Muse/Lorebook/Showrunner/Scriptwriter/Critic 分工）——这条路我们在 [[setup-chat-multiagent-reconsideration-status]] 和 [[dialogue-beat-forward-continuity-status]] 都试过又主动退回单 agent（director 单 agent 直出、单线程 ReAct 整章循环），没有新证据不建议重新捡起。

### 远期架构愿景（留作设计参考，未立项）

通用叙事引擎(Worldpack 解耦)、双轨视觉小说工坊、ECS 插件大厅、事件驱动黑板架构、强类型 Pydantic 数据治理、本地 RLHF 数据飞轮、零代码自适应 MCP、Token 效率专项、高可用与安全体系。

---

*由 Chronos Engine 维护 | 主笔范式 | 2026-06-23 盘点*
