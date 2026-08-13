# Chronos Agent Package 规范

> **状态**：已对齐 dialogue mode 主笔引擎  
> **版本**：0.5 — 2026-07-06  
> **受众**：新增/改造 `hooks/packages/` 下执行单元的开发者  

> **退役说明**：段级 DAG 执行、classic 主笔（写作期 `build_options` 热路径）、`produce_refined`、`build_context`、四阶段 context hook（`brainstorm_/embed_/fill_/judge_context`）、独立 MCP 数据服务均已移除。dialogue mode 热路径见 `skills/setup_chat_skills/`（含已迁入的代码 skill 包）；`hooks/packages/` 中最后一个真实包 `dialogue_design` 已确认零运行时消费方并删除（台词设计现由 `dialogue_mode` 内的 director 等机制承担），目前该目录只剩 `_template` 脚手架。当前 live Hook 扩展点见 §6。
> **对标**：借鉴 VS Code Extension 的「manifest + contributes + activation」，**不**引入 `package.json` / VSIX；管线级契约在 `config/pipelines/<id>/manifest.json`。

---

## 1. 设计目标

| 目标 | 说明 |
|------|------|
| **可发现** | 引擎仅凭目录结构与文件名加载 prompt / refine，无需硬编码 agent 列表 |
| **可组合** | 同一目录可承载多个 `role`（多节点共用一个 `hook.py`） |
| **可降级** | 无 `hook.py` 时仍可用 manifest + 纯 prompt 跑通（旧行为） |
| **边界清晰** | 领域知识在 agent 目录；跨领域机制在 `skills/` + `src/backend/engine/` |

---

## 2. 概念映射（VS Code → Chronos）

| VS Code Extension | Chronos Agent Package |
|-------------------|------------------------|
| `package.json`（扩展清单） | `config/pipelines/<id>/manifest.json` 中的 **节点** + 可选节点字段覆盖 |
| `main` / `activate()` | `hooks/packages/<pkg>/hook.py` 中的 `class Hook(AgentHook)` |
| `contributes.commands` 等 | **文件名约定** + Hook 类属性（`validation`、`build_options`…） |
| `README` | `hooks/packages/<pkg>/` 内 prompt 头注释 + 本规范 |
| 扩展根目录 | `hooks/packages/<package_name>/`（**package** = 磁盘目录名，可与 manifest `agent` 字段不同） |

**关键区别**：Chronos 的「扩展 ID」在管线里是 **节点 key**（如 `dialogue_turn`），磁盘目录往往是 **package**（如 `dialogue_design`）。`AgentPluginLoader` 用 manifest 的 `agent` 找 hook，用 `resolve_role()` 找 prompt 文件。

---

## 3. 目录布局

### 3.1 标准单角色包（推荐默认）

```text
hooks/packages/<package_name>/
├── hook.py                      # 可选；IoC 入口
├── <role>.md                    # 必填（主 System Prompt）
├── <role>_EXAMPLE.md            # 强烈推荐（Few-shot）
├── refine_analysis.md           # 可选；REFINE 通用分析（单角色时可省略 role 前缀）
├── <role>_refine_analysis.md    # 可选；REFINE 分析（优先于上一项）
├── agent.meta.json              # 必填（已接线包）；契约见 hooks/packages/agent.meta.schema.json
├── assets/                      # 可选；只读数据 / 可 import 的引擎模块
│   ├── *.json
│   ├── *.schema.json
│   └── *.py                     # 仅服务本 package；由 loader 加入 sys.path
└── *.py                         # 可选；package 内共享库（默认勿被其他 package import；同组宿主例外见 §3.4）
```

**`<package_name>`**：与 `manifest.json` 里节点的 `"agent"` 字段一致，例如 `dialogue_design`、`architect`。

**`<role>`**：由 `AgentPluginLoader.resolve_role(step_config)` 解析，优先级：

