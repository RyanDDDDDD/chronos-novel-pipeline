"""One-off migration: rebuild lore_characters/character_archives/timeline_snapshots/
relationship_edges to use a surrogate lore_characters.id instead of the bare name string,
and add the chapter FK constraint to character_archives/timeline_snapshots. SQLite can't
ALTER a column into a new PRIMARY KEY or add a FOREIGN KEY to an existing table, so each
table is rebuilt: rename old -> create new (matches the updated repositories.sqlite_
store._DDL shape) -> copy via JOIN (drops orphan rows that don't resolve) -> drop old.

sandbox_events is NOT touched by this migration: chapter=0 there is the reserved, permanent
"free mode" sentinel (see engine/story_sandbox/prompt.py's module docstring), not an
orphan -- a chapter FK on this table would require either destroying live free-mode data
during migration or perpetually faking a chapter-0 plot_chapters row at write time, and the
latter leaks a phantom chapter into plot_chapters that generate_one_chapter's
"n = len(chapters)" append-bounds check would miscount. No FK on this table's chapter column.

Idempotent: if lore_characters already has an `id` column, the novel is skipped.

Usage:
    uv run python scripts/migrate_character_fk.py [--novel <novel_id>] [--dry-run]
"""
from __future__ import annotations

import argparse
import sqlite3


def _novel_ids(explicit: str | None) -> list[str]:
    if explicit:
        return [explicit]
    import os

    from utils.paths import novels_dir

    root = novels_dir()
    if not os.path.isdir(root):
        return []
    return sorted(
        d for d in os.listdir(root)
        if os.path.isdir(os.path.join(root, d)) and d not in (".trash",)
    )


def _already_migrated(conn: sqlite3.Connection) -> bool:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(lore_characters)").fetchall()]
    return "id" in cols


