"""
Dispatch a plan/spec (or an ad-hoc prompt) to the Cursor headless CLI (`cursor-agent`),
running it inside an isolated git worktree so implementation can happen without opening
the Cursor app. Prints the worktree path, branch, and log file on exit so the caller can
`git diff` / run the project's gates and review before deciding what to do with the branch.

Prerequisites:
  - Cursor CLI installed (Windows: irm 'https://cursor.com/install?win32=true' | iex).
  - Authenticated once via `cursor-agent login` (browser login, billed against the
    user's Cursor Plan subscription -- not CURSOR_API_KEY, which is metered separately
    and only needed where interactive login isn't possible, e.g. containers/CI).

Usage:
  uv run python scripts/cursor_dispatch.py docs/superpowers/plans/2026-07-18-foo.md
  uv run python scripts/cursor_dispatch.py docs/superpowers/plans/2026-07-18-foo.md --base-ref dev
  uv run python scripts/cursor_dispatch.py --prompt "fix: tighten the X validator" --name quick-fix

Output: worktree path + branch name + log path, printed on stdout as soon as dispatch
starts (before Cursor finishes) plus a final status line. This script runs synchronously
end-to-end; run it via a backgrounded shell call to avoid blocking the caller, and tail
the printed log path (e.g. with the Monitor tool) to watch progress -- the log is
`--output-format stream-json --stream-partial-output`, i.e. NDJSON events as Cursor works,
not just a final blob. This script does not review the diff or open a PR -- that's left
to the caller (see CLAUDE.md rule 14).
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = REPO_ROOT / "logs" / "cursor_dispatch"

# Emitted by the dispatched agent after each plan task -- grep the stream-json log (or a
# live Monitor tail) for this prefix to drive external per-task progress tracking.
TASK_MARKER_PREFIX = "TASK_DONE:"


def find_cli() -> str:
    """Locate the cursor-agent executable, preferring PATH.

    The Windows installer drops it under %LOCALAPPDATA%\\cursor-agent, which a shell
    started before install (or before a PATH refresh) won't see yet -- so fall back to
    the known install path.
    """
    for name in ("cursor-agent", "agent"):
        found = shutil.which(name)
        if found:
            return found
    fallback = Path(os.environ.get("LOCALAPPDATA", "")) / "cursor-agent" / "cursor-agent.cmd"
    if fallback.exists():
        return str(fallback)
    raise SystemExit(
        "cursor-agent CLI not found on PATH. Install with:\n"
        "  irm 'https://cursor.com/install?win32=true' | iex"
    )


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return slug[:40] or "task"


# This worktree is freshly created and has neither .venv nor node_modules yet. Running
# setup_worktree.py first (fast copy from the main checkout) instead of a from-scratch
# `uv sync`/`npm install` avoids that cold-start path.
#
# --skip-testmon: the commit-gate pre-commit hook doesn't run pytest at all anymore (ruff/
# mypy only -- see docs/TECHNICAL_JOURNEY.md #32), and this dispatch flow never merges/
# pushes (the two hooks that do run full pytest), so a pre-warmed `.testmondata` baseline
# buys this workflow nothing -- verification happens via a direct `pytest` run by the
# caller after dispatch completes. Building it anyway is actively harmful here: Cursor's
# own shell tool backgrounds any command past its ~30s soft timeout instead of waiting or
# killing it (reporting a premature `exitCode: 0` to the agent in the meantime), and a cold
# full-suite testmon baseline routinely takes far longer than that -- the orphaned
# background run then keeps this whole dispatch's process tree alive long after the
# agent's actual work is done and committed, so `run_dispatch()`'s blocking subprocess.run
# below hangs waiting for a process that has nothing left to do (see #33).
_SETUP_INSTRUCTION = (
    "First run `python scripts/setup_worktree.py --skip-testmon` (plain python, not "
    "`uv run`) to provision .venv/node_modules -- faster and safer than letting `uv sync`/"
    "`npm install` run from scratch. "
)


# Commits land under the user's name only -- no agent co-authorship. Cursor's own
# Co-authored-by trailer is off via ~/.cursor/cli-config.json attribution flags; this
# line stops the agent adding one by hand (and overrides any stale CLAUDE.md wording).
_NO_ATTRIBUTION = (
    " Do NOT add any Co-Authored-By / Co-authored-by / agent-attribution trailer to "
    "commit messages -- the commit is authored by the user alone."
)


def build_prompt(plan: Path | None, raw_prompt: str | None) -> str:
    if raw_prompt:
        return _SETUP_INSTRUCTION + raw_prompt + _NO_ATTRIBUTION
    rel = plan.relative_to(REPO_ROOT) if plan.is_relative_to(REPO_ROOT) else plan  # type: ignore[union-attr]
    return (
        _SETUP_INSTRUCTION +
        f"Then implement the plan at {rel}. Follow CLAUDE.md conventions "
        "(coding standards, commit style). The plan is split into '## Task N: ...' "
        "sections -- immediately after fully completing each one (before starting the "
        f'next), run `echo "{TASK_MARKER_PREFIX} Task N"` (substituting its number) so '
        "progress can be tracked externally. When finished, commit your changes with a "
        "Conventional Commits message. Do not push and do not open a pull request." +
        _NO_ATTRIBUTION
    )


def current_branch(cwd: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=cwd, capture_output=True, text=True, check=True,
    ).stdout.strip()


def resolve_worktree_path(worktree_name: str) -> Path:
    return Path.home() / ".cursor" / "worktrees" / REPO_ROOT.name / worktree_name


def build_cmd(cli: str, prompt: str, worktree_name: str, base_ref: str, model: str | None) -> list[str]:
    cmd = [
        cli, "-p", "--force", "--trust",
        "--worktree", worktree_name,
        "--worktree-base", base_ref,
        "--output-format", "stream-json",
        "--stream-partial-output",
    ]
    if model:
        cmd += ["--model", model]
    cmd.append(prompt)
    return cmd


def new_log_path(worktree_name: str) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return LOG_DIR / f"{ts}_{worktree_name}.log"


def run_dispatch(cmd: list[str], log_path: Path) -> int:
    with open(log_path, "w", encoding="utf-8") as log_f:
        log_f.write(f"$ {' '.join(cmd)}\n\n")
        log_f.flush()
        result = subprocess.run(cmd, cwd=REPO_ROOT, stdout=log_f, stderr=subprocess.STDOUT)
    return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dispatch a task to the Cursor headless CLI in an isolated worktree."
    )
    parser.add_argument("plan", nargs="?", type=Path, help="Path to a plan/spec markdown file to implement.")
    parser.add_argument("--prompt", type=str, help="Ad-hoc prompt instead of a plan file.")
    parser.add_argument("--name", type=str, help="Worktree/branch name (default: derived from plan filename or prompt).")
    parser.add_argument("--base-ref", type=str, default=None, help="Branch/ref to base the worktree on (default: current HEAD branch).")
    parser.add_argument("--model", type=str, default=None, help="Model override, e.g. 'sonnet-4.5' or 'claude-opus-4-8[effort=high]'.")
    args = parser.parse_args()

    if not args.plan and not args.prompt:
        parser.error("Provide a plan file path or --prompt.")

    base_ref = args.base_ref or current_branch(REPO_ROOT)
    name = args.name or slugify(args.plan.stem if args.plan else (args.prompt or "")[:40])
    prompt = build_prompt(args.plan, args.prompt)

    cli = find_cli()
    cmd = build_cmd(cli, prompt, name, base_ref, args.model)
    log_path = new_log_path(name)

    print(f"Dispatching to Cursor: worktree={name} base={base_ref}")
    print(f"  log: {log_path}  (tail -f this, or use Monitor, to watch progress)")
    sys.stdout.flush()

    exit_code = run_dispatch(cmd, log_path)

    worktree_path = resolve_worktree_path(name)
    if not worktree_path.exists():
        print(f"worktree not found at expected path: {worktree_path}", file=sys.stderr)
        print(f"see log: {log_path}", file=sys.stderr)
        sys.exit(exit_code or 1)

    branch = subprocess.run(
        ["git", "-C", str(worktree_path), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()

    status = "OK" if exit_code == 0 else "FAILED"
    print(f"[{status}] exit={exit_code}")
    print(f"  worktree: {worktree_path}")
    print(f"  branch:   {branch}")
    print(f"  log:      {log_path}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
