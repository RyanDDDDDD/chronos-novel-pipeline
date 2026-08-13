"""One-off migration: collapse every character/chapter's timeline to a single stage=1 snapshot
(dropping legacy per-stage deltas left over from the retired classic beat-by-beat engine), then
re-derive and re-persist every existing archive.json file in the new flat shape -- no
"stages": {sid: {...}} wrapper, profile fields (sliders/gender/physique/personality/...) sit
directly on the top level alongside the base identity fields. See _resolve_archive in
engine/setup_chat/tools.py for the shape this produces.

Usage: uv run python scripts/flatten_character_archives.py
"""
from __future__ import annotations

import argparse
import os


def flatten_character_archives() -> dict[str, list[int]]:
    """Returns {character_name: [affected chapter numbers]} -- a chapter counts as affected if
    either (a) more than one timeline snapshot existed and got collapsed down to stage=1, or
    (b) an existing archive.json file got re-persisted in the new flat shape. A chapter with no
    on-disk archive.json is left untouched (this migrates existing files, it does not backfill
    missing ones)."""
    from context import character_timeline
    from engine.setup_chat.tools import _persist_archive, _resolve_archive
    from utils.paths import get_character_archive_dir

    affected: dict[str, list[int]] = {}
    for name in character_timeline.list_timeline_names():
        tl = character_timeline.load_timeline(name)
        snapshots = tl.get("snapshots") or []
        by_chapter: dict[int, list[dict]] = {}
        for snap in snapshots:
            by_chapter.setdefault(int(snap.get("chapter", 0)), []).append(snap)

        collapsed_chapters: set[int] = set()
        kept: list[dict] = []
        for chapter, snaps in by_chapter.items():
            if len(snaps) <= 1:
                kept.extend(snaps)
                continue
            stage_one = [s for s in snaps if int(s.get("stage", 0)) == 1]
            kept.extend(stage_one)
            collapsed_chapters.add(chapter)
        if collapsed_chapters:
            tl["snapshots"] = kept
            character_timeline._save(tl)

        touched_chapters: set[int] = set(collapsed_chapters)
        for chapter in sorted(by_chapter):
            path = os.path.join(
                get_character_archive_dir(chapter), f"{name}_ch{chapter:02d}_archive.json",
            )
            if not os.path.isfile(path):
                continue
            archive = _resolve_archive(name, chapter)
            _persist_archive(name, chapter, archive)
            touched_chapters.add(chapter)

        if touched_chapters:
            affected[name] = sorted(touched_chapters)
    return affected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    affected = flatten_character_archives()
    if not affected:
        print("未发现需要展平的角色档案。")
        return
    print(f"已展平 {len(affected)} 个角色的档案：")
    for name, chapters in affected.items():
        print(f"  - {name}：第 {'、'.join(str(c) for c in chapters)} 章")


if __name__ == "__main__":
    main()
