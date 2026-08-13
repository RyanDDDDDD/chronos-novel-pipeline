#!/usr/bin/env python3
"""
Agent Asset Auditor

扫描所有 hooks/packages/*/assets/*.json，如果存在对应的 .schema.json 则用 jsonschema 验证。
同时运行 hooks/packages/*/validator.py（如存在）。

用法:
    python scripts/audit_agent_assets.py [--agents-dir PATH] [--fail-fast]

退出码:
    0 — 全部通过（或无可审计资产）
    1 — 存在验证失败
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import jsonschema
except ImportError:
    print("[ERROR] jsonschema not installed. Run: uv add jsonschema", file=sys.stderr)
    sys.exit(2)


@dataclass
class AuditResult:
    asset_path: Path
    status: str   # "pass" | "fail" | "skip"
    message: str = ""

    def __str__(self) -> str:
        return f"[{self.status.upper():4s}] {self.asset_path}  {self.message}"


def _validate_asset(asset_path: Path) -> AuditResult:
    """

    校验单个 JSON 资产文件。

    - 若无对应 .schema.json → SKIP
    - 若 JSON 解析失败      → FAIL
    - 若 schema 不符合      → FAIL
    - 否则                  → PASS
    """
    schema_path = asset_path.with_suffix("").with_suffix(".schema.json")
    if not schema_path.exists():
        return AuditResult(asset_path, "skip")

    try:
        with open(asset_path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return AuditResult(asset_path, "fail", f"JSON parse error: {e}")

    try:
        with open(schema_path, encoding="utf-8") as f:
            schema = json.load(f)
    except Exception as e:
        return AuditResult(asset_path, "fail", f"Schema parse error: {e}")

    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as e:
        return AuditResult(asset_path, "fail", e.message)

    return AuditResult(asset_path, "pass")


def _run_validator_script(validator_path: Path) -> list[AuditResult]:
    """
运行 hooks/packages/*/validator.py，调用其 validate() 函数。"""

    results: list[AuditResult] = []
    spec = importlib.util.spec_from_file_location("_validator", str(validator_path))
    if spec is None or spec.loader is None:
        return [AuditResult(validator_path, "fail", "Cannot load validator module")]
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except Exception as e:
        return [AuditResult(validator_path, "fail", f"Import error: {e}")]
    if not hasattr(mod, "validate"):
        return [AuditResult(validator_path, "skip", "No validate() function")]
    try:
        vr = mod.validate(validator_path.parent)
        if hasattr(vr, "ok") and not vr.ok:
            results.append(AuditResult(validator_path, "fail", str(getattr(vr, "errors", ""))))
        else:
            results.append(AuditResult(validator_path, "pass"))
    except Exception as e:
        results.append(AuditResult(validator_path, "fail", str(e)))
    return results


def _run_audit(agents_dir: Path, fail_fast: bool = False) -> list[AuditResult]:
    """审计 agents_dir 下所有 assets/ 目录和 validator.py 文件。"""

    results: list[AuditResult] = []

    for agent_dir in sorted(agents_dir.iterdir()):
        if not agent_dir.is_dir():
            continue

        assets_dir = agent_dir / "assets"
        if assets_dir.exists():
            for json_file in sorted(assets_dir.glob("*.json")):
                if json_file.name.endswith(".schema.json"):
                    continue
                r = _validate_asset(json_file)
                results.append(r)
                if fail_fast and r.status == "fail":
                    return results

        validator_py = agent_dir / "validator.py"
        if validator_py.exists():
            vrs = _run_validator_script(validator_py)
            results.extend(vrs)
            if fail_fast and any(r.status == "fail" for r in vrs):
                return results

    return results


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root / "src" / "backend"))
    from utils.paths import AGENTS_DIR  # noqa: E402

    parser = argparse.ArgumentParser(description="Audit agent asset files against JSON Schemas")
    parser.add_argument(
        "--agents-dir",
        default=AGENTS_DIR,
        help="Path to hooks/packages/ directory (default: utils.paths.AGENTS_DIR)",
    )
    parser.add_argument("--fail-fast", action="store_true", help="Stop on first failure")
    parser.add_argument("--quiet", action="store_true", help="Only show failures and summary")
    args = parser.parse_args()

    agents_dir = Path(args.agents_dir)
    if not agents_dir.exists():
        print(f"[ERROR] agents dir not found: {agents_dir}", file=sys.stderr)
        sys.exit(2)

    results = _run_audit(agents_dir, fail_fast=args.fail_fast)

    passes   = [r for r in results if r.status == "pass"]
    failures = [r for r in results if r.status == "fail"]
    skips    = [r for r in results if r.status == "skip"]

    for r in results:
        if r.status == "fail" or not args.quiet:
            print(r)

    print(f"\n{'─'*60}")
    print(f"  通过: {len(passes)}  失败: {len(failures)}  跳过: {len(skips)}")

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
