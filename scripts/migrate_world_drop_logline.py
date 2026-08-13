"""scripts/migrate_world_drop_logline.py

One-off migration: drops the legacy world_bible `logline` scalar field now that it has been
merged into `background` (see
docs/superpowers/specs/2026-07-31-world-logline-background-merge-design.md). Historical logline
content is discarded per product decision; `background`'s existing value is left untouched.
Skips novels that no longer have a `logline` key.

Usage: uv run python scripts/migrate_world_drop_logline.py
"""
from __future__ import annotations

import argparse


def _migrate_one(nid: str) -> bool:
    """Drops `logline` from one novel's world_bible if present. Returns True if it changed anything."""
    import repositories
    from utils.paths import use_novel

    with use_novel(nid):
        repositories.reset_repositories()
        bible = repositories.get_world_repo().get()
        if not isinstance(bible, dict) or "logline" not in bible:
            return False
        bible = dict(bible)
        del bible["logline"]
        repositories.get_world_repo().save(bible)
        return True


def migrate_all() -> dict[str, list[str]]:
    from api.services.novels import list_novels

    migrated: list[str] = []
    for novel in list_novels():
        nid = novel["id"]
        if _migrate_one(nid):
            migrated.append(nid)
    return {"migrated": migrated}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    result = migrate_all()
    migrated = result["migrated"]
    if not migrated:
        print("没有找到含 logline 字段的小说，无需迁移。")
        return
    print(f"已迁移 {len(migrated)} 部小说，丢弃了 logline 字段：{', '.join(migrated)}")


if __name__ == "__main__":
    main()
