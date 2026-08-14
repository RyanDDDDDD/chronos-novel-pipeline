import sqlite3


def _seed_old_schema(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE lore_characters (name TEXT PRIMARY KEY, data_json TEXT NOT NULL, seq INTEGER NOT NULL);
        CREATE TABLE plot_chapters (chapter INTEGER PRIMARY KEY, data_json TEXT NOT NULL, seq INTEGER NOT NULL);
        CREATE TABLE character_archives (name TEXT NOT NULL, chapter INTEGER NOT NULL, data_json TEXT NOT NULL, PRIMARY KEY (name, chapter));
        CREATE TABLE timeline_snapshots (name TEXT NOT NULL, chapter INTEGER NOT NULL, stage INTEGER NOT NULL, delta_json TEXT NOT NULL, PRIMARY KEY (name, chapter, stage));
        CREATE TABLE relationship_edges (id INTEGER PRIMARY KEY AUTOINCREMENT, from_name TEXT NOT NULL, to_name TEXT NOT NULL, nature TEXT NOT NULL DEFAULT '', relationship_anchor TEXT NOT NULL DEFAULT '', from_ref_terms_json TEXT NOT NULL DEFAULT '[]', to_ref_terms_json TEXT NOT NULL DEFAULT '[]', deleted INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE sandbox_events (id TEXT PRIMARY KEY, chapter INTEGER NOT NULL, turn_index INTEGER NOT NULL, entry_json TEXT NOT NULL);
        """
    )
    conn.execute("INSERT INTO lore_characters VALUES ('甲', '{}', 0)")
    conn.execute("INSERT INTO lore_characters VALUES ('乙', '{}', 1)")
    conn.execute("INSERT INTO plot_chapters VALUES (1, '{}', 0)")
    conn.execute("INSERT INTO character_archives VALUES ('甲', 1, '{}')")
    conn.execute("INSERT INTO character_archives VALUES ('幽灵', 1, '{}')")  # orphan: no lore row
    conn.execute("INSERT INTO timeline_snapshots VALUES ('甲', 1, 1, '{}')")
    conn.execute("INSERT INTO relationship_edges (from_name, to_name) VALUES ('甲', '乙')")
    conn.execute("INSERT INTO sandbox_events VALUES ('e1', 1, 0, '{}')")
    conn.execute("INSERT INTO sandbox_events VALUES ('e2', 0, 0, '{}')")  # orphan: chapter 0, no plot row
    conn.commit()
    conn.close()


def test_migrate_adds_surrogate_id_and_drops_orphans(tmp_path):
    db_path = str(tmp_path / "chronos.sqlite3")
    _seed_old_schema(db_path)

    from scripts.migrate_character_fk import _migrate_one
    counts = _migrate_one(db_path, dry_run=False)

    assert counts["lore_characters"] == 2
    assert counts["character_archives"] == 1
    assert counts["character_archives_orphans_dropped"] == 1
    assert counts["sandbox_events"] == 1
    assert counts["sandbox_events_orphans_dropped"] == 1

    conn = sqlite3.connect(db_path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(lore_characters)").fetchall()]
    assert "id" in cols
    row = conn.execute(
        "SELECT ca.chapter FROM character_archives ca"
        " JOIN lore_characters lc ON lc.id = ca.character_id WHERE lc.name = '甲'",
    ).fetchone()
    assert row == (1,)


def test_migrate_is_idempotent(tmp_path):
    db_path = str(tmp_path / "chronos.sqlite3")
    _seed_old_schema(db_path)
    from scripts.migrate_character_fk import _migrate_one

    _migrate_one(db_path, dry_run=False)
    second = _migrate_one(db_path, dry_run=False)
    assert second == {"skipped_already_migrated": 1}


def test_migrate_dry_run_does_not_persist(tmp_path):
    db_path = str(tmp_path / "chronos.sqlite3")
    _seed_old_schema(db_path)
    from scripts.migrate_character_fk import _migrate_one

    _migrate_one(db_path, dry_run=True)
    conn = sqlite3.connect(db_path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(lore_characters)").fetchall()]
    assert "id" not in cols
