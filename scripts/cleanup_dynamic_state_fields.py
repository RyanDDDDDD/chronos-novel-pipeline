"""scripts/cleanup_dynamic_state_fields.py

One-off migration: strip the now-retired `state`/`clothing` per-stage delta fields from every
character's timeline snapshots (source of truth) and re-derive each affected chapter's
archive.json, so future `write_character_archive` calls don't resurrect them via resolve_from.
See docs/superpowers/specs/2026-07-13-dialogue-mode-state-runtime-derivation-design.md.

Usage: uv run python scripts/cleanup_dynamic_state_fields.py
"""
from __future__ import annotations

import argparse


def _stripped_keys(delta: dict) -> tuple[dict, bool]:
    changed = "state" in delta or "clothing" in delta
    return {k: v for k, v in delta.items() if k not in ("state", "clothing")}, changed


def strip_dynamic_state_fields() -> dict[str, list[int]]:
    """Strip state/clothing from every character's timeline snapshots + re-derive their
    archive.json. Returns {character_name: [affected chapter numbers]}."""
    from context import character_timeline
    from engine.setup_chat.tools import _persist_archive, _resolve_archive

    affected: dict[str, list[int]] = {}
    for name in character_timeline.list_timeline_names():
        tl = character_timeline.load_timeline(name)
        snapshots = tl.get("snapshots") or []
        changed_chapters: set[int] = set()
        for snap in snapshots:
            delta = snap.get("delta") or {}
            stripped, changed = _stripped_keys(delta)
            if changed:
                snap["delta"] = stripped
                changed_chapters.add(int(snap.get("chapter", 0)))
        if not changed_chapters:
            continue
        character_timeline._save(tl)
        for chapter in sorted(changed_chapters):
            archive = _resolve_archive(name, chapter)
            _persist_archive(name, chapter, archive)
        affected[name] = sorted(changed_chapters)
    return affected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    affected = strip_dynamic_state_fields()
    if not affected:
        print("未发现需要清理的 state/clothing 历史数据。")
        return
    print(f"已清理 {len(affected)} 个角色的历史 state/clothing 数据：")
    for name, chapters in affected.items():
        print(f"  - {name}：第 {'、'.join(str(c) for c in chapters)} 章")


if __name__ == "__main__":
    main()
