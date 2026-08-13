"""
MCP 工具调用分析器

用法：
  uv run python scripts/tool_report.py                    # 所有章节最新跑（按工具汇总）
  uv run python scripts/tool_report.py --chapter 6        # 第6章最新跑
  uv run python scripts/tool_report.py --run chapter_006_20260518_080420
  uv run python scripts/tool_report.py --by-step          # 按步骤分组显示
  uv run python scripts/tool_report.py --errors-only      # 只显示有错误或空返回的条目
"""

from __future__ import annotations

import argparse
import ast
import glob
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field

LOGS_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
SEP = "─" * 72


# ──────────────────────────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────────────────────────

@dataclass
class ToolInvocation:
    step: int
    agent: str
    name: str
    args: str
    result: str
    is_error: bool
    is_empty: bool   # 返回"无表态数据"或空字符串


@dataclass
class ToolStat:
    name: str
    calls: int = 0
    errors: int = 0
    empties: int = 0
    steps: set[int] = field(default_factory=set)


# ──────────────────────────────────────────────────────────────────
# 解析
# ──────────────────────────────────────────────────────────────────

def _extract_text(content: object) -> str:
    if isinstance(content, list):
        parts = [item.get("text", str(item)) if isinstance(item, dict) else str(item) for item in content]
        return "\n".join(p for p in parts if p)
    if isinstance(content, str):
        stripped = content.strip()
        if stripped.startswith("[{") or stripped.startswith("[{'"):
            try:
                parsed = ast.literal_eval(stripped)
                if isinstance(parsed, list):
                    texts = [item.get("text", "") if isinstance(item, dict) else str(item) for item in parsed]
                    return "\n".join(t for t in texts if t)
            except (ValueError, SyntaxError):
                pass
        return content
    return str(content)


_EMPTY_MARKERS = ("无表态数据", "尚未解锁", "暂无数据", "not found", "[]", "")