1. manifest 节点显式 `"role": "..."`  
2. `Hook.default_role`（单角色包）  
3. 节点 key（`step_config["_node_id"]`，如 `dialogue_turn`）  
4. manifest `"agent"` 名  

示例：`dialogue_turn` 节点 → `agent: dialogue_design` → **role** = `dialogue_turn`（无 `default_role` 时）→ 加载 `dialogue_turn.md`（若存在）或回退 agent 名。

### 3.2 多角色包（一个 hook，多个节点）

```text
hooks/packages/<multi_role_package>/
├── hook.py                      # Hook.handles = ["role_a", "role_b"]
├── role_a.md
├── role_b.md
└── assets/                      # 可选
```

**约定**：

- 一个 `hook.py`，`handles` 列出所有由本包服务的 **节点 agent 名**（与 loader 查找键一致；见 §4）。  
- 每个 role 一套 `{role}.md` + 可选 `{role}_*` 附属文件。  
- `Hook.names` / `Hook.descriptions` 可按 role 提供显示名（`resolve_name` / `resolve_description`）。

> 原多角色扩展包已退役，动作库迁入 `skills/setup_chat_skills/` 下的代码 skill 包（`interface.py` + `assets/`）。

### 3.3 脚本型包（非 LLM prompt 主导）

`archive_builder` 等以 Python 流水线为主：

```text
hooks/packages/archive_builder/
├── hook.py                      # 常 override run_chapter_step
├── state_builder.md             # 子角色 prompt（若仍走 LLM）
├── character_archive_builder.py
└── assets/
```

**约定**：若节点不产生章节 md，`Hook.output_file = ""` 或 manifest `emits_file: false`。

### 3.4 禁止 / 不推荐

| 做法 | 原因 |
|------|------|
| 跨 package 直接 `from other_agent.xxx import`（任意散引） | 破坏边界；通用共享逻辑应抽到 `src/backend/` 或 `skills/` |
| 在 `hooks/packages/` 外硬编码 agent 路径 | 破坏 `AGENTS_DIR` 单根约定 |
| 遗留未接线目录 | manifest 未引用的 agent 目录视为 **deprecated**，应删或合并（如旧 `hooks/packages/dialogue/` 已删，其共享库 `dialogue_context.py`/`scene_aware.py`/`assets` 已并入 `dialogue_anchor/`） |
| 把运行时状态写入 `assets/` | `assets/` 仅静态；状态走 `PipelineState` / lore / 内存 Snapshot |

**同组包共享库（受控例外）**：一组**强相关**的 agent（如 `dialogue_anchor` + `dialogue_expander`）可指定其中一个为「共享库宿主」，把共用模块/资产（`dialogue_context.py`、`scene_aware.py`、`anchor_schema.py`、`assets/`）放在宿主目录，另一个用 `sys.path` 引宿主目录 import。约束：① 依赖**单向**（expander→anchor，不互引）；② 仅限同组；③ 真正跨领域的通用逻辑仍须上移 `src/backend`。这不算违反上面的「跨 package 散引」禁令——是有意的同组聚合，避免散落多个 `dialogue_*` 目录。

---

## 4. Hook 发现与加载（`AgentPluginLoader`）

实现：`src/backend/engine/execution/agent_plugin_loader.py`。

查找 `hook.py` 的顺序（对 manifest 中的 `agent` 名）：

1. `hooks/packages/<subdir>/<agent_name>/hook.py`  
2. `hooks/packages/<agent_name>/hook.py`  
3. `hooks/packages/<subdir>/hook.py` 且 `Hook.handles` 包含 `agent_name`  

加载后：

- 必须存在 **`class Hook(AgentHook)`**（实例化）。  
- 将 `hook.py` 所在目录及 `assets/` 插入 `sys.path`（故 `assets/*.py` 可被同包 `from … import …` 引用）。构建期代码 skill 包（`skills/setup_chat_skills/<name>/interface.py`）由 `collect_skill_tools` 对包目录与 `assets/` 做同样处理。

