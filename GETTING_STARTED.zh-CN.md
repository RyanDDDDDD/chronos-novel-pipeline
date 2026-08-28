[English](GETTING_STARTED.md) | **中文**

# Chronos Engine 启动指南

Chronos 是受 **Dify 式工作流**启发、为**长篇章节创作**自研的多 Agent 编排引擎；目标体验接近**酒馆（SillyTavern）的可插拔自定义**——自由组装、替换、排序流水线节点，而非绑定固定模板。项目背景见 [README.zh-CN.md](README.zh-CN.md#项目缘起与愿景)。

---

## 环境要求

| 项目 | 要求 |
|------|------|
| Python | 3.12+（使用 `uv` 管理） |
| 包管理 | `uv`（替代 pip/venv） |
| Node.js | 18+ 及 `npm`（前端与桌面壳依赖） |
| 本地模型 | LM Studio / Ollama，建议使用 OpenAI 兼容接口 |
| 云端模型 | Anthropic / OpenAI / DeepSeek API Key (可选) |

安装依赖：

```powershell
uv sync
```

---

## 配置文件

所有参数通过 `config/config.json` 统一管理。首次使用：

```powershell
copy config\config.example.json config\config.json
```

### `config.json` 核心字段说明

```json
{
  "llm": {
    "cloud_model_id": "claude-opus-4-7",   // 云端文本模型 id（config/model_catalog.json 预设，或 custom_models 里的自定义条目）
    "custom_models": [],                   // 自定义模型（文本/图像生成均在此），见下方「API / 模型配置」
    "local_base_url": "http://localhost:1234/v1",  // 本地 LLM 地址（LM Studio / Ollama）
    "local_model": "local-model"
  },
  "api": {
    "model_api_keys": {},        // 按模型 id 存 API Key，如 {"claude-opus-4-7": "sk-..."}
    "search_provider": "tavily", // 联网检索提供商：tavily | baidu_qianfan
    "tavily_api_key": "",
    "qianfan_api_key": ""
  },
  "server": {
    "engine_port": 8776          // 内部引擎端口
  }
}
```

> 完整默认字段见 `config/config.example.json`；实际生效值是默认值与 `config.json` 深合并的结果（`src/backend/utils/config.py`）。

### API / 模型配置：四类能力各自独立

**文本生成、图像识别（识图）、图像生成（生图）、联网检索**是四条完全独立的配置路径，各自可以指向不同的模型和 API Key，互不影响：

| 能力 | 配置位置 | 生效方式 |
|------|----------|----------|
| **文本生成** | WebUI「服务配置」页 → 模型 → 文本 tab：选预设云端模型（`config/model_catalog.json` 里的 Claude / DeepSeek / Qwen / Gemini）或添加自定义条目（`llm.custom_models`，`provider` 为 `openai_compatible` / `anthropic`）；本地模型走「本地」tab（`llm.local_base_url` + `local_model`，LM Studio / Ollama，无需 Key）。API Key 按模型 id 存进 `api.model_api_keys` | 保存后立即热重载（重置云端 LLM 缓存 + 重建 setup-chat agent），无需重启 |
| **图像识别（识图）** | 不是独立 provider——从已配置的文本模型（云端预设或自定义，选一个支持视觉的）里挑一个，绑定到 WebUI「Pipeline 配置」视图里「图片识别」/「一键建设定」/「文本识别」等能力节点的 `model_ref`（按小说独立配置，存在该小说的 `author_loop_skill_prefs.json`） | 保存后下次调用即生效 |
| **图像生成（生图）** | WebUI「服务配置」页 → 模型 → 图像 tab：添加自定义条目（`llm.custom_models` 里 `provider: "image_gen"`），二选一：**Novita**（`service: "novita"`，checkpoint 模型列表实时拉取）或 **NovelAI**（`service: "novelai"`，填持久 API Token + 选固定模型档，需 NovelAI 订阅）。配好后绑定到「Pipeline 配置」视图「立绘生成」节点的 `model_ref` | Novita 保存 Key 触发一次目录刷新；NovelAI 无需刷新；绑定后下次生成生效 |
| **联网检索** | WebUI「服务配置」页 →「API 密钥」区：二选一 `search_provider`（Tavily 或百度千帆），填对应 Key（`api.tavily_api_key` / `api.qianfan_api_key`），`search_top_k` 控制单次返回条数上限 | 保存后立即生效 |

> **不要混淆**：RAG 检索用的 embedding 模型（`BAAI/bge-small-zh-v1.5`）是固定的本地 ONNX 模型（`src/backend/rag/embedding.py`，通过 FastEmbed 运行），跟上表「联网检索」（网页搜索）完全是两回事——不需要配置、不需要 Key，也不受 `search_provider` 影响。

---

## 快速启动

系统提供根目录的 `run.py` 作为统一入口，默认启动 WebUI 服务器。

```powershell
# 开发模式 — 单终端，Ctrl+C 同时关闭后端与 Vite（推荐，引擎+网关双进程）
uv run python run.py --dev

# 或使用根目录 npm（需先 npm install），单进程顺序启动（等价于 run.py --sequenced --no-browser）
npm run dev

# 生产模式（仅启动后端，手动访问 http://localhost:8775）
uv run python run.py

# 命令行调试模式（跳过自动打开浏览器）
uv run python run.py --no-browser
```

> **不要**在 `src/frontend` 单独 `npm run dev` 的同时另开终端跑后端：在前端终端 Ctrl+C 只会停 Vite，后端 `:8775` 会继续运行。请改用上面两种「单入口」方式之一。

启动后，在浏览器中选择章节并点击「启动主笔」即可开始写作循环。

---

## 主笔写作流程概览（Dialogue Mode）

当前系统采用 **对话驱动主笔循环（`dialogue_mode`）**，旧版逐段选方案模式与段级 DAG 打标流水线均已退役。

| 阶段 | 说明 |
|------|------|
| **1. 设定共创 (Setup Chat)** | 设定共创 Agent 交互式构建 world / cast / plot，并将大纲预建为分 beat 骨架与台词设计 |
| **2. 整章图写作 (Dialogue Mode)** | LangGraph 整章图按 beat 执行：`task_packet`（装配上下文）→ `author_prose`（主笔落字）→ `derive_states`（状态推演与快照更新）→ `advance`（推进至下一 beat） |
| **3. 一致性与检查点** | archive 状态守卫 + 动态前文尾窗，跨拍记忆随距离坍缩为概要，自动保存 checkpoint 随时支持断点续写 |
| **4. 成稿保存** | 章节产物自动保存为 `chapters/chapter_XXX/第N章_主笔.md` |

- **Skill & 节点配置**：在 WebUI「Pipeline 配置」视图配置多套档案（`manifest.json` / `author_loop_skill_prefs.json`）及能力节点 LLM 参数（一键建设定 `auto_build_setup`、图像识别、身份生成等）。
- 详细架构契约请参阅 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## 维护与运维工具

项目在 `scripts/` 目录下提供了一系列工业级运维与分析工具：

- **Prompt 解析调试**：`uv run python scripts/prompt_parse.py -c <章号>` (解析流式日志中每次 LLM 的 system/user prompt 与模型回复)
- **状态自愈与重置**：`uv run scripts/reset_pipeline_state.py` (清理脏数据，加 `--chapter N` 可重置特定章节产物)
- **Token 与成本分析**：`uv run python scripts/token_report.py --chapter <章号>` (按 step/agent 聚合 token 消耗与成本估算)
- **Tool 调用诊断**：`uv run python scripts/tool_report.py --chapter <章号>` (分析工具调用的成功率与结果)
- **日志导出 Markdown**：`uv run python scripts/log_export.py --chapter <章号>` (将 NDJSON 日志转为结构化 Markdown)
- **Agent 包校验**：`uv run python scripts/validate_agent_packages.py` (检查 Agent Package 与 manifest 接线一致性)
- **AI 腔特征分析**：`uv run python scripts/ai_word_report.py` (统计成稿中 AI 常用词与句式密度)

更多详情请参阅 📖 [《运维与分析脚本指南》(scripts/README.md)](./scripts/README.md)

---

## Tauri 桌面壳打包（发布安装包给终端用户）

给不装 Python/Node 环境的用户发版本时，使用 Tauri 打包为原生桌面安装包：

```powershell
# 桌面壳开发调试
npm run tauri:dev

# 打包发行安装包
npm run tauri:build
```

内部依次执行（由 `scripts/release/build_tauri_sidecar.ps1` 串联）：

1. `build_frontend_dist.ps1` — `npm install` + `npm run build`，产出 `src/frontend/dist`
2. `build_backend_exe.ps1` — `uv sync --extra release` 安装 PyInstaller，按 `release/windows/chronos-win-portable.spec` 打出 `dist/chronos/`（内嵌 hooks/skills/frontend_dist），把 `chronos.exe` 拷到 `src-tauri/binaries/`，`_internal/` 拷到 `src-tauri/resources/`
3. Tauri 打包器把 sidecar + resources + 原生外壳编译成安装包

打包产物位于 `src-tauri/target/release/bundle/`（Windows 下默认为 NSIS `.exe` 安装包）。用户安装后启动原生窗口，后端作为 Sidecar 随窗口自动拉起与关闭。

---

## 自动化测试

```powershell
# 后端 pytest 测试
uv run pytest tests/ -v

# 仅运行引擎核心测试
uv run pytest tests/engine/ -v

# 前端构建与测试（在 src/frontend 目录下）
npm --prefix src/frontend run test     # vitest 单元测试
npm --prefix src/frontend run lint     # eslint 代码规范检查
npm --prefix src/frontend run build    # TypeScript 类型检查 + Vite 构建
```