def _is_empty(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    return any(marker in t for marker in _EMPTY_MARKERS if marker)


def _fmt_args(args: object) -> str:
    if isinstance(args, dict):
        return ", ".join(f"{k}={v}" for k, v in args.items())
    s = str(args).strip()
    return s if s else ""


def parse_tool_messages(step: int, agent: str, msgs: list) -> list[ToolInvocation]:
    from collections import deque
    pending: list[tuple[str, str]] = []
    results: list[tuple[str, str, bool]] = []

    for msg in msgs:
        if not isinstance(msg, dict):
            continue
        mtype = msg.get("type")

        if mtype == "ai":
            for tc in msg.get("tool_calls") or []:
                name = tc.get("name", "?")
                args = _fmt_args(tc.get("args", ""))
                pending.append((name, args))

        elif mtype == "tool" and msg.get("name"):
            raw = _extract_text(msg.get("content", ""))
            is_error = "Error:" in raw or "ToolException" in raw
            results.append((msg["name"], raw, is_error))

    queues: dict[str, deque] = {}
    for name, args in pending:
        queues.setdefault(name, deque()).append(args)

    invocations: list[ToolInvocation] = []
    for name, raw, is_error in results:
        args = queues.get(name, deque())
        matched_args = args.popleft() if args else ""
        invocations.append(ToolInvocation(
            step=step,
            agent=agent,
            name=name,
            args=matched_args,
            result=raw,
            is_error=is_error,
            is_empty=_is_empty(raw) and not is_error,
        ))

    return invocations


def load_log(path: str) -> list[ToolInvocation]:
    invocations: list[ToolInvocation] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "step" not in e or "tool_messages" not in e:
                continue
            step = int(e["step"])
            agent = e.get("agent", "?")
            invocations.extend(parse_tool_messages(step, agent, e["tool_messages"]))
    return invocations


# ──────────────────────────────────────────────────────────────────
# 汇总
# ──────────────────────────────────────────────────────────────────

def aggregate_by_tool(invocations: list[ToolInvocation]) -> list[ToolStat]:
    stats: dict[str, ToolStat] = {}
    for inv in invocations:
        if inv.name not in stats:
            stats[inv.name] = ToolStat(name=inv.name)
        s = stats[inv.name]
        s.calls += 1
        s.steps.add(inv.step)
        if inv.is_error:
            s.errors += 1
        elif inv.is_empty:
            s.empties += 1
    return sorted(stats.values(), key=lambda x: (-x.calls, x.name))


def group_by_step(invocations: list[ToolInvocation]) -> dict[int, list[ToolInvocation]]:
    by_step: dict[int, list[ToolInvocation]] = defaultdict(list)
    for inv in invocations:
        by_step[inv.step].append(inv)
    return dict(sorted(by_step.items()))


# ──────────────────────────────────────────────────────────────────
# 渲染
# ──────────────────────────────────────────────────────────────────

def print_by_tool(
    path: str,
    invocations: list[ToolInvocation],
    errors_only: bool = False,
) -> None:
    stats = aggregate_by_tool(invocations)
    if errors_only:
        stats = [s for s in stats if s.errors > 0 or s.empties > 0]

    ch_match = re.search(r"chapter_(\d+)_(\d{8}_\d{6})", os.path.basename(path))
    ch = int(ch_match.group(1)) if ch_match else 0
    ts_raw = ch_match.group(2) if ch_match else ""
    ts_fmt = (
        f"{ts_raw[:4]}-{ts_raw[4:6]}-{ts_raw[6:8]} {ts_raw[9:11]}:{ts_raw[11:13]}"
        if ts_raw else ""
    )

    total_calls = sum(s.calls for s in stats)
    total_errors = sum(s.errors for s in stats)
    total_empties = sum(s.empties for s in stats)

    print(f"\n第{ch}章 · {os.path.basename(path)}   ({ts_fmt})")
    print(f"  工具调用总计：{total_calls} 次  ✗ {total_errors} 错误  ∅ {total_empties} 空返回")
    print(SEP)
    print(f"  {'工具名':<35}  {'calls':>5}  {'✗ err':>5}  {'∅ emp':>5}  步骤")
    print(SEP)

    if not stats:
        print("  （无 MCP 工具调用记录）")
    else:
        for s in stats:
            steps_str = ", ".join(f"S{n}" for n in sorted(s.steps))
            err_str = f"{s.errors:>5}" if s.errors else "     "
            emp_str = f"{s.empties:>5}" if s.empties else "     "
            flag = "  ◄ 有问题" if s.errors or s.empties else ""
            print(
                f"  {s.name:<35}  {s.calls:>5}  {err_str}  {emp_str}  {steps_str}{flag}"
            )

    print(SEP)


def print_by_step(
    path: str,
    invocations: list[ToolInvocation],
    errors_only: bool = False,
) -> None:
    ch_match = re.search(r"chapter_(\d+)", os.path.basename(path))
    ch = int(ch_match.group(1)) if ch_match else 0

    print(f"\n第{ch}章 · 按步骤明细  ({os.path.basename(path)})")
    print(SEP)

    by_step = group_by_step(invocations)
    if not by_step:
        print("  （无 MCP 工具调用记录）")
        return

    for step, invs in by_step.items():
        # 计数
        n_err = sum(1 for i in invs if i.is_error)
        n_emp = sum(1 for i in invs if i.is_empty)
        agent = invs[0].agent if invs else "?"

        if errors_only and n_err == 0 and n_emp == 0:
            continue

        suffix = ""
        if n_err:
            suffix += f"  ✗ {n_err} 错误"
        if n_emp:
            suffix += f"  ∅ {n_emp} 空返回"

        print(f"\n  Step {step} · {agent}  （共 {len(invs)} 次调用{suffix}）")

        # 按工具名折叠
        tool_counts: dict[str, list[ToolInvocation]] = defaultdict(list)
        for inv in invs:
            tool_counts[inv.name].append(inv)

        for name, group in sorted(tool_counts.items()):
            n = len(group)
            errs = sum(1 for i in group if i.is_error)
            emps = sum(1 for i in group if i.is_empty)

            icons: list[str] = []
            if errs:
                icons.append(f"✗×{errs}")
            if emps:
                icons.append(f"∅×{emps}")
            ok = n - errs - emps
            if ok:
                icons.append(f"✓×{ok}")

            status = "  ".join(icons) if icons else "✓"
            count_str = f"×{n}" if n > 1 else "  "
            print(f"    {count_str}  {name:<35}  {status}")

            # 展开错误详情
            for inv in group:
                if inv.is_error or inv.is_empty:
                    args_display = f"({inv.args})" if inv.args else "()"
                    tag = "✗" if inv.is_error else "∅"
                    preview = inv.result.replace("\n", " ").strip()
                    if len(preview) > 120:
                        preview = preview[:120] + "…"
                    print(f"         {tag} {name}{args_display}")
                    print(f"           → {preview}")

    print(f"\n{SEP}")


# ──────────────────────────────────────────────────────────────────
# IO
# ──────────────────────────────────────────────────────────────────

def list_logs(chapter: int | None = None) -> list[str]:
    files = sorted(glob.glob(os.path.join(LOGS_DIR, "*.ndjson")))
    if chapter is not None:
        prefix = f"chapter_{chapter:03d}_"
        files = [f for f in files if os.path.basename(f).startswith(prefix)]
    return [f for f in files if not os.path.basename(f).startswith("chapter_999")]


def parse_log_name(path: str) -> tuple[int, str]:
    name = os.path.splitext(os.path.basename(path))[0]
    m = re.match(r"chapter_(\d+)_(\d{8}_\d{6})", name)
    return (int(m.group(1)), m.group(2)) if m else (0, name)


def latest_log_per_chapter(logs: list[str]) -> dict[int, str]:
    best: dict[int, str] = {}
    for path in logs:
        ch, ts = parse_log_name(path)
        if ch not in best or ts > parse_log_name(best[ch])[1]:
            best[ch] = path
    return best


# ──────────────────────────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="MCP 工具调用分析器")
    parser.add_argument("--chapter", "-c", type=int, help="指定章节号（如 6）")
    parser.add_argument("--run", "-r", type=str, help="指定 run 文件名（不含 .ndjson）")
    parser.add_argument("--by-step", "-s", action="store_true", help="按步骤分组显示")
    parser.add_argument("--errors-only", "-e", action="store_true", help="只显示有问题的条目")
    args = parser.parse_args()

    def process(path: str) -> None:
        invocations = load_log(path)
        if args.by_step:
            print_by_step(path, invocations, errors_only=args.errors_only)
        else:
            print_by_tool(path, invocations, errors_only=args.errors_only)

    if args.run:
        path = os.path.join(LOGS_DIR, args.run + ".ndjson")
        if not os.path.exists(path):
            path = os.path.join(LOGS_DIR, args.run)
        if not os.path.exists(path):
            print(f"找不到: {path}", file=sys.stderr)
            sys.exit(1)
        process(path)
        return

    all_logs = list_logs(chapter=args.chapter)
    if not all_logs:
        print("没有找到日志文件。", file=sys.stderr)
        sys.exit(1)

    latest = latest_log_per_chapter(all_logs)
    chapters = sorted(latest) if args.chapter is None else [args.chapter]
    for ch in chapters:
        if ch not in latest:
            print(f"第{ch}章没有日志", file=sys.stderr)
            continue
        process(latest[ch])


if __name__ == "__main__":
    main()
