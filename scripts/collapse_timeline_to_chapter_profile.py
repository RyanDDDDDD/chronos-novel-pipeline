"""scripts/collapse_timeline_to_chapter_profile.py

One-off migration: for every character/chapter with more than one timeline snapshot (the old
per-stage authoring regime), keep only the stage=1 snapshot and drop the rest -- stage 1
represents this chapter's initial profile under the new per-chapter model, later per-stage deltas
are no longer meaningful. Re-derives each affected chapter's archive.json afterward.
See docs/superpowers/specs/2026-07-13-character-timeline-per-chapter-profile-design.md.

Usage: uv run python scripts/collapse_timeline_to_chapter_profile.py
"""
from __future__ import annotations

import argparse


def collapse_to_chapter_profile() -> dict[str, list[int]]:
    """Drop every non-stage-1 snapshot for chapters that have more than one. Returns
    {character_name: [affected chapter numbers]} -- only chapters that actually had >1 snapshot,
    a chapter that already has exactly one snapshot is left untouched and not counted."""
    from context import character_timeline
    from engine.setup_chat.tools import _persist_archive, _resolve_archive

    affected: dict[str, list[int]] = {}
    for name in character_timeline.list_timeline_names():
        tl = character_timeline.load_timeline(name)
        snapshots = tl.get("snapshots") or []
        by_chapter: dict[int, list[dict]] = {}
        for snap in snapshots:
            by_chapter.setdefault(int(snap.get("chapter", 0)), []).append(snap)

        changed_chapters: list[int] = []
        kept: list[dict] = []
        for chapter, snaps in by_chapter.items():
            if len(snaps) <= 1:
                kept.extend(snaps)
                continue
            stage_one = [s for s in snaps if int(s.get("stage", 0)) == 1]
            kept.extend(stage_one)
            changed_chapters.append(chapter)
        if not changed_chapters:
            continue

        tl["snapshots"] = kept
        character_timeline._save(tl)
        for chapter in sorted(changed_chapters):
            archive = _resolve_archive(name, chapter)
            _persist_archive(name, chapter, archive)
        affected[name] = sorted(changed_chapters)
    return affected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    affected = collapse_to_chapter_profile()
    if not affected:
        print("未发现需要收敛的多 stage 历史数据。")
        return
    print(f"已收敛 {len(affected)} 个角色的历史多 stage 数据：")
    for name, chapters in affected.items():
        print(f"  - {name}：第 {'、'.join(str(c) for c in chapters)} 章")


if __name__ == "__main__":
    main()
