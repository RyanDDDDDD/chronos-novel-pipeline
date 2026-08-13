"""scripts/migrate_plot_drop_characters.py

One-off migration: physically deletes the retired `characters` key from every stage in every
novel's plot_library.json (see
docs/superpowers/specs/2026-07-31-plot-characters-field-elimination-design.md). The field is no
longer read or written by any code path (Phase 1/2 of that design switched every consumer to
entity_index.scan_characters(description) at read time) -- this just cleans up the now-inert
historical data. Skips novels where no stage has the key.

Usage: uv run python scripts/migrate_plot_drop_characters.py
"""
from __future__ import annotations

import argparse


def _migrate_one(nid: str) -> int:
    """Drops `characters` from every stage of one novel's plot_library if present. Returns the
    number of stages changed."""
    import repositories
    from utils.paths import use_novel

    with use_novel(nid):
        repositories.reset_repositories()
        chapters = repositories.get_plot_repo().list_raw()
        changed = 0
        for ch in chapters:
            if not isinstance(ch, dict):
                continue
            for stage in ch.get("stages") or []:
                if isinstance(stage, dict) and "characters" in stage:
                    del stage["characters"]
                    changed += 1
        if changed:
            repositories.get_plot_repo().save_all(chapters)
        return changed


def migrate_all() -> dict[str, int]:
    from api.services.novels import list_novels

    migrated: dict[str, int] = {}
    for novel in list_novels():
        nid = novel["id"]
        count = _migrate_one(nid)
        if count:
            migrated[nid] = count
    return migrated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    result = migrate_all()
    if not result:
        print("没有找到含 characters 字段的 plot_library，无需迁移。")
        return
    print(f"已迁移 {len(result)} 部小说：")
    for nid, count in result.items():
        print(f"  - {nid}：删除 {count} 处 stage 的 characters 字段")


if __name__ == "__main__":
    main()
