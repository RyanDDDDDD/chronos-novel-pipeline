"""Sweep every per-novel chronos.sqlite3 (+ the registry) and bring its Alembic
revision to head. Legacy dbs get stamped, fresh ones get the schema. Run this in a
new worktree or after pulling a migration; the app also auto-migrates each db on
first open (repositories/engine.py), so this is a manual convenience, not a gate."""
from __future__ import annotations

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from repositories.migrations import ensure_novel_db_migrated, ensure_registry_migrated  # noqa: E402
from repositories.registry_store import registry_path  # noqa: E402
from utils.paths import novel_db_path, novels_dir  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="migrate every novel db, not just the active one")
    args = ap.parse_args()

    reg = registry_path()
    ensure_registry_migrated(reg)
    print(f"[ok] registry {reg}")

    if args.all:
        paths = sorted(glob.glob(os.path.join(novels_dir(), "*", "chronos.sqlite3")))
    else:
        paths = [novel_db_path()]
    for p in paths:
        if not os.path.exists(p):
            continue
        ensure_novel_db_migrated(p)
        print(f"[ok] {p}")


if __name__ == "__main__":
    main()