**多角色包**务必设置：

```python
class Hook(AgentHook):
    handles = ["role_a", "role_b"]
```

manifest 中两节点均写 `"agent": "<multi_role_package>"`，靠 `_node_id` 区分 role。

---

## 5. 文件契约与引擎加载器

### 5.1 Prompt 层（每次 LLM 调用）

| 文件 | 加载器 | 条件 |
|------|--------|------|
| `skills/global_base.md` | `PromptManager.load_global_base` | 所有 agent |
| `skills/tagging_base.md` | `load_tagging_base` | `Hook.is_annotator is True` |
| `{role}.md` | `load_agent_prompt` | 文件存在 |
| `{role}_EXAMPLE.md` | 同上 | **必填**（若需要 Few-shot）；根目录 `EXAMPLE.md` 已废弃 |
| `skills/prose-style-base.md` | `plugins.PROSE_STYLE_CARD`（import 时加载一次） | **hook 存在且** `Hook.inject_prose_style is True`（基类默认 True） |

组装顺序：`global_base` → `tagging_base`（kind=inline_tag 就地标注师）/ `block_base`（kind=block_gen 块生成/埋槽师）→ `System_Instructions` → `Few_Shot_Examples` →（运行时）`prose-style` 追加在 system 末尾。节点形态由 hook 的 `kind`（`NodeKind`）决定；旧 `is_annotator=True` 声明回退为 `inline_tag`。

> **注意**：dialogue mode 文风卡由 `dialogue_mode/turns.py` 在整章 system prompt 一次注入（`build_system_prompt(prose_style)`）。classic 路径的 per-beat 落字拼装已退役。无 `hook.py` 的纯 prompt 包不参与 skill 发现。

### 5.2 REFINE 层

| 文件 / API | 加载器 | 条件 |
|------------|--------|------|
| `{role}_refine_analysis.md` → `refine_analysis.md` | `load_agent_refine_analysis` | `mode: REFINE` |
| `Hook.build_options()` | `RefineManager` | 返回非 `None` 时跳过 LLM 分析，直通 MCQ |
| `skills/brainstorm-refine-protocol.md` | refine 模块 | 分析阶段外壳（领域分析在 agent md） |
| `skills/divergent-options.md` | refine 模块 | 选项质量卡（全局） |

Phase 3 执行时 user_msg 追加 `## 用户选定方向`（引擎生成，非磁盘文件）。

### 5.3 Validation 层（规则校验，非 LLM）

| 配置 | 解析 |
|------|------|
| `Hook.validation` | `"preserve"` \| `"structure"` \| `"none"` |
| manifest `output_preservation` | 覆盖 `min_ratio` / `max_retries`；`enabled: false` 关闭 |

### 5.4 上下文与 `injects` 契约

预注入由引擎经 **`repositories`**（`get_lore_repo()` / `get_archive_repo()` 等）与 **`context/` helper**（`character_resolver`、`pre_inject`）装配，不经 `Hook.build_context()` 或已退役的 `ContextRegistry`。

Hook 仍用类属性 `injects: list[str]` 声明向 prompt 提供的数据键；主 prompt 用 `<!-- requires: a, b -->` 声明所需。`agent_package_check` 校验 `requires ⊆ injects`。

dialogue mode 主笔任务包在 `dialogue_mode/turns.py:render_task_packet` 内组装角色卡与台词设计块；setup_chat skills 在构建期自行读 repo。

> 四阶段 context hook 与 MCP RPC 已退役；见 `src/backend/context/README.md`。

---

## 6. `AgentHook` 贡献点一览（当前 live）

基类：`src/backend/engine/execution/agent_hook.py`。子类 **只 override 需要的方法**。

