#!/usr/bin/env python3
"""校验 manifest 已接线 agent 是否符合 Agent Package 规范。

用法:
    uv run python scripts/validate_agent_packages.py
    uv run python scripts/validate_agent_packages.py --manifest tests/engine/fixtures/test_pipeline_manifest.json

退出码: 0 通过，1 存在错误
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src" / "backend"))

from engine.validator.agent_package_check import (  # noqa: E402
    check_manifest_agent_packages,
    load_manifest,
)
from utils.paths import AGENTS_DIR, manifest_path  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        default=manifest_path(),
        help="pipeline manifest JSON 路径",
    )
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    errors = check_manifest_agent_packages(manifest, AGENTS_DIR, require_meta=True)
    if not errors:
        print(f"[OK] {args.manifest} — 全部 agent 包结构检查通过")
        return 0
    print(f"[FAIL] {args.manifest} — {len(errors)} 个问题:\n")
    for e in errors:
        print(f"  - {e}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
