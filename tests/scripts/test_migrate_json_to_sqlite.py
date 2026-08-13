"""scripts/migrate_json_to_sqlite.py: JSON → SQLite migration for lore/plot/archive + registry."""
from __future__ import annotations

import json
import os

from engine.setup.cast.relationship_graph import load_graph
from scripts.migrate_json_to_sqlite import migrate


def _write_json(path: str, data: object) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _setup_novel(tmp_path, monkeypatch, novel_id: str = "nov1") -> str:
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    root = tmp_path / novel_id
    lore_path = root / "lore" / "character_lore_library.json"
    plot_path = root / "plot" / "plot_library.json"
    _write_json(str(lore_path), [{"name": "甲", "gender": "female"}, {"name": "乙", "gender": "male"}])
    _write_json(str(plot_path), [{"chapter": 1, "title": "T1", "stages": []}, {"chapter": 2, "title": "T2", "stages": []}])
    _write_json(str(root / "novel.json"), {"name": novel_id, "prose_style": {"preset": "plain-explicit", "custom_addendum": ""}})

    for chapter, name in [(1, "甲"), (1, "乙"), (2, "甲")]:
        archive_dir = root / "chapters" / f"第{chapter}章" / "characters"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / f"{name}_ch{chapter:02d}_archive.json"
        _write_json(str(archive_path), {"name": name, "chapter": chapter, "note": f"{name}-ch{chapter}"})

    edges_path = root / "lore" / "relationship_edges.jsonl"
    edges_path.parent.mkdir(parents=True, exist_ok=True)
    edge_a = {
        "from": "甲", "to": "乙", "nature": "同门",
        "relationship_anchor": "", "from_ref_terms": [], "to_ref_terms": [],
    }
    edge_b = {
        "from": "乙", "to": "甲", "nature": "同门",
        "relationship_anchor": "羁绊", "from_ref_terms": [], "to_ref_terms": ["师兄"],
    }
    edges_path.write_text(
        json.dumps(edge_a, ensure_ascii=False) + "\nnot valid json\n"
        + json.dumps(edge_b, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    _write_json(str(root / "world" / "world_bible.json"), {"setting": "test-realm"})
    _write_json(str(root / "lore" / "story_character_config.json"), {"甲": {"note": "lead"}})
    _write_json(str(root / "token_ledger.json"), {"author_loop": {"1": {"tokens_in": 10, "tokens_out": 5, "tokens_cached": 0, "model": "m"}}})
    _write_json(str(root / "session" / "messages.json"), [{"id": "u-1", "role": "user", "content": "hi", "seq": 0, "ts": 1}])
    _write_json(str(root / "lore" / "sandbox_event_log.json"), {"entries": [{"id": "e1", "chapter": 1, "turn_index": 0, "summary": "evt"}]})

    timeline_dir = root / "chapters" / "character_timeline"
    timeline_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        str(timeline_dir / "甲.json"),
        {"name": "甲", "snapshots": [{"chapter": 1, "stage": 1, "delta": {"mood": "calm"}}]},
    )
    _write_json(
        str(timeline_dir / "乙.json"),
        {"name": "乙", "snapshots": [
            {"chapter": 1, "stage": 1, "delta": {"mood": "eager"}},
            {"chapter": 2, "stage": 1, "delta": {"mood": "tired"}},
        ]},
    )

    (tmp_path / "active.json").write_text(json.dumps({"active": novel_id}), encoding="utf-8")
    return novel_id


def _read_file_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def test_dry_run_does_not_create_sqlite(tmp_path, monkeypatch):
    novel_id = _setup_novel(tmp_path, monkeypatch)
    before = {
        p: _read_file_bytes(p)
        for p in _json_paths(tmp_path / novel_id)
    }

    result = migrate(novel_id, dry_run=True)

    assert result[novel_id]["角色"] == 2
    assert result["__registry__"]["注册表"] == 1
    assert not (tmp_path / novel_id / "chronos.sqlite3").exists()
    after = {p: _read_file_bytes(p) for p in before}
    assert before == after


def test_migrate_matches_json_store_and_preserves_json_files(tmp_path, monkeypatch):
    novel_id = _setup_novel(tmp_path, monkeypatch)
    json_paths = _json_paths(tmp_path / novel_id)
    jsonl_paths = _jsonl_paths(tmp_path / novel_id)
    before = {p: _read_file_bytes(p) for p in json_paths + jsonl_paths}

    migrate(novel_id)
    migrate(novel_id)  # idempotent re-run

    after = {p: _read_file_bytes(p) for p in json_paths + jsonl_paths}
    assert before == after

    from context import character_timeline as ct
    from repositories.json_store import JsonStore
    from repositories.sqlite_store import SqliteStore
    from utils.paths import use_novel

    with use_novel(novel_id):
        js = JsonStore()
        js.scan()
        json_lore = js.list_lore_raw()
        json_plot = js.list_plot_raw()

    ss = SqliteStore(novel_id)
    db_path = str(tmp_path / novel_id / "chronos.sqlite3")
    try:
        assert ss.list_lore_raw() == json_lore
        assert ss.list_plot_raw() == json_plot
        novel_root = tmp_path / novel_id
        for chapter in (1, 2):
            for name in ("甲", "乙"):
                if chapter == 2 and name == "乙":
                    continue
                archive_path = (
                    novel_root / "chapters" / f"第{chapter}章" / "characters"
                    / f"{name}_ch{chapter:02d}_archive.json"
                )
                expected = json.loads(archive_path.read_text(encoding="utf-8"))
                actual = ss.get_archive(name, chapter)
                assert actual == expected

        assert ss.get_doc("world_bible", "/unused") == {"setting": "test-realm"}
        assert ss.get_doc("story_character_config", "/unused") == {"甲": {"note": "lead"}}
        assert ss.get_doc("novel_settings", "")["prose_style"]["preset"] == "plain-explicit"
        assert ss.get_doc("token_ledger", "")["author_loop"]["1"]["tokens_in"] == 10

        g = load_graph(db_path)
        assert set(g["edges"]) == {"甲→乙", "乙→甲"}
        assert g["edges"]["乙→甲"]["relationship_anchor"] == "羁绊"

        with use_novel(novel_id):
            snaps_a = ct.load_timeline("甲")["snapshots"]
            snaps_b = ct.load_timeline("乙")["snapshots"]
        assert len(snaps_a) == 1 and snaps_a[0]["delta"] == {"mood": "calm"}
        assert len(snaps_b) == 2

        rows = ss._conn.execute("SELECT id FROM session_messages").fetchall()
        assert [r[0] for r in rows] == ["u-1"]
        events = ss._conn.execute("SELECT id FROM sandbox_events").fetchall()
        assert [r[0] for r in events] == ["e1"]
    finally:
        ss.close()


def test_migrate_all_reruns_novels_with_existing_sqlite(tmp_path, monkeypatch):
    _setup_novel(tmp_path, monkeypatch, "already-migrated")
    _setup_novel(tmp_path, monkeypatch, "never-migrated")
    migrate("already-migrated")

    result = migrate()

    assert "already-migrated" in result and "never-migrated" in result
    for nid in ("already-migrated", "never-migrated"):
        counts = result[nid]
        assert counts["角色"] == 2 and counts["章节"] == 2 and counts["归档"] == 3
        assert counts["关系边"] == 2 and counts["文档"] == 2 and counts["时间线"] > 0


def _json_paths(novel_root) -> list[str]:
    paths: list[str] = []
    for dirpath, _, filenames in os.walk(novel_root):
        for fname in filenames:
            if fname.endswith(".json"):
                paths.append(os.path.join(dirpath, fname))
    return paths


def _jsonl_paths(novel_root) -> list[str]:
    paths: list[str] = []
    for dirpath, _, filenames in os.walk(novel_root):
        for fname in filenames:
            if fname.endswith(".jsonl"):
                paths.append(os.path.join(dirpath, fname))
    return paths
