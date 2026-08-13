"""按 author / chat / sandbox 三个页面分别统计 prompt cache 命中率。

三者共用同一批 logs/engine_server/chapter_*.json NDJSON 日志——章号不能用来分页（story_sandbox
在很多流程里也会写 chapter_000_*.json，不是 setup_chat 专属；实测数据里 chapter=0 的记录里
story_sandbox_* 反而占大多数），所以只能靠 agent 标签分：
  - agent 以 "story_sandbox" 开头   → sandbox
  - agent == "auto_build_setup"     → chat（setup_chat 的批量构建工具；见下方 caveat，
                                       主聊天 agent 逐轮请求不落 NDJSON，本统计覆盖不到）
  - 其余（director/author/review:*/detail:*/state_derive/memory_recall 等） → author
  - chapter_999_*.json （预览/测试专用章号，见 pipeline_catalog.py）        → 整体排除

命中率 = sum(tokens_cached) / sum(tokens_in)（tokens_in 已含 cache_read 部分，与
scripts/token_report.py 的 _full_price_load 口径一致）。

用法：
  uv run python scripts/cache_hit_report.py                  # 全部历史 run 聚合
  uv run python scripts/cache_hit_report.py --latest         # 每章只取最近一次 run
  uv run python scripts/cache_hit_report.py --chapter 4      # 只看第4章相关日志
  uv run python scripts/cache_hit_report.py --verbose        # 附各页内部按 agent 的明细
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from utils.paths import active_novel_dir, active_novel_id, engine_logs_dir
from utils.reporting import (
    latest_log_per_chapter,
    list_chapter_logs,
    load_call_records,
    parse_log_name,
)

_EXCLUDED_CHAPTER = 999
_PAGES = ("author", "sandbox", "chat")


@dataclass
class AgentStats:
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0


@dataclass
class PageStats:
    runs: set[str] = field(default_factory=set)
    chapters: set[int] = field(default_factory=set)
    by_agent: dict[str, AgentStats] = field(default_factory=dict)

    @property
    def calls(self) -> int:
        return sum(a.calls for a in self.by_agent.values())

    @property
    def tokens_in(self) -> int:
        return sum(a.tokens_in for a in self.by_agent.values())

    @property
    def tokens_out(self) -> int:
        return sum(a.tokens_out for a in self.by_agent.values())

    @property
    def tokens_cached(self) -> int:
        return sum(a.tokens_cached for a in self.by_agent.values())

    @property
    def hit_rate(self) -> float:
        ti = self.tokens_in
        return self.tokens_cached / ti if ti else 0.0


def classify_page(agent: str) -> str:
    """Return 'author' / 'sandbox' / 'chat'. Chapter number is not a reliable signal here --
    story_sandbox writes chapter_000_*.json too -- so this is agent-tag-only."""
    if agent.startswith("story_sandbox"):
        return "sandbox"
    if agent == "auto_build_setup":
        return "chat"
    return "author"


def collect(paths: list[str]) -> tuple[dict[str, PageStats], int]:
    pages: dict[str, PageStats] = {p: PageStats() for p in _PAGES}
    excluded_records = 0
    for path in paths:
        chapter, _ = parse_log_name(path)
        records = load_call_records(path)
        if chapter == _EXCLUDED_CHAPTER:
            excluded_records += len(records)
            continue
        for r in records:
            page = classify_page(r.agent)
            stats = pages[page]
            stats.runs.add(os.path.basename(path))
            stats.chapters.add(chapter)
            a = stats.by_agent.setdefault(r.agent, AgentStats())
            a.calls += 1
            a.tokens_in += r.tokens_in
            a.tokens_out += r.tokens_out
            a.tokens_cached += r.tokens_cached
    return pages, excluded_records


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


_PAGE_LABEL = {
    "author": "author 页（author_loop 主笔对话）",
    "sandbox": "sandbox 页（story_sandbox 沙盒）",
    "chat": "chat 页（setup_chat 设定对话）",
}

_CHAT_CAVEAT = (
    "  ⚠ 仅覆盖 auto_build_setup 工具的批量构建调用（chapter_000_*.json）；\n"
    "    setup_chat 主聊天 agent 的逐轮请求走 TokenAccountant(subsystem=\"setup\", key=\"chat\")\n"
    "    累计写 token_ledger.json，不落 NDJSON，此统计覆盖不到——见下方“当前小说快照”补充。"
)


def format_report(pages: dict[str, PageStats], excluded_records: int, *, verbose: bool) -> str:
    sep = "─" * 78
    lines: list[str] = []
    for page in _PAGES:
        s = pages[page]
        lines.append(f"\n{_PAGE_LABEL[page]}")
        lines.append(sep)
        if not s.by_agent:
            lines.append("  (无数据)")
            if page == "chat":
                lines.append(_CHAT_CAVEAT)
            continue
        uncached = s.tokens_in - s.tokens_cached
        lines.append(
            f"  runs={len(s.runs)}  chapters={len(s.chapters)}  calls={s.calls}"
        )
        lines.append(
            f"  tokens_in={s.tokens_in:,}  cached={s.tokens_cached:,}  "
            f"uncached={uncached:,}  tokens_out={s.tokens_out:,}"
        )
        lines.append(f"  命中率 = cached / tokens_in = {_pct(s.hit_rate)}")
        if page == "chat":
            lines.append(_CHAT_CAVEAT)
        if verbose:
            lines.append("")
            name_w = max(6, max((len(n) for n in s.by_agent), default=6)) + 2
            lines.append(f"  {'agent':<{name_w}}{'calls':>7}{'tokens_in':>12}{'cached':>10}{'hit_rate':>10}")
            for name, a in sorted(s.by_agent.items(), key=lambda kv: -kv[1].tokens_in):
                rate = a.tokens_cached / a.tokens_in if a.tokens_in else 0.0
                lines.append(
                    f"  {name:<{name_w}}{a.calls:>7}{a.tokens_in:>12,}{a.tokens_cached:>10,}{_pct(rate):>10}"
                )
    lines.append("")
    lines.append(sep)
    if excluded_records:
        lines.append(f"（另有 {excluded_records} 条记录属于 chapter_{_EXCLUDED_CHAPTER:03d} 预览/测试日志，已排除）")
    return "\n".join(lines)


def format_ledger_snapshot() -> str:
    """Supplementary point-in-time snapshot from token_ledger.json for the active novel.

    token_ledger.json is override semantics (reset every run, not a historical series), but
    it's the only source that also covers setup_chat's main conversational agent -- the NDJSON
    logs only see its auto_build_setup tool calls (see _CHAT_CAVEAT above).

    Reads the JSON file directly (mirrors api.services.token_ledger.load_ledger) instead of
    importing that module -- importing anything under api.services pulls in message_hub.py's
    full engine dependency chain (LangGraph et al.), which this lightweight report shouldn't need.
    """
    import json

    novel_id = active_novel_id()
    ledger_file = os.path.join(active_novel_dir(), "token_ledger.json")
    doc: dict = {}
    if os.path.isfile(ledger_file):
        try:
            with open(ledger_file, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                doc = loaded
        except (OSError, json.JSONDecodeError):
            pass
    lines = [
        "",
        f"当前小说（{novel_id}）token_ledger.json 快照 —— 覆盖语义（同 key 只留最近一次 run），非历史全量：",
        "─" * 78,
    ]
    subsystem_label = {
        "author_loop": "author（章号=key）",
        "story_sandbox": "sandbox（章号=key）",
        "setup": "chat（key=\"chat\"）",
    }
    any_row = False
    for subsystem in ("author_loop", "story_sandbox", "setup"):
        cells = doc.get(subsystem, {})
        if not isinstance(cells, dict) or not cells:
            continue
        for key, cell in sorted(cells.items()):
            if not isinstance(cell, dict):
                continue
            tin = int(cell.get("tokens_in", 0) or 0)
            tcached = int(cell.get("tokens_cached", 0) or 0)
            tout = int(cell.get("tokens_out", 0) or 0)
            if tin == 0 and tout == 0:
                continue
            rate = tcached / tin if tin else 0.0
            any_row = True
            lines.append(
                f"  {subsystem_label.get(subsystem, subsystem):<24} key={key:<10} "
                f"in={tin:>9,}  cached={tcached:>9,}  out={tout:>9,}  hit_rate={_pct(rate)}"
            )
    if not any_row:
        lines.append("  (空 — 当前小说尚未产生任何记录，或已被下一次 run 覆盖)")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="按 author/chat/sandbox 三页分别统计 prompt cache 命中率")
    parser.add_argument("--chapter", "-c", type=int, help="只统计指定章节号相关的日志（含该章的 author 与 sandbox 记录）")
    parser.add_argument("--latest", action="store_true", help="每个章节号只取最近一次 run（默认聚合全部历史 run）")
    parser.add_argument("--verbose", "-v", action="store_true", help="附各页内部按 agent 的明细表")
    parser.add_argument("--no-ledger", action="store_true", help="不附加 token_ledger.json 快照（仅看 NDJSON 历史统计）")
    args = parser.parse_args()

    logs_root = engine_logs_dir()
    all_logs = list_chapter_logs(chapter=args.chapter, logs_dir=logs_root)
    if not all_logs:
        print("没有找到日志文件。", file=sys.stderr)
        sys.exit(1)

    if args.latest:
        all_logs = sorted(latest_log_per_chapter(all_logs).values())

    pages, excluded_records = collect(all_logs)
    print(format_report(pages, excluded_records, verbose=args.verbose))
    if not args.no_ledger:
        print(format_ledger_snapshot())


if __name__ == "__main__":
    main()
