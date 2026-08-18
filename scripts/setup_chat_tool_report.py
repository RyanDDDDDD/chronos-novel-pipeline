"""
setup_chat 对话 ReAct agent 工具调用分析器（读 logs/setup_chat_tool_analysis.ndjson，
按回合 turn_trace 记录，见 engine.setup_chat.tool_trace）

用法：
  uv run python scripts/setup_chat_tool_report.py                    # 全部回合
  uv run python scripts/setup_chat_tool_report.py --novel <小说ID>   # 按小说过滤
  uv run python scripts/setup_chat_tool_report.py --turn 12          # 指定回合号
  uv run python scripts/setup_chat_tool_report.py --flagged-only     # 只看有可疑循环标记的回合
  uv run python scripts/setup_chat_tool_report.py --tail 5           # 只看最近 5 个回合
"""

from __future__ import annotations

import argparse
import json
import os
import sys

LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "logs", "setup_chat_tool_analysis.ndjson")
SEP = "─" * 72

_STATUS_ICON = {"ok": "✓", "error": "✗", "rejected": "⊘", "pending": "…"}


def load_records(path: str) -> list[dict]:
    records: list[dict] = []
    if not os.path.exists(path):
        return records
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def print_record(record: dict) -> None:
    flags = record.get("flags") or []
    calls = record.get("calls") or []

    header = (
        f"\n[{record.get('novel_label', '?')}] 回合 #{record.get('turn_id', '?')}"
        f"  ({record.get('ts', '')})"
    )
    print(header)
    print(f"  用户：{record.get('user_text', '')}")
    print(
        f"  共 {record.get('total_calls', len(calls))} 次调用"
        f"  {record.get('rejected_count', 0)} 次被拒"
        f"  {len(flags)} 处可疑循环"
    )
    print(SEP)

    for flag in flags:
        print(
            f"  ◄ 可疑循环  {flag['tool']}({flag['args']})"
            f"  ×{flag['count']}  步骤 {', '.join(f'#{s}' for s in flag['seqs'])}"
        )
    if flags:
        print(SEP)

    for call in calls:
        icon = _STATUS_ICON.get(call.get("status", ""), "?")
        print(f"  {icon} #{call['seq']}  {call['name']}({call.get('args', '')})")
        if call.get("status") in ("error", "rejected"):
            print(f"       → {call.get('result', '')}")

    print(SEP)


def main() -> None:
    parser = argparse.ArgumentParser(description="setup_chat 工具调用分析器")
    parser.add_argument("--novel", type=str, help="按小说 ID 或名称子串过滤")
    parser.add_argument("--turn", type=int, help="指定回合号")
    parser.add_argument("--flagged-only", action="store_true", help="只显示有可疑循环标记的回合")
    parser.add_argument("--tail", type=int, help="只显示最近 N 个回合")
    args = parser.parse_args()

    records = load_records(LOG_PATH)
    if not records:
        print(f"没有找到日志：{LOG_PATH}", file=sys.stderr)
        sys.exit(1)

    if args.novel:
        needle = args.novel.lower()
        records = [
            r for r in records
            if needle in str(r.get("novel_id", "")).lower()
            or needle in str(r.get("novel_label", "")).lower()
        ]
    if args.turn is not None:
        records = [r for r in records if r.get("turn_id") == args.turn]
    if args.flagged_only:
        records = [r for r in records if r.get("flags")]
    if args.tail:
        records = records[-args.tail:]

    if not records:
        print("没有匹配的回合。", file=sys.stderr)
        sys.exit(1)

    for record in records:
        print_record(record)


if __name__ == "__main__":
    main()
