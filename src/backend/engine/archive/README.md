# `engine/archive/` — 设定层：角色档案构建

脱离章节生产 pipeline 的 timeline/state 构建器；产物供 `context` Provider 与 `character_resolver` 运行时读取。

| 文件 | 作用 | 关键符号 |
|------|------|----------|
| `archive_hook.py` | **ArchiveHook 协议**：delta/enrich 插件 seam。 | `ArchiveDeltaHook`, `ArchiveEnrichHook` |
| `hook_loader.py` | **发现 `hooks/archive/`**：importlib 加载、按 phase 分组、按目录名稳定排序。 | `DELTA_HOOKS`, `ENRICH_HOOKS`, `discover_hooks` |
| `state_delta_call.py` | **统一 delta 调用**：组合 hook 片段 → 一次 LLM → 派发 parse。 | `run_state_delta_call` |
| `archive_fields.py` | `character_archive` 顶层字段 SSOT。 | — |
| `physique_dims.py` | 题材级 physique 子字段闭合集与校验及部位槽结构 prompt 渲染（PhysiqueHook 调用）。 | — |
| `sliders.py` | 滑块解析与档位映射（轴/档位从各角色 lore 卡上 `sliders.*.levels` 读取，`character_rubrics(name)`；SlidersHook 调用）。 | — |
| `archive_error.py` | 档案构建可恢复/致命错误类型。 | — |

**用户插件** `hooks/archive/<name>/hook.py`（进版本控制，照 `hooks/packages/` 可自定义）：

| 目录 | hook | 自带资产 |
|------|------|----------|
| `state_core/` | state/gender/address_ref/self_ref delta | `state_builder.md`, `cold_start.md` |
| `sliders/` | 滑块档位 + 标签→数字 | 各角色 lore 卡上的 `sliders.*.levels` |
| `physique/` | 体貌部位槽结构片段 + guard（合法 key = 角色基础部位槽） | `physique_dims.py` |

引擎经 `hook_loader` 发现、按 phase 分组、按目录名字典序拼接 prompt 片段；协议/机制/工具库留 `src/backend/engine/archive/`。

`character_resolver.fold_delta` 合并策略由各 delta hook 的 `merge` 声明汇总（`collect_merge_strategies`）。

设计说明见 `docs/superpowers/specs/2026-06-14-archive-hooks-root-plugins-design.md`。
