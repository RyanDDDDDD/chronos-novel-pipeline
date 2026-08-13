"""
守卫/自审报警频率汇总

读 logs/engine_server/alarms.ndjson（由 dialogue_mode/alarm.py 跨 run 追加），把 census 行
按类目聚合成一行：「守卫 X 检查 Y 报警(率) ｜ 自审 …」，用于判断新架构下这两层还值不值得留。

用法：
  uv run python scripts/alarm_report.py                # 全量汇总一行
  uv run python scripts/alarm_report.py --chapter 4    # 只看第 4 章
  uv run python scripts/alarm_report.py --detail       # 一并列出每条报警内容（看是不是真问题）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from utils.paths import alarms_log_path

# 已知类目固定排序在前，其余按出现序补后。
_KNOWN_ORDER = ["守卫", "自审"]


def _load(path: str, chapter: int | None) -> list[dict]:
    """
读 NDJSON 全部记录（可按章过滤）；文件缺失/坏行宽容跳过。"""

    records: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if chapter is not None and rec.get("chapter") != chapter:
                    continue
                records.append(rec)
    except OSError:
        return []
    return records


def _aggregate(records: list[dict]) -> dict[str, dict[str, int]]:
    """按类目聚合 census 行的 checks/fires。"""

    agg: dict[str, dict[str, int]] = defaultdict(lambda: {"checks": 0, "fires": 0})
    for rec in records:
        if rec.get("type") != "census":
            continue
        kind = str(rec.get("kind", "?"))
        agg[kind]["checks"] += int(rec.get("checks", 0) or 0)
        agg[kind]["fires"] += int(rec.get("fires", 0) or 0)
    return agg


def _ordered_kinds(agg: dict[str, dict[str, int]]) -> list[str]:
    rest = [k for k in agg if k not in _KNOWN_ORDER]
    return [k for k in _KNOWN_ORDER if k in agg] + sorted(rest)


def _summary_line(agg: dict[str, dict[str, int]]) -> str:
    if not agg:
        return "（无 census 记录——还没跑过主笔，或 alarms.ndjson 为空）"
    cells = []
    for kind in _ordered_kinds(agg):
        checks = agg[kind]["checks"]
        fires = agg[kind]["fires"]
        rate = (fires / checks * 100) if checks else 0.0
        cells.append(f"{kind} {checks}检查 {fires}报警({rate:.1f}%)")
    return "  ｜  ".join(cells)


def _format_alarm(rec: dict) -> str:
    """
单条报警明文：守卫含着装前后，自审含 feedback。"""

    kind = rec.get("kind", "?")
    loc = f"ch{rec.get('chapter', '?')} stage{rec.get('stage', '?')} beat{rec.get('beat', '?')}"
    if kind == "守卫":
        before, after = rec.get("clothing_before", ""), rec.get("clothing_after", "")
        cloth = f"  ({before}→{after})" if (before or after) else ""
        return f"[守卫] {loc} {rec.get('character', '?')}: {rec.get('note', '')}{cloth}"
    if kind == "自审":
        return f"[自审] {loc}: {rec.get('feedback', '')}"
    extra = {k: v for k, v in rec.items()
             if k not in ("type", "kind", "chapter", "stage", "beat", "ts")}
    return f"[{kind}] {loc}: {extra}"


def main() -> None:
    parser = argparse.ArgumentParser(description="守卫/自审报警频率汇总")
    parser.add_argument("--chapter", "-c", type=int, help="只统计指定章节号")
    parser.add_argument("--detail", "-d", action="store_true", help="列出每条报警内容")
    args = parser.parse_args()

    path = alarms_log_path()
    records = _load(path, args.chapter)

    scope = f"第 {args.chapter} 章" if args.chapter is not None else "全部"
    print(f"报警汇总（{scope}）  来源：{path}")
    print(_summary_line(_aggregate(records)))

    if args.detail:
        alarms = [r for r in records if r.get("type") == "alarm"]
        print(f"\n报警明细（{len(alarms)} 条）：")
        for rec in alarms:
            print("  " + _format_alarm(rec))


if __name__ == "__main__":
    main()
