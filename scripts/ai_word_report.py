"""
AI 特征词/句式密度诊断工具

用法：
  uv run python scripts/ai_word_report.py                 # 当前 active 小说全部成稿
  uv run python scripts/ai_word_report.py --chapter 4      # 单章
  uv run python scripts/ai_word_report.py --markdown       # 输出 Markdown 表格
"""
from __future__ import annotations

import argparse
import sys

from api.services.pipeline_catalog import list_author_manuscripts, read_author_manuscript
from engine.execution.style_guard import WORD_THRESHOLDS, get_compiled_patterns


def compute_chapter_density(content: str) -> dict:
    """整章静态密度：词汇/句式命中数、每万字密度、按 WORD_THRESHOLDS 超标的词列表。"""
    length = len(content)
    word_hits = {w: content.count(w) for w in WORD_THRESHOLDS if content.count(w) > 0}
    word_total = sum(word_hits.values())
    pattern_total = sum(len(p.findall(content)) for p in get_compiled_patterns())
    grand_total = word_total + pattern_total
    density = (grand_total / length * 10000) if length else 0.0
    over_threshold = [
        w for w, c in word_hits.items()
        if (c / length * 10000 if length else 0) > WORD_THRESHOLDS[w]
    ]
    return {
        "length": length, "word_hits": word_hits, "word_total": word_total,
        "pattern_total": pattern_total, "grand_total": grand_total,
        "density": density, "over_threshold": over_threshold,
    }


def _format_console(chapter: int, stats: dict) -> str:
    lines = [
        f"第{chapter}章 | 字数: {stats['length']:,} | 总命中: {stats['grand_total']}"
        f"（词汇 {stats['word_total']} / 句式 {stats['pattern_total']}）"
        f" | 每万字密度: {stats['density']:.2f}",
    ]
    if stats["word_hits"]:
        detail = " | ".join(
            f"{w}:{c}" for w, c in sorted(
                stats["word_hits"].items(), key=lambda kv: kv[1], reverse=True,
            )
        )
        lines.append(f"  词频: {detail}")
    if stats["over_threshold"]:
        lines.append(f"  超标词: {', '.join(stats['over_threshold'])}")
    return "\n".join(lines)


def _format_markdown_row(chapter: int, stats: dict) -> str:
    over = ", ".join(stats["over_threshold"]) if stats["over_threshold"] else "无"
    return (
        f"| {chapter} | {stats['length']:,} | {stats['grand_total']} | "
        f"{stats['word_total']} | {stats['pattern_total']} | "
        f"**{stats['density']:.2f}** | {over} |"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="AI 特征词/句式密度诊断")
    parser.add_argument("--chapter", "-c", type=int, help="只看指定章节号")
    parser.add_argument("--markdown", "-m", action="store_true", help="输出 Markdown 表格")
    args = parser.parse_args()

    manuscripts = list_author_manuscripts()
    if args.chapter is not None:
        manuscripts = [m for m in manuscripts if m["chapter"] == args.chapter]

    if not manuscripts:
        print("没有找到已保存的主笔成稿。", file=sys.stderr)
        sys.exit(1)

    rows = []
    for m in manuscripts:
        content = read_author_manuscript(m["chapter"])["content"]
        rows.append((m["chapter"], compute_chapter_density(content)))
    rows.sort(key=lambda r: r[1]["density"], reverse=True)

    if args.markdown:
        print("| 章节 | 字数 | 总命中 | 词汇 | 句式 | **万字密度** | 超标词 |")
        print("| --- | --- | --- | --- | --- | --- | --- |")
        for chapter, stats in rows:
            print(_format_markdown_row(chapter, stats))
        return

    for chapter, stats in rows:
        print(_format_console(chapter, stats))


if __name__ == "__main__":
    main()
