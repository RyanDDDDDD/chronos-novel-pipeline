"""
engine_server NDJSON 日志 → 解析并输出 LLM 的 system / user prompt 与回复。

日志格式见 `src/backend/llm/prompt_logger.py`：无 `type` 字段且含
`system`、`user`、`response` 的行即为一次 LLM 调用。

用法：
  uv run python scripts/prompt_parse.py logs/engine_server/chapter_006_20260602_182304.json
  uv run python scripts/prompt_parse.py            # 不带参数=自动取最新一次执行的日志
  uv run python scripts/prompt_parse.py --split     # 最新日志全部调用，各存一个独立文件
  uv run python scripts/prompt_parse.py -c 6
  uv run python scripts/prompt_parse.py -c 6 --step 21 --agent synthesis
  uv run python scripts/prompt_parse.py path/to/log.json --index 3 -o out.txt
  uv run python scripts/prompt_parse.py path/to/log.json --list
  uv run python scripts/prompt_parse.py path/to/log.json --format json -o calls.json
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from dataclasses import asdict, dataclass

LOGS_DIR = os.path.join(os.path.dirname(__file__), "..", "logs", "engine_server")

SEP = "=" * 80
SUBSEP = "-" * 40


@dataclass
class LlmCall:
    """
单次 LLM 调用（prompt_logger sink 写入的一行）。"""


    index: int
    ts: str
    step: int
    agent: str
    model: str
    duration_s: float
    tokens_in: int
    tokens_out: int
    prompt_hash: str
    system: str
    user: str
    response: str


def is_llm_entry(entry: dict) -> bool:
    return (
        entry.get("type") is None
        and "system" in entry
        and "user" in entry
        and "response" in entry
        and entry.get("step") is not None
    )


def load_llm_calls(path: str) -> tuple[dict, list[LlmCall]]:
    """读取 NDJSON，返回 (run_header, llm_calls)。"""

    header: dict = {}
    calls: list[LlmCall] = []
    idx = 0

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

            if not is_llm_entry(e):
                continue

            calls.append(
                LlmCall(
                    index=idx,
                    ts=str(e.get("ts", "")),
                    step=int(e["step"]),
                    agent=str(e.get("agent", "?")),
                    model=str(e.get("model", "?")),
                    duration_s=float(e.get("duration_s", 0)),
                    tokens_in=int(e.get("tokens_in", 0)),
                    tokens_out=int(e.get("tokens_out", 0)),
                    prompt_hash=str(e.get("prompt_hash", "")),
                    system=str(e.get("system", "")),
                    user=str(e.get("user", "")),
                    response=str(e.get("response", "")),
                )
            )
            idx += 1

    return header, calls


def filter_calls(
    calls: list[LlmCall],
    *,
    step: int | None = None,
    agent: str | None = None,
    index: int | None = None,
) -> list[LlmCall]:
    out = calls
    if step is not None:
        out = [c for c in out if c.step == step]
    if agent is not None:
        out = [c for c in out if c.agent == agent]
    if index is not None:
        # 有 step/agent 筛选时，index 指筛选结果内的第 N 条；否则为全文件全局序号
        scoped = step is not None or agent is not None
        if scoped:
            if index < 0 or index >= len(out):
                return []
            out = [out[index]]
        else:
            out = [c for c in out if c.index == index]
    return out


def format_call_text(call: LlmCall, *, total: int) -> str:
    header = (
        f"# Call {call.index + 1}/{total}  "
        f"S{call.step:02d} {call.agent}  {call.model}  "
        f"in={call.tokens_in} out={call.tokens_out}  "
        f"{call.duration_s:.2f}s  hash={call.prompt_hash}"
    )
    if call.ts:
        header += f"\n# ts: {call.ts}"

    parts = [
        SEP,
        header,
        SEP,
        "",
        f"{SUBSEP} SYSTEM {SUBSEP}",
        call.system,
        "",
        f"{SUBSEP} USER {SUBSEP}",
        call.user,
        "",
        f"{SUBSEP} RESPONSE {SUBSEP}",
        call.response,
        "",
    ]
    return "\n".join(parts)


def format_list(calls: list[LlmCall]) -> str:
    lines = [f"共 {len(calls)} 次 LLM 调用：", ""]
    for c in calls:
        lines.append(
            f"  [{c.index:3d}] S{c.step:02d} {c.agent:16s} {c.model:20s} "
            f"in={c.tokens_in:6d} out={c.tokens_out:6d} "
            f"sys={len(c.system):6d} user={len(c.user):6d} resp={len(c.response):6d}"
        )
    return "\n".join(lines)


def find_latest_log() -> str:
    """
logs/engine_server 下按修改时间最新的日志（不分章节）。无日志 → 退出。"""

    files = glob.glob(os.path.join(LOGS_DIR, "*.json"))
    if not files:
        print("logs/engine_server 下无日志", file=sys.stderr)
        sys.exit(1)
    return os.path.abspath(max(files, key=os.path.getmtime))


_FNAME_BAD = re.compile(r"[^\w.-]+")


def split_filename(call: LlmCall) -> str:
    """单次调用的独立文件名：序号_步骤_agent（agent 里的 :// 等非法字符归一为 _）。"""

    agent = _FNAME_BAD.sub("_", call.agent).strip("_") or "agent"
    return f"{call.index:03d}_S{call.step:02d}_{agent}.txt"


