"""scripts/rename_lore_sliders_init.py

One-off migration for the retired `sliders_init` key, across every novel under data/novels/
(via api.services.novels.list_novels(), not just the active one):

1. every character_lore_library.json under the novel dir (live + setup_chat snapshot copy) --
   rename each character's `sliders_init` to `sliders` (the code now reads `char.get("sliders")`
   for cold-start/rolling resolution).
2. every resolved `*_archive.json` under the novel dir (chapters/ + setup_chat snapshot copies) --
   pop the stale top-level `sliders_init` lore copy and fold it into `sliders` as the baseline:
   axes the resolved `sliders` already has keep their resolved value, missing axes fall back to
   the baseline. This mirrors resolve_from's new lore-seeded deep_ignore_none fold, and stops the
   stale key leaking into the archive page now that archive_view no longer filters it.

Deliberately untouched: data/novels/.trash/ (recycle bin) and any novels_backup_* sibling dirs
(frozen backups stay byte-exact).
See docs/superpowers/specs/2026-07-14-unify-sliders-init-into-sliders-design.md.

Usage: uv run python scripts/rename_lore_sliders_init.py
"""
from __future__ import annotations

import argparse
import json
import os


def _rename_one_lore_file(path: str) -> list[str]:
    """Rename sliders_init -> sliders in place for every character in this lore file that still
    has it. Returns the list of renamed character names (empty if nothing needed renaming or the
    file is missing)."""
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        roster = json.load(f)
    if not isinstance(roster, list):
        return []

    renamed: list[str] = []
    for char in roster:
        if not isinstance(char, dict) or "sliders_init" not in char:
            continue
        char["sliders"] = char.pop("sliders_init")
        renamed.append(str(char.get("name") or char.get("given_name") or "?"))

    if renamed:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(roster, f, ensure_ascii=False, indent=2)
    return renamed


def _fold_baseline_into_archive(archive: dict) -> bool:
    """Pop the stale top-level sliders_init copy and fold it into sliders as the baseline
    (resolved axes win, untouched axes fall back). Returns True if the dict changed."""
    if "sliders_init" not in archive:
        return False
    baseline = archive.pop("sliders_init")
    if isinstance(baseline, dict):
        cur = archive.get("sliders")
        if not isinstance(cur, dict):
            archive["sliders"] = baseline
        else:
            for axis, val in baseline.items():
                cur.setdefault(axis, val)
    return True


def _migrate_files_in(novel_dir: str) -> tuple[list[str], list[str]]:
    """Walk the novel dir migrating every *_archive.json (fold baseline into sliders) and every
    character_lore_library.json copy (rename; covers the setup_chat snapshot copy alongside the
    live one). Returns (renamed lore character names, changed archive relpaths)."""
    lore_names: list[str] = []
    changed: list[str] = []
    for dirpath, _, files in os.walk(novel_dir):
        for fn in files:
            path = os.path.join(dirpath, fn)
            if fn == "character_lore_library.json":
                lore_names.extend(_rename_one_lore_file(path))
                continue
            if not fn.endswith("_archive.json"):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    archive = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(archive, dict) or not _fold_baseline_into_archive(archive):
                continue
            with open(path, "w", encoding="utf-8") as f:
                json.dump(archive, f, ensure_ascii=False, indent=2)
            changed.append(os.path.relpath(path, novel_dir))
    return lore_names, changed


def rename_sliders_init_to_sliders() -> dict[str, dict[str, list[str]]]:
    """Run both migration passes across every novel. Returns
    {novel_id: {"lore": [renamed character names], "archives": [changed archive paths]}} --
    only novels where at least one file actually changed are included."""
    from api.services.novels import list_novels
    from utils.paths import active_novel_dir, use_novel

    affected: dict[str, dict[str, list[str]]] = {}
    for novel in list_novels():
        nid = novel["id"]
        with use_novel(nid):
            renamed, archives = _migrate_files_in(active_novel_dir())
        if renamed or archives:
            affected[nid] = {"lore": renamed, "archives": archives}
    return affected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    affected = rename_sliders_init_to_sliders()
    if not affected:
        print("未发现需要迁移的 sliders_init 字段。")
        return
    for nid, changes in affected.items():
        print(f"- {nid}：")
        if changes["lore"]:
            print(f"    lore 改名 {len(changes['lore'])} 个角色：{'、'.join(changes['lore'])}")
        if changes["archives"]:
            print(f"    档案折叠 {len(changes['archives'])} 个文件：")
            for p in changes["archives"]:
                print(f"      · {p}")


if __name__ == "__main__":
    main()
