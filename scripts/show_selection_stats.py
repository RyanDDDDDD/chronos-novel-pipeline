"""显示 LLM 选项偏好统计报告。

用法：
    uv run python scripts/show_selection_stats.py
    uv run python scripts/show_selection_stats.py --reset   # 清空统计
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
STATS_PATH = ROOT / "var" / "selection_stats.json"
CATEGORIES = ("体位", "前戏", "插件")


def _bar(count: int, total: int, width: int = 24) -> str:
    filled = round(count / total * width) if total else 0
    return "█" * filled + "░" * (width - filled)


def _flatten_bucket(bucket: dict) -> list[tuple[str, int]]:
    """
合并嵌套子分类 {子类: {名: 次数}} 或旧版扁平 {名: 次数}。"""

    merged: dict[str, int] = {}
    for key, val in bucket.items():
        if isinstance(val, int):
            merged[key] = merged.get(key, 0) + val
        elif isinstance(val, dict):
            for name, count in val.items():
                if isinstance(count, int):
                    merged[name] = merged.get(name, 0) + count
    return sorted(merged.items(), key=lambda x: x[1], reverse=True)


def show() -> None:
    if not STATS_PATH.exists():
        print("暂无统计数据，运行流水线后再试。")
        return

    with open(STATS_PATH, encoding="utf-8") as f:
        data = json.load(f)

    any_data = False
    for category in CATEGORIES:
        bucket = data.get(category, {})
        if not bucket:
            continue
        ranked = _flatten_bucket(bucket)
        if not ranked:
            continue
        any_data = True
        total = sum(c for _, c in ranked)
        print(f"\n{'═' * 52}")
        print(f"  {category}  （共选用 {total} 次 / {len(ranked)} 种选项）")
        print(f"{'═' * 52}")
        for name, count in ranked:
            pct = count / total * 100
            print(f"  {name:<18} {_bar(count, total)}  {count:>3}次  {pct:>5.1f}%")

    if not any_data:
        print("统计文件存在但无数据。")
    print()


def reset() -> None:
    if STATS_PATH.exists():
        STATS_PATH.unlink()
        print(f"已清空：{STATS_PATH}")
    else:
        print("统计文件不存在，无需清空。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM 选项偏好统计报告")
    parser.add_argument("--reset", action="store_true", help="清空统计数据")
    args = parser.parse_args()

    if args.reset:
        reset()
    else:
        show()
