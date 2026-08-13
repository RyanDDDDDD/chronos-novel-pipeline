"""重排序号脚本。

用法：
    uv run python scripts/reindex.py           # plot + plugin 都重排
    uv run python scripts/reindex.py --plot    # 只重排章节
    uv run python scripts/reindex.py --plugin  # 只重排插件
"""

import argparse
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PLOT_PATH = os.path.join(ROOT, "data", "plot", "plot_library.json")
PLUGIN_PATH = os.path.join(ROOT, "hooks", "packages", "plugin_injection", "assets", "plugin_library.json")


# ── 章节重排 ─────────────────────────────────────────────────────────────────


def reindex_plot():
    with open(PLOT_PATH, encoding="utf-8") as f:
        data = json.load(f)

    changed = []
    for new_ch, chapter in enumerate(data, start=1):
        old_ch = chapter["chapter"]

        # 更新 chapter 字段
        chapter["chapter"] = new_ch

        # 更新 title 中的"第N章"
        old_title = chapter.get("title", "")
        new_title = re.sub(r"第\d+章", f"第{new_ch}章", old_title, count=1)
        chapter["title"] = new_title

        # 重排 stage_num
        for new_sn, stage in enumerate(chapter.get("stages", []), start=1):
            stage["stage_num"] = new_sn

        if old_ch != new_ch:
            changed.append(f"  第{old_ch}章 → 第{new_ch}章")

    with open(PLOT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    if changed:
        print(f"✓ plot_library.json 重排了 {len(changed)} 章：")
        for line in changed:
            print(line)
    else:
        print("✓ plot_library.json 序号已是连续，无需变动")

    print(f"  共 {len(data)} 章")


# ── 插件重排 ─────────────────────────────────────────────────────────────────


def reindex_plugin():
    with open(PLUGIN_PATH, encoding="utf-8") as f:
        data = json.load(f)

    changed = []
    counter = 1
    for _category, items in data.items():
        for item in items:
            old_id = item["id"]
            new_id = f"UPP-{counter:02d}"
            if old_id != new_id:
                changed.append(f"  {old_id} → {new_id}  ({item.get('name', '')})")
            item["id"] = new_id
            counter += 1

    with open(PLUGIN_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    if changed:
        print(f"✓ plugin_library.json 重排了 {len(changed)} 个插件：")
        for line in changed:
            print(line)
    else:
        print("✓ plugin_library.json 序号已是连续，无需变动")

    total = sum(len(v) for v in data.values())
    print(f"  共 {total} 个插件，分 {len(data)} 类")


# ── 主入口 ────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="重排 plot/plugin 库序号")
    parser.add_argument("--plot",   action="store_true", help="只重排章节")
    parser.add_argument("--plugin", action="store_true", help="只重排插件")
    args = parser.parse_args()

    run_all = not args.plot and not args.plugin
    if args.plot or run_all:
        reindex_plot()
    if args.plugin or run_all:
        reindex_plugin()


if __name__ == "__main__":
    main()
