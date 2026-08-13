"""
skill 注册表校验器

用法：
  uv run python scripts/skill_lint.py                 # 扫内建 + 导入两目录
  uv run python scripts/skill_lint.py --dir <path>    # 只扫指定目录（可重复，首个视为内建）
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from engine.setup_chat.skill_lint import lint_dirs
from engine.setup_chat.skills import setup_chat_skill_dirs


def main() -> int:
    ap = argparse.ArgumentParser(description="校验 setup-chat skill 注册表（含外部导入目录）")
    ap.add_argument("--dir", action="append", default=None,
                    help="只扫指定目录（可重复；首个视为内建）。缺省 = 内建 + data/skills 导入目录")
    args = ap.parse_args()
    dirs = args.dir or setup_chat_skill_dirs()
    findings = lint_dirs(dirs)
    for level, name, msg in findings:
        print(f"[{level.upper():7}] {name}: {msg}")
    errors = sum(1 for lv, _n, _m in findings if lv == "error")
    print(f"—— 共 {len(findings)} 条（error {errors}，warning {len(findings) - errors}）")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