| 类属性 / 方法 | 类型 | 用途 |
|---------------|------|------|
| `handles` | `list[str]` | 目录级 hook 服务的 agent 名列表 |
| `injects` | `list[str]` | prompt `requires` 契约 lint |
| `default_role` | `str` | 单角色包默认 prompt 名 |
| `display_name` / `description` | `str` | skill UI 展示 |
| `agent_type` | `str` | `structure` / `expansion` 等；skill 发现用 |
| `build_options` | async | **classic 路径** expansion skill：产出候选方案；dialogue mode 写作期不调用 |
| `render_selection_option` | sync | **classic 路径**：把选中 option 渲染成指示文本行 |

> 已退役（勿在新 hook 中实现）：`build_context`、`brainstorm_/embed_/fill_/judge_context`、`produce_refined`、`post_refine_execute`、`trim_audit_context`、`output_file*`、`prepare_segments`、`run_chapter_step` 等 DAG / classic 时代扩展点。构建期 skill 见 `skills/setup_chat_skills/*/SKILL.md`。

---

## 7. 与 `manifest.json` 的关系

节点最小字段：

```json
"my_node": {
  "agent": "package_name",
  "inputs": ["upstream_node"]
}
```

常用可选字段：

| 字段 | 作用 |
|------|------|
| `role` | 显式指定 prompt 文件名前缀 |
| `name` / `description` | 覆盖 hook 显示名（历史字段，skill UI 以 hook 为准） |

> `mode: REFINE`、`parallel_group`、`strip_sections`、`output_file` 等为 DAG 时代字段，执行链已不读取。

**节点 key** 会写入运行时 `step_config["_node_id"]`，是多角色包解析 role 的默认来源。

---

## 8. `assets/` 规范

| 类型 | 命名 | 说明 |
|------|------|------|
| 数据 | `*.json` | 动作库、词表、预设等 |
| 契约 | `*.schema.json` | JSON Schema，供校验与文档 |
| 逻辑 | `*.py` | 拓扑、组装器等；**仅本 package 引用** |

JSON 字段约定应在同目录 `*.schema.json` 或 package 内 README 片段中说明；**禁止**在 prompt 中硬编码大段 JSON。

---

## 9. 包类型模板（快速选型）

| 类型 | 特征 | 示例 |
|------|------|------|
| **A. structure skill** | `agent_type=structure` | `architect`（骨架演进） |
| **B. expansion skill（classic，已退役）** | `agent_type=expansion`，实现 `build_options` | 原多角色扩展包；动作库已迁入 `skills/setup_chat_skills/` 下的代码 skill 包 |
| **C. 库 agent** | manifest 未接线或 `unwired: true` | 备用包 |
| **D. 纯 prompt** | 无 `hook.py` | 不参与 skill 发现 |

---

## 10. 新增 Agent 检查清单

- [ ] 在 `config/pipelines/<id>/manifest.json` 增加节点（若需 agent-meta 接线）  
- [ ] 创建 `hooks/packages/<package>/`，含 `{role}.md`  
- [ ] 若 expansion skill：实现 `hook.py` + `build_options` + 可选 `render_selection_option`  
- [ ] 声明 `injects` 并与 prompt `<!-- requires: … -->` 对齐  
- [ ] 提供 `agent.meta.json`（改 manifest 后运行 `scripts/sync_agent_meta.py`）  
- [ ] 静态数据放 `assets/`，附 `*.schema.json`（如有结构）  
- [ ] 多角色时设置 `handles` 与各 role 文件成套  
- [ ] 不引用 deprecated 目录；共享代码上移 `src/backend`  

---

## 11. 测试约定

| 范围 | 位置 |
|------|------|
| Hook / context 契约 | `tests/engine/test_*_hook.py` |
| 加载器 / validation | `tests/engine/test_validation.py` |
| MCP / 数据服务 | `tests/servers/` |

新增 package 时至少：**resolve_role 能解析到存在的 `{role}.md`**。

---

## 12. 与现有文档的关系

