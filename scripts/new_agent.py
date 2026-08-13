#!/usr/bin/env python3
"""从 hooks/packages/_template/ 脚手架生成新 Agent Package。

用法:
    uv run python scripts/new_agent.py my_agent --role my_role
    uv run python scripts/new_agent.py my_agent --role my_role --refine

规范: docs/AGENT_PACKAGE.md
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src" / "backend"))

from utils.paths import AGENTS_DIR  # noqa: E402

TEMPLATE_DIR = Path(AGENTS_DIR) / "_template"
AGENTS_PACKAGES_DIR = Path(AGENTS_DIR)

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _substitute(text: str, package: str, role: str) -> str:
    return text.replace("{package}", package).replace("{role}", role)


def _copy_template(
    src_name: str,
    dest_dir: Path,
    package: str,
    role: str,
) -> None:
    src = TEMPLATE_DIR / src_name
    if not src.is_file():
        raise FileNotFoundError(f"模板缺失: {src}")
    dest_name = _substitute(src_name, package, role)
    dest = dest_dir / dest_name
    if dest.exists():
        raise FileExistsError(f"已存在: {dest}")
    content = _substitute(src.read_text(encoding="utf-8"), package, role)
    dest.write_text(content, encoding="utf-8")
    print(f"  + {dest.relative_to(PROJECT_ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 Agent Package 脚手架")
    parser.add_argument("package", help="目录名，与 manifest agent 字段一致")
    parser.add_argument("--role", required=True, help="主 prompt 角色名（{role}.md）")
    parser.add_argument(
        "--refine", action="store_true", help="复制 refine_analysis 占位（需自行重命名）"
    )
    args = parser.parse_args()

    package, role = args.package, args.role
    if not _NAME_RE.match(package) or not _NAME_RE.match(role):
        print("[ERROR] package/role 须为小写 snake_case", file=sys.stderr)
        return 1

    if not TEMPLATE_DIR.is_dir():
        print(f"[ERROR] 模板目录不存在: {TEMPLATE_DIR}", file=sys.stderr)
        return 1

    dest_dir = AGENTS_PACKAGES_DIR / package
    if dest_dir.exists():
        print(f"[ERROR] 目录已存在: {dest_dir}", file=sys.stderr)
        return 1

    dest_dir.mkdir(parents=True)
    print(f"创建 hooks/packages/{package}/ (role={role})")

    always = ["README.md", "hook.py", "agent.meta.json", "{role}.md", "{role}_EXAMPLE.md"]
    for name in always:
        _copy_template(name, dest_dir, package, role)

    if args.refine:
        path = dest_dir / f"{role}_refine_analysis.md"
        if path.exists():
            print(f"  skip (exists) {path.name}")
        else:
            path.write_text(
                f"# {role} REFINE 分析\n\nTODO: Phase 1 MCQ 分析 prompt。\n",
                encoding="utf-8",
            )
            print(f"  + {path.relative_to(PROJECT_ROOT)}")

    print("\n下一步:")
    print(f"  1. 编辑 hooks/packages/{package}/{{hook,{role}*.md}}")
    print(f"  2. 在当前 pipeline 档案 manifest 增加节点 \"agent\": \"{package}\"（WebUI 或 config/pipelines/<id>/manifest.json）")
    print("  3. uv run python scripts/sync_agent_meta.py  # 接入 manifest 后同步 nodes")
    print("  4. uv run pytest tests/engine/test_agent_package.py -q")
    return 0


if __name__ == "__main__":
    sys.exit(main())
