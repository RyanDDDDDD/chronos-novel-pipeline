#!/usr/bin/env python3
"""根据 pipeline_manifest + Hook 生成/更新各包的 hooks/packages/<pkg>/agent.meta.json。

用法:
    uv run python scripts/sync_agent_meta.py          # 写入缺失或过期 meta
    uv run python scripts/sync_agent_meta.py --check  # 仅检查是否与磁盘一致（CI）

退出码: 0 一致；1 有漂移或错误
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src" / "backend"))

from engine.validator.agent_package_check import (  # noqa: E402
    check_agent_meta_drift,
    collect_expected_metas,
    load_manifest,
    sync_agent_meta_files,
)
from utils.paths import AGENTS_DIR, manifest_path  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=manifest_path())
    parser.add_argument(
        "--check",
        action="store_true",
        help="不写入；若任一 agent.meta.json 与期望不一致则失败",
    )
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    agents_dir = Path(AGENTS_DIR)

    if args.check:
        drift = check_agent_meta_drift(manifest, agents_dir)
        if drift:
            print("[FAIL] agent.meta.json 漂移:")
            for d in drift:
                print(f"  - {d}")
            return 1
        n = len(collect_expected_metas(manifest, agents_dir))
        print(f"[OK] {n} 个 agent.meta.json 与 manifest 一致")
        return 0

    written = sync_agent_meta_files(manifest, agents_dir)
    for pkg in written:
        print(f"  wrote hooks/packages/{pkg}/agent.meta.json")
    print(f"[OK] 已同步 {len(written)} 个 agent.meta.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
