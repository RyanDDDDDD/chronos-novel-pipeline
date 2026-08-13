"""Report generation: Token consumption summary from engine_server NDJSON log."""
from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, cast

from utils.paths import engine_logs_dir


@dataclass(frozen=True)
class CallRecord:
    ts: str
    step: int
    agent: str
    model: str
    duration_s: float
    tokens_in: int
    tokens_out: int
    tokens_cached: int = 0


@dataclass
class PhaseSummary:
    """Single step (step) × phase (agent label) summary."""

    step: int
    agent: str
    models: set[str] = field(default_factory=set)
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    duration_s: float = 0.0
    call_count: int = 0


def load_call_records(path: str) -> list[CallRecord]:
    records: list[CallRecord] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "tokens_in" not in e or "step" not in e:
                continue
            records.append(CallRecord(
                ts=e.get("ts", ""),
                step=int(e["step"]),
                agent=e.get("agent", "?"),
                model=e.get("model", "?"),
                duration_s=float(e.get("duration_s", 0)),
                tokens_in=int(e.get("tokens_in", 0)),
                tokens_out=int(e.get("tokens_out", 0)),
                tokens_cached=int(e.get("tokens_cached", 0)),
            ))
    return records


def load_run_header(path: str) -> dict[str, Any]:
    """
Read the first run_header in the log (if it exists)."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = cast(dict[str, Any], json.loads(line))
                if e.get("type") == "run_header":
                    return e
            except json.JSONDecodeError:
                continue
    return {}


def aggregate_by_phase(records: list[CallRecord]) -> list[PhaseSummary]:
    by_key: dict[tuple[int, str], PhaseSummary] = {}
    for r in records:
        key = (r.step, r.agent)
        if key not in by_key:
            by_key[key] = PhaseSummary(step=r.step, agent=r.agent)
        s = by_key[key]
        s.models.add(r.model)
        s.tokens_in += r.tokens_in
        s.tokens_out += r.tokens_out
        s.tokens_cached += r.tokens_cached
        s.duration_s += r.duration_s
        s.call_count += 1
    return sorted(by_key.values(), key=lambda x: (x.step, x.agent))


def parse_log_name(path: str) -> tuple[int, str]:
    """Return (chapter, timestamp_str)."""
    name = os.path.splitext(os.path.basename(path))[0]
    m = re.match(r"chapter_(\d+)_(\d{8}_\d{6})", name)
    if m:
        return int(m.group(1)), m.group(2)
    return 0, name


def list_chapter_logs(
    chapter: int | None = None,
    logs_dir: str | None = None,
) -> list[str]:
    root = logs_dir or engine_logs_dir()
    pattern = os.path.join(root, "*.json")
    files = sorted(glob.glob(pattern))
    if chapter is not None:
        prefix = f"chapter_{chapter:03d}_"
        files = [f for f in files if os.path.basename(f).startswith(prefix)]
    return files


def latest_log_per_chapter(logs: list[str]) -> dict[int, str]:
    best: dict[int, str] = {}
    for path in logs:
        ch, ts = parse_log_name(path)
        if ch not in best or ts > parse_log_name(best[ch])[1]:
            best[ch] = path
    return best


def _fmt_duration(seconds: float) -> str:
    if seconds >= 60:
        return f"{seconds / 60:.1f}m"
    return f"{seconds:.1f}s"


def _full_price_load(tokens_in: int, tokens_out: int, tokens_cached: int) -> int:
    return (tokens_in - tokens_cached) + tokens_out


def build_token_report(
    chapter: int,
    summaries: list[PhaseSummary],
    *,
    model_hint: str = "",
    git_commit: str = "",
    log_name: str = "",
) -> str:
    """
