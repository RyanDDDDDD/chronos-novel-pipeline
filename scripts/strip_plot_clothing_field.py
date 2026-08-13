"""scripts/strip_plot_clothing_field.py

One-off migration: strip the now-retired per-stage `clothing` key from every novel's
plot_library.json. The field has been dropped from the write schema (PlotStageArgs/
StagePatchFields), the merge allowlist, and the setup-chat timeline seed rendering --
see docs/superpowers/specs/2026-07-19-retire-plot-clothing-field-design.md. This script
cleans up the stale key left behind in already-generated plot data.

Usage: uv run python scripts/strip_plot_clothing_field.py
"""
from __future__ import annotations

import argparse
import json
import os


def _strip_file(path: str) -> int:
    """Strip `clothing` from every stage in one plot_library.json. Returns the number of
    stages that had the key removed (0 if the file is missing, empty, or already clean --
    in which case nothing is written back)."""
    if not os.path.isfile(path):
        return 0
    with open(path, encoding="utf-8") as f:
        chapters = json.load(f)
    if not isinstance(chapters, list):
        return 0

    affected = 0
    for ch in chapters:
        if not isinstance(ch, dict):
            continue
        for stage in ch.get("stages", []):
            if isinstance(stage, dict) and "clothing" in stage:
                del stage["clothing"]
                affected += 1

    if affected:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(chapters, f, ensure_ascii=False, indent=2)
    return affected


def strip_plot_clothing_field() -> dict[str, int]:
    """Strip `clothing` from every novel's plot_library.json (all novels from
    api.services.novels.list_novels(), plus the `default` template novels are copied from).
    Deliberately skips data/novels/.trash/ -- frozen recycle bin, stays byte-exact, same
    convention as scripts/rename_lore_sliders_init.py. Returns {novel_id: affected_stage_count},
    only including novels where something actually changed."""
    from api.services.novels import list_novels
    from utils.paths import novels_dir

    affected: dict[str, int] = {}
    ids = [n["id"] for n in list_novels()] + ["default"]
    for nid in ids:
        path = os.path.join(novels_dir(), nid, "plot", "plot_library.json")
        count = _strip_file(path)
        if count:
            affected[nid] = count
    return affected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    affected = strip_plot_clothing_field()
    if not affected:
        print("未发现需要清理的 clothing 字段。")
        return
    print(f"已清理 {len(affected)} 本小说的 plot_library clothing 字段：")
    for nid, count in affected.items():
        print(f"  - {nid}：{count} 处 stage")


if __name__ == "__main__":
    main()
