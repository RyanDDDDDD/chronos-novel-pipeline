[English](README.md) | **中文**

# Chronos

**本地优先的多智能体长文本叙事引擎。** 用软件工程的确定性（主笔循环、内存状态、检查点续写、声明式上下文）规训大模型在长程生成中的非确定性。

当前版本：**主笔引擎时代**（author_loop dialogue_mode · setup_chat 设定共创 · 引擎–插件 IoC）

---

## 项目缘起与愿景

Chronos 的设计融合了三方灵感：

- **[Dify](https://dify.ai/)** 的工作流编排思路——把复杂任务拆成可编排、可观测的多步节点；
- **酒馆（SillyTavern）** 的可插拔自定义哲学——自由组装/替换/排序流水线节点而非绑定固定模板，其 World Info/Lorebook 式"按需检索注入设定"也启发了跨章伏笔记忆的设计方向；
- **AutoNovel**（NousResearch）的长程质量控制思路——反 AI 腔（anti-slop）机械拦截与整叙事单元批量产出，均已评估/部分借鉴进现有反 AI 腔机制与主笔粒度实验。

长篇章节创作需要**跨段落实体状态**、**人机协同选题**与可续写的检查点，因此我们自研专用编排内核。

长期目标是**可完全自定义的创作工作站**：

- **引擎只认契约**：调度层通过 `AgentHook` 与 manifest 元数据接线；
- **Agent 即插件**：`hooks/packages/<包名>/`（prompt + hook + assets）；
- **编排可存档**：多套 pipeline 档案可切换，skill 启用由 WebUI「Pipeline 配置」视图配置；
- **人机协同内建**：Setup Chat 设定共创逐任务停顿征询用户，主笔逐 beat 写作循环内可插入细节反馈与复核。

---

## 它解决什么问题

长文本不能靠「一次 Prompt 写完」。Chronos 把章节生产收敛为**主笔逐 beat 写作循环**：Setup Chat 对话式预建骨架/beats → LangGraph 整章图逐拍出文 → 状态推演滚动 → 检查点续写。创作者可在设定共创与写作过程的各交互点介入，在自动化与人工干预之间取得平衡。

---

## 核心机制

### 主笔写作循环

1. **设定共创**：Setup Chat 对话式构建 world/cast/plot，并将大纲预建为分 beat 骨架。
2. **整章图**：`dialogue_mode` 下的 LangGraph 按 beat 执行（`task_packet` → `author_prose` → `review_stage` → `advance`），逐拍写手落字后过 `review_stage` 保真/字数/文风审核门（未过重试 ≤2 次回退 author_prose，通过或重试耗尽后才做状态推演与跨章归档）。旧「决策 LLM 选 skill → 用户选方案」的逐段范式已退役。
3. **一致性**：archive 状态守卫 + 前文尾窗，跨拍记忆随距离坍缩为概要，checkpoint 不受影响。
4. **成稿**：`第N章_主笔.md`。

详见 [ARCHITECTURE.md](docs/ARCHITECTURE.md) 与 [protocol-contract.md](docs/protocol-contract.md)。

### 引擎 ⇄ 插件（IoC）

调度核心通过 `AgentHook` 契约调用各 skill 的扩展点；新增 skill 只需实现 hook 并接线进 Pipeline 配置——引擎零改动。

### 上下文供给

`ContextRegistry` 按 `ContextRequest` 并发装配互称、声线等数据；author_loop 直接调用。四阶段 AgentHook context 声明链已退役。

---

## 架构一览

```text
┌─────────────────────────────────────────────────────────────┐
│  WebUI（React 19 + Vite · React Query · React Router · RTK） │
│              主笔对话流 · Setup Chat · Pipeline 配置          │
│                （桌面壳：Tauri，见「快速开始」）               │
└──────────────────────────┬──────────────────────────────────┘
                           │  REST + WebSocket
┌──────────────────────────▼──────────────────────────────────┐
│  api/          hub.py（MessageHub）· routes.py · services/   │
├─────────────────────────────────────────────────────────────┤
│  engine/author_loop/dialogue_mode/   LangGraph 整章图         │
│    task_packet → author_prose → review_stage → advance       │
│  engine/setup_chat/   设定共创（world/cast/plot 对话构建）    │
│  engine/setup/        world · cast · plot 批量构建（legacy）  │
│  engine/execution/    AgentHook 契约                          │
├─────────────────────────────────────────────────────────────┤
│  context/      ContextRegistry（零 RPC 数据供给）             │
│  hooks/packages/   Agent 插件                                │
└─────────────────────────────────────────────────────────────┘
```

> **历史**：V8–V11 的 LangGraph DAG 段级打标流水线、以及后续「决策选 skill → build_options 出方案」的逐段范式均已退役；manifest 仅作 agent-meta 与 skill 接线元数据，不驱动运行时拓扑。

---

## 快速开始

```powershell
uv sync
copy config\config.example.json config\config.json
uv run python run.py --dev    # 单终端前后端（engine+gateway 双进程 + Vite）
# 或：npm install && npm run dev   （单进程，= run.py --sequenced --no-browser）
# 桌面壳调试：npm run tauri:dev；打包发行：npm run tauri:build
```

详见 [GETTING_STARTED.zh-CN.md](GETTING_STARTED.zh-CN.md)。

---

## 文档

| 文档 | 内容 |
|------|------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 架构总纲 |
| [docs/AGENT_PACKAGE.md](docs/AGENT_PACKAGE.md) | Agent 包规范 |
| [docs/TECHNICAL_JOURNEY.md](docs/TECHNICAL_JOURNEY.md) | 技术演进白皮书 |
| [docs/README.md](docs/README.md) | 文档索引 |

---

*Chronos | 主笔引擎 | 工业级长文本创作*
