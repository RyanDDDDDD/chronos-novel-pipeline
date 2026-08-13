# `engine/` — 创作引擎核心

主笔逐段写作循环（`author_loop/`）+ 设定/档案构建 + agent 契约与共用原语。

## 根文件

| 文件 | 作用 | 关键符号 |
|------|------|----------|
| `state.py` | **PipelineState/SegmentState**（hook context 类型注解）+ 章节组装。 | `PipelineState`、`SegmentState`、`assemble_chapter_file` |

## 子目录

| 目录 | 职责 | 文档 |
|------|------|------|
| `author_loop/` | **主笔写作循环**：架构骨架 → 逐段[决策→skill→落字→守卫→摘要→检查点] | — |
| `setup/` | world/cast/plot 设定构建 | — |
| `archive/` | 设定层角色档案 timeline 构建 | [`archive/README.md`](archive/README.md) |
| `execution/` | AgentHook 契约 + 共用原语（embed_json/review） | [`execution/README.md`](execution/README.md) |
| `modes/` | 主笔 skill 配置 | [`modes/README.md`](modes/README.md) |
| `validator/` | Agent 包、上下文、plot preflight | [`validator/README.md`](validator/README.md) |
