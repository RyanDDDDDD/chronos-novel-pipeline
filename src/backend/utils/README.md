# `utils/` — 通用工具与基建常量

无业务语义的横切工具：配置单例、路径常量、文本后处理、报表。

| 文件 | 作用 | 关键符号 |
|------|------|----------|
| `config.py` | **ConfigManager**：全局配置单例，所有配置访问统一入口。 | `get_config`、`_deep_merge` |
| `paths.py` | **路径常量**：所有文件路径的单一真实来源（HOOKS_ROOT / AGENTS_DIR / CHAPTERS_DIR / MANIFEST_PATH…）。 | `get_chapter_dir`、`get_character_archive_dir` |
| `text_utils.py` | LLM 输出文本后处理：前缀抽取、加粗剥离、重复截断、思维链剥离。 | `strip_thinking`、`truncate_repetition`、`extract_output_prefix`、`strip_bold_markers` |
| `reporting.py` | engine_server NDJSON → Token 消耗汇总（Markdown / 终端表）。 | `load_call_records`、`aggregate_by_phase`、`build_token_report` |
