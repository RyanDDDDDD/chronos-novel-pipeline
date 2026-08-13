# Chronos 后端引擎核心 (Backend Engine)

本目录包含 Chronos 叙事引擎的核心控制逻辑、大模型交互层及数据供给体系。系统采用高度解耦的分层架构，以确保生成长文本时的物理一致性与逻辑严密性。

---

## 📂 目录结构与分层职责

### 1. `api/` — 接口网关层
- **MessageHub**：FastAPI 单一入口，WebSocket/REST 通信与事件重放。
- **services/**：MessageHub（后台任务+WS）、章节目录、pipeline 档案、主笔 skill 配置。

### 2. `engine/` — 创作引擎核心
- **author_loop/**：主笔逐段写作循环（决策→skill→落字→守卫→摘要→检查点）。
- **setup/**：world/cast/plot 设定构建。
- **execution/**：**AgentHook** IoC 契约 + 共用原语（embed_json/review）。
- **archive/**：设定层角色档案构建（timeline）。

### 3. `domain/` — 业务实体层
- 选项偏好统计（`stats.py`）、章节用量清理（`usage.py`）。

### 4. `context/` — 知识与上下文供给层
- **ContextRegistry** + **indexers/** + **providers/** + **dialogue/**：声明式并发装配预注入数据。

### 5. `llm/` — 大模型基建层
- 流式调用、Prompt 分层组装、Token 日志落盘。

### 6. `rag/` — 台词向量检索（可选能力）
- Chroma 建库 + 桶级混合检索，服务 dialogue 扩写。

### 7. `shared/` / `utils/` — 横切基建
- 日志（`shared/log.py`）、路径 SSOT、配置、文本后处理、报表。

---

## 📑 分目录文件级索引

| 目录 | 职责 | 文件级文档 |
|------|------|------------|
| `api/` | 接口网关（WS/REST） | [`api/README.md`](api/README.md) |
| `api/services/` | MessageHub、章节目录、pipeline 档案 | [`api/services/README.md`](api/services/README.md) |
| `engine/` | 主笔循环、设定/档案构建、agent 契约 | [`engine/README.md`](engine/README.md) |
| `engine/author_loop/` | 主笔逐段写作循环 | — |
| `engine/setup/` | world/cast/plot 设定构建 | — |
| `engine/execution/` | **AgentHook 契约** + 共用原语 | [`engine/execution/README.md`](engine/execution/README.md) |
| `engine/validator/` | Agent 包 / 上下文 / plot preflight | [`engine/validator/README.md`](engine/validator/README.md) |
| `engine/archive/` | 角色档案 timeline 构建 | [`engine/archive/README.md`](engine/archive/README.md) |
| `engine/modes/` | 主笔 skill 配置 | [`engine/modes/README.md`](engine/modes/README.md) |
| `context/` | Registry、预注入格式化 | [`context/README.md`](context/README.md) |
| `context/indexers/` | Lore/Plot 内存索引 | [`context/indexers/README.md`](context/indexers/README.md) |
| `context/providers/` | ContextProvider 实现 | [`context/providers/README.md`](context/providers/README.md) |
| `context/dialogue/` | 台词链脚手架 | [`context/dialogue/README.md`](context/dialogue/README.md) |
| `llm/` | LLM 路由、Prompt、日志 | [`llm/README.md`](llm/README.md) |
| `domain/` | 用量 / 偏好统计 | [`domain/README.md`](domain/README.md) |
| `rag/` | 台词向量检索 | [`rag/README.md`](rag/README.md) |
| `shared/` | 引擎日志 | [`shared/README.md`](shared/README.md) |
| `utils/` | 配置、路径、文本工具 | [`utils/README.md`](utils/README.md) |

**根文件**：
- `main.py` — WebUI 启动入口（FastAPI + Vite）。
- `shared/log.py` — `setup_engine_logger`。

> 引擎↔agent 扩展契约以 `docs/AGENT_PACKAGE.md` 为权威；本层 README 描述实现位置与调用链。

---

## 🚀 架构哲学

1. **逻辑与数据物理隔离**：核心引擎不持有具体设定，上下文通过 Registry 动态生成。
2. **引擎–插件解耦 (IoC)**：调度对具体 agent 零认知，全程经 `AgentHook` 多态契约；策略下沉各 agent 包。
3. **确定性规训**：结构化约束（插槽、DNA、位阶）收敛 LLM 随机性。

---
*Chronos Backend | 构建工业级长文本生成的确定性标准*