def _migrate_one(db_path: str, *, dry_run: bool) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    counts: dict[str, int] = {}
    try:
        if _already_migrated(conn):
            return {"skipped_already_migrated": 1}

        conn.execute("PRAGMA foreign_keys = OFF")  # rebuilding tables mid-transaction
        conn.execute("BEGIN")

        # 1. lore_characters: add surrogate id, keep insertion (seq) order deterministic
        conn.execute("ALTER TABLE lore_characters RENAME TO lore_characters_old")
        conn.execute(
            "CREATE TABLE lore_characters (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " name TEXT NOT NULL UNIQUE, data_json TEXT NOT NULL, seq INTEGER NOT NULL)",
        )
        conn.execute(
            "INSERT INTO lore_characters (name, data_json, seq)"
            " SELECT name, data_json, seq FROM lore_characters_old"
            " WHERE name IS NOT NULL AND name != '' ORDER BY seq",
        )
        skipped_unnamed = conn.execute(
            "SELECT COUNT(*) FROM lore_characters_old WHERE name IS NULL OR name = ''",
        ).fetchone()[0]
        counts["lore_characters"] = conn.execute(
            "SELECT COUNT(*) FROM lore_characters",
        ).fetchone()[0]
        counts["lore_characters_skipped_unnamed"] = skipped_unnamed
        conn.execute("DROP TABLE lore_characters_old")

        # 2. character_archives: name -> character_id, drop orphans (no matching lore row,
        #    or chapter that no longer exists in plot_chapters)
        conn.execute("ALTER TABLE character_archives RENAME TO character_archives_old")
        conn.execute(
            "CREATE TABLE character_archives (character_id INTEGER NOT NULL,"
            " chapter INTEGER NOT NULL, data_json TEXT NOT NULL,"
            " PRIMARY KEY (character_id, chapter),"
            " FOREIGN KEY (character_id) REFERENCES lore_characters(id),"
            " FOREIGN KEY (chapter) REFERENCES plot_chapters(chapter))",
        )
        conn.execute(
            "INSERT INTO character_archives (character_id, chapter, data_json)"
            " SELECT lc.id, o.chapter, o.data_json FROM character_archives_old o"
            " JOIN lore_characters lc ON lc.name = o.name"
            " JOIN plot_chapters pc ON pc.chapter = o.chapter",
        )
        counts["character_archives"] = conn.execute(
            "SELECT COUNT(*) FROM character_archives",
        ).fetchone()[0]
        counts["character_archives_orphans_dropped"] = conn.execute(
            "SELECT COUNT(*) FROM character_archives_old",
        ).fetchone()[0] - counts["character_archives"]
        conn.execute("DROP TABLE character_archives_old")

        # 3. timeline_snapshots: same shape, plus stage in the PK
        conn.execute("ALTER TABLE timeline_snapshots RENAME TO timeline_snapshots_old")
        conn.execute(
            "CREATE TABLE timeline_snapshots (character_id INTEGER NOT NULL,"
            " chapter INTEGER NOT NULL, stage INTEGER NOT NULL, delta_json TEXT NOT NULL,"
            " PRIMARY KEY (character_id, chapter, stage),"
            " FOREIGN KEY (character_id) REFERENCES lore_characters(id),"
            " FOREIGN KEY (chapter) REFERENCES plot_chapters(chapter))",
        )
        conn.execute(
            "INSERT INTO timeline_snapshots (character_id, chapter, stage, delta_json)"
            " SELECT lc.id, o.chapter, o.stage, o.delta_json FROM timeline_snapshots_old o"
            " JOIN lore_characters lc ON lc.name = o.name"
            " JOIN plot_chapters pc ON pc.chapter = o.chapter",
        )
        counts["timeline_snapshots"] = conn.execute(
            "SELECT COUNT(*) FROM timeline_snapshots",
        ).fetchone()[0]
        counts["timeline_snapshots_orphans_dropped"] = conn.execute(
            "SELECT COUNT(*) FROM timeline_snapshots_old",
        ).fetchone()[0] - counts["timeline_snapshots"]
        conn.execute("DROP TABLE timeline_snapshots_old")

        # 4. relationship_edges: from_name/to_name -> from/to_character_id
        conn.execute("ALTER TABLE relationship_edges RENAME TO relationship_edges_old")
        conn.execute(
            "CREATE TABLE relationship_edges (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " from_character_id INTEGER NOT NULL, to_character_id INTEGER NOT NULL,"
            " nature TEXT NOT NULL DEFAULT '', relationship_anchor TEXT NOT NULL DEFAULT '',"
            " from_ref_terms_json TEXT NOT NULL DEFAULT '[]',"
            " to_ref_terms_json TEXT NOT NULL DEFAULT '[]', deleted INTEGER NOT NULL DEFAULT 0,"
            " FOREIGN KEY (from_character_id) REFERENCES lore_characters(id),"
            " FOREIGN KEY (to_character_id) REFERENCES lore_characters(id))",
        )
        conn.execute(
            "INSERT INTO relationship_edges (from_character_id, to_character_id, nature,"
            " relationship_anchor, from_ref_terms_json, to_ref_terms_json, deleted)"
            " SELECT lc_from.id, lc_to.id, o.nature, o.relationship_anchor,"
            " o.from_ref_terms_json, o.to_ref_terms_json, o.deleted"
            " FROM relationship_edges_old o"
            " JOIN lore_characters lc_from ON lc_from.name = o.from_name"
            " JOIN lore_characters lc_to ON lc_to.name = o.to_name"
            " ORDER BY o.id",
        )
        counts["relationship_edges"] = conn.execute(
            "SELECT COUNT(*) FROM relationship_edges",
        ).fetchone()[0]
        counts["relationship_edges_orphans_dropped"] = conn.execute(
            "SELECT COUNT(*) FROM relationship_edges_old",
        ).fetchone()[0] - counts["relationship_edges"]
        conn.execute("DROP TABLE relationship_edges_old")

        if dry_run:
            conn.execute("ROLLBACK")
            return counts
        conn.commit()

        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"{db_path}: foreign_key_check found {len(violations)} violations")
        return counts
    finally:
        conn.close()


def migrate(novel_id: str | None = None, *, dry_run: bool = False) -> dict[str, dict[str, int]]:
    from utils.paths import novel_db_path

    results: dict[str, dict[str, int]] = {}
    for nid in _novel_ids(novel_id):
        db_path = novel_db_path(nid)
        import os
        if not os.path.isfile(db_path):
            continue
        results[nid] = _migrate_one(db_path, dry_run=dry_run)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--novel", help="Novel id to migrate (default: all novels)")
    parser.add_argument("--dry-run", action="store_true", help="Roll back after counting; do not persist")
    args = parser.parse_args()

    results = migrate(args.novel, dry_run=args.dry_run)
    if not results:
        print("没有需要迁移的小说。")
        return
    label = "（dry-run，未写入）" if args.dry_run else ""
    for nid, counts in results.items():
        parts = ", ".join(f"{k} {v}" for k, v in counts.items())
        print(f"{nid}{label}: {parts}")


if __name__ == "__main__":
    main()
