"""
日志 → Markdown 导出工具

用法：
  uv run python scripts/log_export.py                       # 所有章节最新跑
  uv run python scripts/log_export.py --chapter 6           # 第6章最新跑
  uv run python scripts/log_export.py --run chapter_006_20260518_080420
  uv run python scripts/log_export.py --out reports/        # 指定输出目录（默认 reports/）
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from dataclasses import dataclass, field

LOGS_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")


# ──────────────────────────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────────────────────────

@dataclass
class ToolCall:
    name: str
    args: str
    result: str
    is_error: bool


@dataclass
class StepRecord:
    ts: str
    step: int
    agent: str
    model: str
    duration_s: float
    tokens_in: int
    tokens_out: int
    prompt_hash: str
    response: str
    tool_calls: list[ToolCall] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────
# 解析
# ──────────────────────────────────────────────────────────────────

def _extract_text(content: object) -> str:
    """
从 content 字段提取可读文本。

    支持三种格式：
    - str（直接返回，或尝试解析为 Python list repr）
    - list[dict]（提取每项的 text 字段）
    - 其他（str 转换）
    """

    if isinstance(content, list):
        parts = [item.get("text", str(item)) if isinstance(item, dict) else str(item) for item in content]
        return "\n".join(p for p in parts if p)

    if isinstance(content, str):
        # 尝试把 Python repr 格式的 list 转成可读文本
        stripped = content.strip()
        if stripped.startswith("[{") or stripped.startswith("[{'"):
            import ast
            try:
                parsed = ast.literal_eval(stripped)
                if isinstance(parsed, list):
                    texts = [item.get("text", "") if isinstance(item, dict) else str(item) for item in parsed]
                    return "\n".join(t for t in texts if t)
            except (ValueError, SyntaxError):
                pass
        return content

    return str(content)


def _fmt_args(args: object) -> str:
    if isinstance(args, dict):
        return ", ".join(f"{k}={v}" for k, v in args.items())
    s = str(args).strip()
    return s if s else ""


def parse_tool_messages(msgs: list) -> list[ToolCall]:
    """