| 文档 | 关系 |
|------|------|
| `hooks/packages/README.md` | 职能索引；应链接本规范 |
| `CLAUDE.md` | 流水线命令与架构总览 |
| `config/pipelines/<id>/manifest.json` | 管线 SSOT（gitignore live 档） |
| `skills/*.md` | 跨 agent 协议（refine、tagging、文风） |
| `docs/superpowers/specs/*` | 特性级设计说明；不替代本包结构规范 |

---

## 13. `agent.meta.json`（包清单）

每包一份 `hooks/packages/<package>/agent.meta.json`，契约见 `hooks/packages/agent.meta.schema.json`。

> **定位**：`agent.meta.json` 是**镜像 + CI 清单**，由 `sync_agent_meta.py` 据 manifest + hook **反写**。引擎运行时**不**读 meta 决定行为。skill 启用由 `author_loop_skill_prefs.json` + WebUI 控制。

| 字段 | 说明 |
|------|------|
| `package` | 与目录名一致 |
| `roles` | 本包全部 `{role}.md` |
| `nodes` | manifest 节点 key 列表（`sync_agent_meta.py` 维护） |

```bash
uv run python scripts/sync_agent_meta.py        # 手写改 manifest 后同步（与 Web 保存等价）
uv run python scripts/sync_agent_meta.py --check  # CI：检测漂移
```

**Web 保存**：`POST /api/manifest` 写入 manifest 后会调用同一套 `sync_agent_meta_files()`（引擎内函数，非子进程跑脚本），自动更新各包 `agent.meta.json`；失败时以 `warnings` 返回，不阻断保存。

`validate_agent_packages.py` 与 pre-commit 会校验 meta 与 manifest 一致，并拒绝残留根目录 `EXAMPLE.md`。

> **CI 对账范围**：`agent_package_check._check_agent_meta_file` 比对 `package` / `roles`。任一与 manifest 计算的期望不一致即报错，运行 `sync_agent_meta.py` 同步。`nodes` 暂不强制对账（信息性字段）。执行链不读 meta。

**已落地（0.3）**：`agent.meta.json` + `sync_agent_meta.py`；统一 `{role}_EXAMPLE.md`（`PromptManager` 不再加载 `EXAMPLE.md`）；pre-commit 挂 `validate_agent_packages.py`。

---

## 14. Agent 有效性校验

共用底层：`engine/validator/agent_package_check.check_agent_valid` / `check_manifest_agent_packages`。

| 层 | 时机 | 失败处理 |
|----|------|----------|
| **CI** | pre-commit / `validate_agent_packages.py` | 阻断提交 |
| **sync** | `sync_agent_meta.py --check` | 报告 meta drift |

**检查项**：目录存在、`{role}.md`、`requires ⊆ injects`、未接入孤儿包、`agent.meta.json` 同步。

> DAG 时代的 `GET /api/agents` catalog 与 `orchestrator.run()` preflight **已退役**。

---

## 附录 A：`resolve_role` 示例

| 节点 key | manifest `agent` | manifest `role` | `Hook.default_role` | **解析 role** | 加载 prompt |
|----------|------------------|-----------------|---------------------|---------------|-------------|
| `mental` | `mental` | — | `""` | `mental` | `mental.md` |
| `dialogue_turn` | `dialogue_design` | — | `""` | `dialogue_turn` | `dialogue_turn.md`（或回退 `dialogue_design.md`） |

---

## 附录 B：Loader 与 PromptManager 源码索引

- `src/backend/engine/execution/agent_plugin_loader.py` — `AgentPluginLoader`
- `src/backend/llm/prompt_manager.py` — `load_agent_prompt`, `load_agent_refine_analysis`
- `src/backend/engine/validator/agent_package_check.py` — 包校验与 meta 同步
- `src/backend/repositories/` — 数据访问 SSOT
- `src/backend/context/` — 快照 fold、pre_inject 等 helper

---

*本文档描述「当前引擎已实现的行为 + 推荐约定」。若实现与文档冲突，以代码为准并应开 issue 对齐。*