def default_split_dir(log_path: str) -> str:
    """
--split 未给目录时的默认落点：logs/parsed/<日志名>/。"""

    stem = os.path.splitext(os.path.basename(log_path))[0]
    return os.path.join(os.path.dirname(__file__), "..", "logs", "parsed", stem)


def write_split(calls: list[LlmCall], out_dir: str, *, total: int) -> int:
    """把每次调用各写一个独立文件到 out_dir，返回写出文件数。"""

    os.makedirs(out_dir, exist_ok=True)
    for c in calls:
        with open(os.path.join(out_dir, split_filename(c)), "w", encoding="utf-8") as f:
            f.write(format_call_text(c, total=total))
    return len(calls)


def resolve_log_path(
    path: str | None,
    *,
    chapter: int | None,
    run: str | None,
) -> str:
    if path:
        if os.path.isfile(path):
            return os.path.abspath(path)
        alt = os.path.join(LOGS_DIR, path)
        if os.path.isfile(alt):
            return os.path.abspath(alt)
        if not path.endswith(".json"):
            alt2 = alt + ".json"
            if os.path.isfile(alt2):
                return os.path.abspath(alt2)
        print(f"找不到日志: {path}", file=sys.stderr)
        sys.exit(1)

    if run:
        candidate = run if run.endswith(".json") else run + ".json"
        full = os.path.join(LOGS_DIR, os.path.basename(candidate))
        if os.path.isfile(full):
            return full
        print(f"找不到日志: {full}", file=sys.stderr)
        sys.exit(1)

    if chapter is not None:
        pattern = os.path.join(LOGS_DIR, f"chapter_{chapter:03d}_*.json")
        files = sorted(glob.glob(pattern))
        if not files:
            print(f"第 {chapter} 章无 engine_server 日志", file=sys.stderr)
            sys.exit(1)
        return files[-1]

    # 不带任何选择参数 → 自动取最新一次执行的日志
    return find_latest_log()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="解析 engine_server 日志，输出 system/user prompt 与 LLM 回复",
    )
    parser.add_argument(
        "path",
        nargs="?",
        help="NDJSON 日志路径（可相对项目根或 logs/engine_server）",
    )
    parser.add_argument("-c", "--chapter", type=int, help="章节号，取该章最新日志")
    parser.add_argument("-r", "--run", help="run 文件名，如 chapter_006_20260602_182304")
    parser.add_argument("--step", type=int, help="只输出指定步骤号的调用")
    parser.add_argument("--agent", help="只输出指定 agent（如 synthesis、dialogue）")
    parser.add_argument(
        "--index",
        type=int,
        help="只输出第 N 次调用（0 起；配合 --step/--agent 时为筛选内序号，否则为全文件序号）",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出所有 LLM 调用摘要，不输出正文",
    )
    parser.add_argument(
        "-o",
        "--out",
        help="写入文件（默认 stdout）",
    )
    parser.add_argument(
        "--split",
        nargs="?",
        const="__AUTO__",
        default=None,
        metavar="DIR",
        help="每次调用各存一个独立文件到 DIR（省略 DIR 则落 logs/parsed/<日志名>/）",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="输出格式（默认 text）",
    )
    args = parser.parse_args()

    log_path = resolve_log_path(args.path, chapter=args.chapter, run=args.run)
    header, all_calls = load_llm_calls(log_path)
    calls = filter_calls(
        all_calls,
        step=args.step,
        agent=args.agent,
        index=args.index,
    )

    if not calls and args.index is not None:
        scoped = args.step is not None or args.agent is not None
        hint = (
            f"筛选结果内无第 {args.index} 条"
            if scoped
            else f"全局 index={args.index} 不存在（本文件共 {len(all_calls)} 次）"
        )
        print(hint, file=sys.stderr)
        sys.exit(1)
    if not calls:
        print("没有匹配的 LLM 调用", file=sys.stderr)
        sys.exit(1)

    if args.split is not None:
        out_dir = default_split_dir(log_path) if args.split == "__AUTO__" else args.split
        n = write_split(calls, out_dir, total=len(all_calls))
        print(f"✓ {n} 个文件写入 {os.path.abspath(out_dir)}", file=sys.stderr)
        return

    if args.list:
        body = format_list(calls if (args.step or args.agent) else all_calls)
    elif args.format == "json":
        payload = {
            "log_file": log_path,
            "run_header": header,
            "calls": [asdict(c) for c in calls],
        }
        body = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        total = len(all_calls)
        blocks = [format_call_text(c, total=total) for c in calls]
        body = "\n".join(blocks)

    if args.out:
        out_path = args.out
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(body)
        print(f"✓ {out_path} ({len(calls)} call(s))", file=sys.stderr)
    else:
        # Windows 控制台 UTF-8
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass
        sys.stdout.write(body)
        if not body.endswith("\n"):
            sys.stdout.write("\n")


if __name__ == "__main__":
    main()
