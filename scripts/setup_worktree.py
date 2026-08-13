"""Fast-provision a freshly created git worktree's gitignored dev state
(.venv, src/frontend/node_modules) by copying it from the repo's main
checkout instead of resolving/downloading everything from scratch.

Why this exists: `git worktree add` (and anything built on it -- Claude Code's
own worktree tool, cursor-agent's `--worktree`) only materializes tracked
files. `.venv/` and `node_modules/` are gitignored, so every fresh worktree
starts without them, and `uv sync --all-extras` / `npm install` from a cold
cache can take minutes. Copying an already-resolved .venv/node_modules tree
is close to instant (same OS, same interpreter, same lockfiles) and correct:
uv's own package layout doesn't embed the venv's absolute path anywhere `uv
run` cares about (pyvenv.cfg's "home" points at the base interpreter install,
not at itself), so a plain directory copy is a valid venv. The activate
scripts *do* embed the old path, but this project's convention is `uv run
python ...`, never manual activation, so that's not a correctness issue here.

Run with a plain `python` (NOT `uv run python`) -- if .venv doesn't exist yet,
`uv run` would trigger the exact slow from-scratch sync this script exists to
avoid. This script has no third-party dependencies.

Usage:
    python scripts/setup_worktree.py                # target = cwd's worktree root
    python scripts/setup_worktree.py <worktree-path> # explicit target
    python scripts/setup_worktree.py --skip-npm      # .venv only
    python scripts/setup_worktree.py --skip-uv       # node_modules only
    python scripts/setup_worktree.py --skip-testmon  # skip baseline build below

After copying, runs `uv sync --all-extras` and `npm install` in the target to
reconcile against the lockfiles (fast when the copy already matches; falls
back to a real install when there's no source to copy from, e.g. the main
checkout itself has no .venv yet).

Finally builds a `pytest --testmon` baseline (`.testmondata`) in the target.
Why here and not left to the first `git commit`: a cold worktree has no
baseline, so pytest-testmon's first run must execute the entire suite under
coverage instrumentation to build one (a few minutes) -- doing that inside
the pre-commit hook's critical path risks tripping an external caller's own
timeout (observed with Cursor's headless CLI: it timed out a long-running
cold `pytest --testmon`, killed the wrong PID in the process tree, and left
an orphaned process holding `.testmondata`'s WAL lock, wedging every
subsequent retry -- see docs/TECHNICAL_JOURNEY.md #30). Building the
baseline here instead means it's already warm by the time any commit
happens, so the hook only ever pays testmon's fast incremental-selection
cost, never the cold-baseline cost.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def find_main_worktree(target: Path) -> Path:
    """The first entry of `git worktree list` is always the repo's original
    (non-linked) checkout -- that's where a fully-synced .venv/node_modules
    is expected to live."""
    porcelain = _git(["worktree", "list", "--porcelain"], cwd=target)
    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            return Path(line[len("worktree "):]).resolve()
    raise RuntimeError("`git worktree list` returned no entries")


def robocopy_or_copytree(src: Path, dst: Path, label: str) -> None:
    print(f"[setup_worktree] copying {label}: {src} -> {dst}")
    start = time.monotonic()
    if sys.platform == "win32":
        # /E mirrors subdirs incl. empty ones, /MT parallelizes, /NFL /NDL /NJH /NJS
        # quiet down per-file logging (thousands of files in node_modules otherwise).
        result = subprocess.run(
            ["robocopy", str(src), str(dst), "/E", "/MT:16", "/NFL", "/NDL", "/NJH", "/NJS"],
            capture_output=True, text=True,
        )
        # robocopy's exit codes are a bitmask; 0-7 all mean success, >=8 means failure.
        if result.returncode >= 8:
            raise RuntimeError(f"robocopy failed ({result.returncode}): {result.stderr or result.stdout}")
    else:
        shutil.copytree(src, dst, symlinks=True)
    elapsed = time.monotonic() - start
    print(f"[setup_worktree] {label} copied in {elapsed:.1f}s")


def sync_python_env(target: Path) -> None:
    print("[setup_worktree] uv sync --all-extras (reconciling copied .venv against uv.lock)...")
    subprocess.run(["uv", "sync", "--all-extras"], cwd=target, check=True)


def sync_frontend_env(frontend_dir: Path) -> None:
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    print("[setup_worktree] npm install (reconciling copied node_modules against package-lock.json)...")
    subprocess.run([npm, "install"], cwd=frontend_dir, check=True)


def build_testmon_baseline(target: Path) -> None:
    """Run `pytest --testmon` once so `.testmondata` already exists by the time a real
    `git commit` triggers the pre-commit hook -- see module docstring for why this must not
    be left to happen lazily inside the hook's own (externally time-boxed) critical path."""
    pytest_exe = target / ".venv" / ("Scripts/pytest.exe" if sys.platform == "win32" else "bin/pytest")
    if not pytest_exe.exists():
        print(f"[setup_worktree] {pytest_exe} not found, skipping testmon baseline build.")
        return
    print("[setup_worktree] building pytest-testmon baseline (.testmondata)...")
    start = time.monotonic()
    subprocess.run([str(pytest_exe), "--testmon", "-q"], cwd=target, check=False)
    print(f"[setup_worktree] testmon baseline built in {time.monotonic() - start:.1f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", nargs="?", type=Path, default=Path.cwd(), help="Worktree root to provision (default: cwd).")
    parser.add_argument("--skip-uv", action="store_true", help="Skip .venv copy + uv sync.")
    parser.add_argument("--skip-npm", action="store_true", help="Skip node_modules copy + npm install.")
    parser.add_argument("--skip-testmon", action="store_true", help="Skip the pytest-testmon baseline build.")
    args = parser.parse_args()

    target = args.target.resolve()
    if not (target / "pyproject.toml").exists():
        raise SystemExit(f"{target} doesn't look like the chronos repo root (no pyproject.toml)")

    main_worktree = find_main_worktree(target)
    if main_worktree == target:
        raise SystemExit(f"{target} IS the main worktree -- nothing to provision from.")
    print(f"[setup_worktree] target:  {target}")
    print(f"[setup_worktree] source:  {main_worktree}")

    if not args.skip_uv:
        target_venv = target / ".venv"
        source_venv = main_worktree / ".venv"
        if target_venv.exists():
            print("[setup_worktree] .venv already exists in target, skipping copy.")
        elif source_venv.exists():
            robocopy_or_copytree(source_venv, target_venv, ".venv")
        else:
            print("[setup_worktree] no .venv in main worktree either, skipping copy (uv sync will do a full resolve).")
        sync_python_env(target)

    if not args.skip_npm:
        target_nm = target / "src" / "frontend" / "node_modules"
        source_nm = main_worktree / "src" / "frontend" / "node_modules"
        if target_nm.exists():
            print("[setup_worktree] node_modules already exists in target, skipping copy.")
        elif source_nm.exists():
            robocopy_or_copytree(source_nm, target_nm, "node_modules")
        else:
            print("[setup_worktree] no node_modules in main worktree either, skipping copy (npm install will do a full install).")
        sync_frontend_env(target / "src" / "frontend")

    if not args.skip_testmon:
        # Doesn't require --skip-uv to have been omitted -- build_testmon_baseline already
        # no-ops gracefully if target/.venv/.../pytest doesn't exist, so this must stay
        # decoupled from --skip-uv (e.g. `--skip-uv --skip-npm` is exactly how you'd ask to
        # only rebuild a stale/wiped baseline against an already-provisioned venv).
        build_testmon_baseline(target)

    print("[setup_worktree] done.")


if __name__ == "__main__":
    main()
