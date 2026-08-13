# `context/` — 知识与上下文供给层

本层主要包含角色基本属性解析、性别解析、时间轴折叠等与单章小说上下文相关的底层逻辑。

## 根文件

| 文件 | 作用 | 关键符号 |
|------|------|----------|
| `character_resolver.py` | 角色档案 fold：lore 初值 + timeline delta → 某 (chapter,stage) 快照。 | 深合并 physique 等 |
| `character_timeline.py` | stage 级 timeline JSON 读写（archive 构建期滚动）。 | `load_timeline`、`append_stage` |
| `personality.py` | 从 timeline 解析态读取自由文本 personality。 | `resolved_personality` |
| `pre_inject.py` | 注入格式化与裁剪：渲染预注入块、按段/性别/stage 收窄。 | `format_context`、`filter_for_segment` |

## 子目录

| 目录 | 作用 |
|------|------|
| `dialogue/` | 提供台词链互称与场景感知的解析脚手架。 |

> 注：旧的 `ContextRegistry` 注册中心、`providers/`、`indexers/` 以及旧的 `ContextRequest` 并发解析流均已退役，逻辑全部整合至统一的 `repositories` 仓储层中。
