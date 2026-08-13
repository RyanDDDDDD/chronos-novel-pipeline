"""
Token 消耗分析工具

用法：
  uv run python scripts/token_report.py                    # 所有章节最新一次完整跑
  uv run python scripts/token_report.py --chapter 4        # 第4章最新跑
  uv run python scripts/token_report.py --chapter 4 --all  # 第4章所有历史跑趋势
  uv run python scripts/token_report.py --run chapter_004_20260517_170700  # 指定跑
  uv run python scripts/token_report.py --run ... --markdown  # 输出 Markdown 报告
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from utils.paths import engine_logs_dir
from utils.reporting import (
    build_token_report_from_log,
    format_run_table,
    format_trend_table,
    latest_log_per_chapter,
    list_chapter_logs,
    load_call_records,
    parse_log_name,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Token 消耗分析")
    parser.add_argument("--chapter", "-c", type=int, help="指定章节号（如 4）")
    parser.add_argument("--run", "-r", type=str, help="指定 run 文件名（不含 .json）")
    parser.add_argument("--all", "-a", action="store_true", help="显示所有历史 run 趋势")
    parser.add_argument("--step", "-s", type=int, nargs="+", help="只显示指定 seg（step）")
    parser.add_argument("--markdown", "-m", action="store_true", help="输出 Markdown 报告")
    args = parser.parse_args()

    logs_root = engine_logs_dir()

    if args.run:
        path = os.path.join(logs_root, args.run + ".json")
        if not os.path.exists(path):
            path = os.path.join(logs_root, args.run)
        if not os.path.exists(path):
            print(f"找不到: {path}", file=sys.stderr)
            sys.exit(1)
        if args.markdown:
            print(build_token_report_from_log(path))
            return
        records = load_call_records(path)
        if args.step:
            records = [r for r in records if r.step in args.step]
        print(format_run_table(path, records))
        return

    all_logs = list_chapter_logs(chapter=args.chapter, logs_dir=logs_root)
    all_logs = [f for f in all_logs if not os.path.basename(f).startswith("chapter_999")]

    if not all_logs:
        print("没有找到日志文件。", file=sys.stderr)
        sys.exit(1)

    if args.all:
        by_chapter: dict[int, list[str]] = defaultdict(list)
        for path in all_logs:
            ch, _ = parse_log_name(path)
            by_chapter[ch].append(path)
        for ch in sorted(by_chapter):
            print(format_trend_table(by_chapter[ch]))
        return

    latest = latest_log_per_chapter(all_logs)
    chapters = sorted(latest) if args.chapter is None else [args.chapter]
    for ch in chapters:
        if ch not in latest:
            print(f"第{ch}章没有日志", file=sys.stderr)
            continue
        path = latest[ch]
        if args.markdown:
            print(build_token_report_from_log(path))
            continue
        records = load_call_records(path)
        if args.step:
            records = [r for r in records if r.step in args.step]
        print(format_run_table(path, records))


if __name__ == "__main__":
    main()