Generate chapter token consumption Markdown report."""
    total_in = total_out = total_cached = 0
    rows: list[str] = []

    for s in summaries:
        uncached = s.tokens_in - s.tokens_cached
        total_in += s.tokens_in
        total_out += s.tokens_out
        total_cached += s.tokens_cached
        calls = f"×{s.call_count}" if s.call_count > 1 else ""
        model = "/".join(sorted(s.models)) if s.models else model_hint
        rows.append(
            f"| {s.step:2d} | {s.agent} | {calls} | {s.tokens_in:,} | {s.tokens_cached:,} | "
            f"{uncached:,} | {s.tokens_out:,} | "
            f"{s.tokens_in + s.tokens_out:,} | {_fmt_duration(s.duration_s)} | {model} |"
        )

    meta_lines = [
        f"# 第{chapter}章 Token 消耗报告",
        "",
        f"**生成日期**：{date.today()}",
    ]
    if model_hint:
        meta_lines.append(f"**模型**：{model_hint}  ")
    if log_name:
        meta_lines.append(f"**日志**：{log_name}  ")
    if git_commit:
        meta_lines.append(f"**git**：{git_commit}  ")
    meta_lines.append("")

    lines = [
        *meta_lines,
        "| Seg | Phase | Calls | Input | Cached | Uncached | Output | 合计 | 耗时 | Model |",
        "|----:|-------|------:|------:|-------:|---------:|-------:|-----:|-----:|-------|",
        *rows,
        (
            f"| **—** | **合计** | | **{total_in:,}** | **{total_cached:,}** | "
            f"**{total_in - total_cached:,}** | **{total_out:,}** | "
            f"**{total_in + total_out:,}** | | |"
        ),
    ]
    return "\n".join(lines)


def build_token_report_from_log(path: str) -> str:
    """Generate Markdown reports from a single NDJSON log."""
    chapter, _ = parse_log_name(path)
    header = load_run_header(path)
    summaries = aggregate_by_phase(load_call_records(path))
    models = sorted({m for s in summaries for m in s.models})
    return build_token_report(
        chapter,
        summaries,
        model_hint="/".join(models),
        git_commit=str(header.get("git_commit", "") or ""),
        log_name=os.path.basename(path),
    )


def format_run_table(
    path: str,
    records: list[CallRecord],
    *,
    show_header: bool = True,
) -> str:
    """
ASCII table for the terminal (scripts/token_report.py)."""
    chapter, _ = parse_log_name(path)
    summaries = aggregate_by_phase(records)
    if not summaries:
        return "  (空日志)\n"

    total_in = sum(s.tokens_in for s in summaries)
    total_out = sum(s.tokens_out for s in summaries)
    total_cached = sum(s.tokens_cached for s in summaries)
    total_dur = sum(s.duration_s for s in summaries)
    sep = "─" * 80
    lines: list[str] = []

    if show_header:
        header_rec = load_run_header(path)
        git_str = f"  git={header_rec['git_commit']}" if header_rec.get("git_commit") else ""
        lines.extend([
            f"\n第{chapter}章 · {os.path.basename(path)}{git_str}",
            sep,
        ])

    lines.extend([
        f"{'Seg':>4}  {'Phase':<22}  {'calls':>5}  {'in':>9}  {'cached':>9}  "
        f"{'uncached':>9}  {'out':>9}  {'全价负荷':>9}  {'dur':>7}  model",
        sep,
    ])

    max_load = max(
        (_full_price_load(s.tokens_in, s.tokens_out, s.tokens_cached) for s in summaries),
        default=0,
    )

    for s in summaries:
        uncached = s.tokens_in - s.tokens_cached
        load = uncached + s.tokens_out
        flag = " ◄" if load == max_load and len(summaries) > 1 else ""
        model_str = "/".join(sorted(s.models))
        calls_str = f"×{s.call_count}" if s.call_count > 1 else ""
        lines.append(
            f"  {s.step:>2}  {s.agent:<22}  {calls_str:>5}  "
            f"{s.tokens_in:>9,}  {s.tokens_cached:>9,}  {uncached:>9,}  "
            f"{s.tokens_out:>9,}  {load:>9,}  {_fmt_duration(s.duration_s):>7}  "
            f"{model_str}{flag}"
        )

    t_uncached = total_in - total_cached
    lines.extend([
        sep,
        (
            f"  {'Total':<27}  {total_in:>9,}  {total_cached:>9,}  {t_uncached:>9,}  "
            f"{total_out:>9,}  {t_uncached + total_out:>9,}  {_fmt_duration(total_dur):>7}"
        ),
        "",
    ])
    return "\n".join(lines)


def format_trend_table(paths: list[str]) -> str:
    """Trend table across runs (one row per run for total tokens)."""
    if not paths:
        return ""
    chapter, _ = parse_log_name(paths[0])
    sep = "─" * 80
    lines = [
        f"\n第{chapter}章 · 历史趋势 ({len(paths)} 次运行)",
        sep,
        f"  {'时间':<20}  {'phases':>6}  {'tokens_in':>10}  {'tokens_out':>10}  "
        f"{'duration':>8}",
        sep,
    ]

    for path in paths:
        records = load_call_records(path)
        if not records:
            continue
        _, ts = parse_log_name(path)
        ts_fmt = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}"
        summaries = aggregate_by_phase(records)
        ti = sum(s.tokens_in for s in summaries)
        to = sum(s.tokens_out for s in summaries)
        dur = sum(s.duration_s for s in summaries)
        lines.append(
            f"  {ts_fmt:<20}  {len(summaries):>6}  {ti:>10,}  {to:>10,}  "
            f"{_fmt_duration(dur):>8}"
        )

    lines.append(sep)
    return "\n".join(lines)
