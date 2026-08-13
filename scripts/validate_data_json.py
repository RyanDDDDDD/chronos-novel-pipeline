"""验证 data/ 目录下所有 JSON 文件的格式合法性。

用法：
    uv run python scripts/validate_data_json.py
        验证所有 data/ 下的 JSON，打印结果；有错误时以非零退出码退出

    uv run python scripts/validate_data_json.py --quiet
        仅打印错误，忽略 OK 文件

可供引擎内部直接 import 调用：
    from scripts.validate_data_json import validate_data_json
    errors = validate_data_json(data_dir)   # 返回 [(path, error_msg), ...]
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")


def validate_data_json(data_dir: str) -> list[tuple[str, str]]:
    """
遍历 data_dir 下所有 .json 文件并尝试解析。

    Returns:
        解析失败的文件列表：[(相对路径, 错误描述), ...]
        空列表表示全部合法。
    """

    errors: list[tuple[str, str]] = []
    for dirpath, _, filenames in os.walk(data_dir):
        for fname in sorted(filenames):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    json.load(f)
            except Exception as exc:
                rel = os.path.relpath(fpath, data_dir)
                errors.append((rel, str(exc)))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 data/ 目录下所有 JSON 文件")
    parser.add_argument(
        "--quiet", "-q", action="store_true", help="仅打印错误，忽略 OK 文件"
    )
    parser.add_argument(
        "--data-dir", default=DATA_DIR, help=f"待验证目录（默认：{DATA_DIR}）"
    )
    args = parser.parse_args()

    if not os.path.isdir(args.data_dir):
        print(f"[ERROR] 目录不存在：{args.data_dir}", file=sys.stderr)
        return 2

    errors = validate_data_json(args.data_dir)
    ok_count = 0
    err_count = len(errors)

    # 统计 OK 文件数（只计数，不再次遍历）
    for _dirpath, _, filenames in os.walk(args.data_dir):
        ok_count += sum(1 for f in filenames if f.endswith(".json"))
    ok_count -= err_count

    if not args.quiet:
        for dirpath, _, filenames in os.walk(args.data_dir):
            for fname in sorted(filenames):
                if fname.endswith(".json"):
                    rel = os.path.relpath(os.path.join(dirpath, fname), args.data_dir)
                    is_err = any(r == rel for r, _ in errors)
                    if not is_err:
                        print(f"  OK   {rel}")

    for rel, msg in errors:
        print(f"  ERR  {rel}\n       {msg}", file=sys.stderr)

    print(f"\n共 {ok_count + err_count} 个 JSON 文件：{ok_count} 合法，{err_count} 损坏")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