顺序配对 AI tool_calls 与 tool result，跳过 name=null 的初始消息。"""

    # 第一遍：收集所有 pending 调用（按出现顺序）
    pending: list[tuple[str, str]] = []   # [(name, args), ...]
    results: list[tuple[str, str, bool]] = []  # [(name, content, is_error), ...]

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
            name = msg["name"]
            raw = _extract_text(msg.get("content", ""))
            is_error = "Error:" in raw or "ToolException" in raw
            # 截断过长内容
            preview = raw.replace("\n", " ").strip()
            if len(preview) > 300:
                preview = preview[:300] + "…"
            results.append((name, preview, is_error))

    # 第二遍：按顺序配对（同名工具可能多次调用，FIFO 匹配）
    from collections import deque
    queues: dict[str, deque] = {}
    for name, args in pending:
        queues.setdefault(name, deque()).append(args)

    calls: list[ToolCall] = []
    for name, preview, is_error in results:
        args = queues.get(name, deque())
        matched_args = args.popleft() if args else ""
        calls.append(ToolCall(name=name, args=matched_args, result=preview, is_error=is_error))

    return calls


def load_log(path: str) -> tuple[dict, list[StepRecord]]:
    header: dict = {}
    records: list[StepRecord] = []

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue

            if e.get("type") == "run_header":
                header = e
                continue

            if "tokens_in" not in e or "step" not in e:
                continue

            tool_calls = parse_tool_messages(e.get("tool_messages") or [])

            records.append(StepRecord(
                ts=e.get("ts", ""),
                step=int(e["step"]),
                agent=e.get("agent", "?"),
                model=e.get("model", "?"),
                duration_s=float(e.get("duration_s", 0)),
                tokens_in=int(e.get("tokens_in", 0)),
                tokens_out=int(e.get("tokens_out", 0)),
                prompt_hash=e.get("prompt_hash", ""),
                response=e.get("response", ""),
                tool_calls=tool_calls,
            ))

    return header, records


# ──────────────────────────────────────────────────────────────────
# 渲染
# ──────────────────────────────────────────────────────────────────

def render_md(path: str, header: dict, records: list[StepRecord]) -> str:
    m = re.search(r"chapter_(\d+)_(\d{8}_\d{6})", os.path.basename(path))
    ch = int(m.group(1)) if m else 0
    ts_raw = m.group(2) if m else ""
    ts_fmt = (
        f"{ts_raw[:4]}-{ts_raw[4:6]}-{ts_raw[6:8]} {ts_raw[9:11]}:{ts_raw[11:13]}"
        if ts_raw else ""
    )
    git = header.get("git_commit", "")

    total_in = sum(r.tokens_in for r in records)
    total_out = sum(r.tokens_out for r in records)
    total_dur = sum(r.duration_s for r in records)
    total_dur_str = f"{total_dur/60:.1f}m" if total_dur >= 60 else f"{total_dur:.1f}s"

    out: list[str] = []
    out.append(f"# 第{ch}章 · 运行日志")
    out.append("")
    out.append("| | |")
    out.append("|--|--|")
    out.append(f"| 时间 | {ts_fmt} |")
    if git:
        out.append(f"| Git | `{git}` |")
    out.append(f"| Steps | {len(records)} |")
    out.append(f"| Tokens | {total_in:,} in / {total_out:,} out |")
    out.append(f"| 耗时 | {total_dur_str} |")
    out.append("")
    out.append("---")
    out.append("")

    for r in records:
        dur_str = f"{r.duration_s/60:.1f}m" if r.duration_s >= 60 else f"{r.duration_s:.1f}s"

        out.append(f"## Step {r.step} · {r.agent}")
        out.append("")
        out.append("| | |")
        out.append("|--|--|")
        out.append(f"| 模型 | `{r.model}` |")
        out.append(f"| 耗时 | {dur_str} |")
        out.append(f"| Tokens | {r.tokens_in:,} in / {r.tokens_out:,} out |")
        if r.prompt_hash:
            out.append(f"| Prompt hash | `{r.prompt_hash}` |")
        out.append("")

        if r.tool_calls:
            out.append("### 工具调用")
            out.append("")
            for tc in r.tool_calls:
                icon = "✗" if tc.is_error else "✓"
                args_str = f"({tc.args})" if tc.args else "()"
                out.append(f"- **{icon} `{tc.name}`**{args_str}")
                out.append(f"  > {tc.result}")
                out.append("")

        out.append("### 输出")
        out.append("")
        out.append(r.response.strip())
        out.append("")
        out.append("---")
        out.append("")

    return "\n".join(out)


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


def export_log(path: str, out_dir: str) -> str:
    header, records = load_log(path)
    md = render_md(path, header, records)
    base = os.path.splitext(os.path.basename(path))[0]
    out_path = os.path.join(out_dir, base + ".md")
    os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    return out_path


# ──────────────────────────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="日志 → Markdown 导出")
    parser.add_argument("--chapter", "-c", type=int, help="指定章节号（如 6）")
    parser.add_argument("--run", "-r", type=str, help="指定 run 文件名（不含 .ndjson）")
    parser.add_argument("--out", "-o", type=str, default="reports", help="输出目录（默认 reports/）")
    args = parser.parse_args()

    out_dir = os.path.join(os.path.dirname(__file__), "..", args.out)

    if args.run:
        path = os.path.join(LOGS_DIR, args.run + ".ndjson")
        if not os.path.exists(path):
            path = os.path.join(LOGS_DIR, args.run)
        if not os.path.exists(path):
            print(f"找不到: {path}", file=sys.stderr)
            sys.exit(1)
        out = export_log(path, out_dir)
        print(f"✓ {out}")
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
        out = export_log(latest[ch], out_dir)
        print(f"✓ {out}")


if __name__ == "__main__":
    main()
