"""
章骨架 → 成稿 扩写增效分析

对比 plot beats（底稿 text，若设计了台词则已织入其中）与主笔成稿（第N章_主笔.md），
并用 journal 的 intent→segment 校验主笔实际扩写倍数。

用法：
  uv run python scripts/expand_report.py                 # 所有有骨架的章（汇总表）
  uv run python scripts/expand_report.py --chapter 6     # 单章详情
  uv run python scripts/expand_report.py --chapter 6 -d  # 含 stage/拍 明细
  uv run python scripts/expand_report.py --markdown      # Markdown 报告
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from utils.expand_report import (  # noqa: E402
    analyze_chapters,
    format_chapter_report,
    format_markdown_report,
    format_summary_table,
    list_analyzable_chapters,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="章骨架扩写增效分析")
    parser.add_argument("--chapter", "-c", type=int, nargs="+", help="指定章节号（可多个）")
    parser.add_argument("--detail", "-d", action="store_true", help="输出 stage/拍 明细")
    parser.add_argument("--markdown", "-m", action="store_true", help="输出 Markdown 报告")
    args = parser.parse_args()

    if args.chapter:
        chapters = args.chapter
    else:
        chapters = list_analyzable_chapters()

    if not chapters:
        print("plot 中未找到含 beats 的章节。", file=sys.stderr)
        sys.exit(1)

    reports = analyze_chapters(chapters)
    if not reports:
        print("未找到可分析的章节。", file=sys.stderr)
        sys.exit(1)

    if args.markdown:
        print(format_markdown_report(reports, detail=args.detail))
        return

    if len(reports) > 1 and not args.detail:
        print(format_summary_table(reports))
        print()
        print("单章明细: uv run python scripts/expand_report.py --chapter N -d")
        return

    for i, report in enumerate(reports):
        if i:
            print()
        print(format_chapter_report(report, detail=args.detail))


if __name__ == "__main__":
    main()
