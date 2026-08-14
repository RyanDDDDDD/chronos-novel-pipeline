"""scripts/migrate_json_to_sqlite.py

One-off migration: copy lore/plot/archive JSON assets into per-novel chronos.sqlite3 + registry.
Non-destructive — original JSON files are never modified or deleted. Idempotent (re-run
clears target tables and re-imports).

Usage:
    uv run python scripts/migrate_json_to_sqlite.py [--novel <novel_id>] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, datetime

_ARCHIVE_RE = re.compile(r"^(.+)_ch(\d+)_archive\.json$")
_CHECKPOINT_RE = re.compile(r"^第(\d+)章$")


def _read_json(path: str) -> object | None:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _db_path(novel_id: str) -> str:
    from utils.paths import novel_dir

    return os.path.join(novel_dir(novel_id), "chronos.sqlite3")


def _collect_archives(novel_id: str) -> list[tuple[str, int, dict]]:
    from utils.paths import novel_dir

    chapters_root = os.path.join(novel_dir(novel_id), "chapters")
    entries: list[tuple[str, int, dict]] = []
    if not os.path.isdir(chapters_root):
        return entries
    for dirpath, _, filenames in os.walk(chapters_root):
        for fname in filenames:
            m = _ARCHIVE_RE.match(fname)
            if not m:
                continue
            name, ch_str = m.group(1), m.group(2)
            chapter = int(ch_str)
            path = os.path.join(dirpath, fname)
            data = _read_json(path)
            if isinstance(data, dict):
                entries.append((name, chapter, data))
    return entries


def _parse_relationship_edge_line(raw_line: bytes) -> dict | None:
    try:
        line = raw_line.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    if not line:
        return None
    try:
        edge = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(edge, dict):
        return None
    frm = str(edge.get("from", "")).strip()
    to = str(edge.get("to", "")).strip()
    if not frm or not to:
        return None
    return edge


def _clean_ref_terms(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [t.strip() for t in raw if isinstance(t, str) and t.strip()]


def _migrate_registry(*, dry_run: bool) -> int:
    from repositories.registry_store import get_registry_connection
    from utils.paths import active_novel_pointer_path, novels_dir

    root = novels_dir()
    if not os.path.isdir(root):
        return 0

    active_id: str | None = None
    active_data = _read_json(active_novel_pointer_path())
    if isinstance(active_data, dict) and isinstance(active_data.get("active"), str):
        active_id = active_data["active"]

    rows: list[tuple[str, str, str, int, str | None]] = []
    for name in os.listdir(root):
        if name in (".trash", "_registry.sqlite3"):
            continue
        novel_path = os.path.join(root, name)
        if not os.path.isdir(novel_path):
            continue
        meta_path = os.path.join(novel_path, "novel.json")
        if not os.path.isfile(meta_path):
            continue
        meta = _read_json(meta_path)
        if not isinstance(meta, dict):
            meta = {}
        display_name = meta.get("name") if isinstance(meta.get("name"), str) else name
        created_at = datetime.fromtimestamp(
            os.path.getctime(meta_path), tz=UTC,
        ).isoformat()
        deleted_at: str | None = None
        if meta.get("deleted"):
            ts = meta.get("deleted_at")
            if isinstance(ts, (int, float)):
                deleted_at = datetime.fromtimestamp(ts, tz=UTC).isoformat()
            else:
                deleted_at = datetime.now(UTC).isoformat()
        is_active = 1 if name == active_id else 0
        rows.append((name, display_name or name, created_at, is_active, deleted_at))

    if dry_run:
        return len(rows)

    conn = get_registry_connection()
    conn.execute("DELETE FROM novels")
    for nid, display_name, created_at, is_active, deleted_at in rows:
        conn.execute(
            "INSERT INTO novels (id, name, created_at, is_active, deleted_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (nid, display_name, created_at, is_active, deleted_at),
        )
    conn.commit()
    return len(rows)


def _migrate_relationship_edges(novel_id: str, *, dry_run: bool) -> int:
    from utils.paths import relationship_edges_path, use_novel

    with use_novel(novel_id):
        path = relationship_edges_path()

    if not os.path.exists(path):
        return 0

    with open(path, "rb") as f:
        raw_lines = f.read().splitlines()

    edges: list[dict] = []
    for raw_line in raw_lines:
        edge = _parse_relationship_edge_line(raw_line)
        if edge is not None:
            edges.append(edge)

    if dry_run:
        return len(edges)

    from repositories.sqlite_store import _character_id, get_connection

    conn = get_connection(_db_path(novel_id))
    conn.execute("DELETE FROM relationship_edges")
    for edge in edges:
        frm = str(edge.get("from", "")).strip()
        to = str(edge.get("to", "")).strip()
        from_id = _character_id(conn, frm)
        to_id = _character_id(conn, to)
        if from_id is None or to_id is None:
            continue  # orphan edge whose endpoint never made it into lore_characters
        conn.execute(
            "INSERT INTO relationship_edges (from_character_id, to_character_id, nature,"
            " relationship_anchor, from_ref_terms_json, to_ref_terms_json, deleted)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                from_id,
                to_id,
                str(edge.get("nature", "")),
                str(edge.get("relationship_anchor", "")),
                json.dumps(_clean_ref_terms(edge.get("from_ref_terms"))),
                json.dumps(_clean_ref_terms(edge.get("to_ref_terms"))),
                1 if edge.get("deleted") else 0,
            ),
        )
    conn.commit()
    return len(edges)


def _migrate_documents(novel_id: str, *, dry_run: bool) -> int:
    from utils.paths import (
        story_character_config_path,
        use_novel,
        world_bible_path,
    )

    docs: list[tuple[str, object]] = []
    with use_novel(novel_id):
        for doc_key, file_path in (
            ("world_bible", world_bible_path()),
            ("story_character_config", story_character_config_path()),
        ):
            data = _read_json(file_path)
            if data is not None:
                docs.append((doc_key, data))

    if dry_run:
        return len(docs)

    from repositories.sqlite_store import get_connection

    conn = get_connection(_db_path(novel_id))
    conn.execute(
        "DELETE FROM documents WHERE doc_key IN ('world_bible', 'story_character_config')",
    )
    for doc_key, data in docs:
        conn.execute(
            "INSERT OR REPLACE INTO documents (doc_key, data_json) VALUES (?, ?)",
            (doc_key, json.dumps(data, ensure_ascii=False)),
        )
    conn.commit()
    return len(docs)


def _migrate_timeline(novel_id: str, *, dry_run: bool) -> int:
    from utils.paths import novel_dir

    timeline_dir = os.path.join(novel_dir(novel_id), "chapters", "character_timeline")
    if not os.path.isdir(timeline_dir):
        return 0

    snapshots: list[tuple[str, int, int, dict]] = []
    for fname in os.listdir(timeline_dir):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(timeline_dir, fname)
        tl = _read_json(path)
        if not isinstance(tl, dict):
            continue
        name = str(tl.get("name", fname[:-5]))
        for snap in tl.get("snapshots") or []:
            if not isinstance(snap, dict):
                continue
            chapter = int(snap.get("chapter", 0))
            stage = int(snap.get("stage", 0))
            delta = snap.get("delta")
            if not isinstance(delta, dict):
                delta = {}
            snapshots.append((name, chapter, stage, delta))

    if dry_run:
        return len(snapshots)

    from repositories.sqlite_store import _character_id, get_connection

    conn = get_connection(_db_path(novel_id))
    conn.execute("DELETE FROM timeline_snapshots")
    for name, chapter, stage, delta in snapshots:
        character_id = _character_id(conn, name)
        if character_id is None:
            # Ensure lore parent exists so FK insert succeeds for JSON-era timelines that
            # predate a roster row (legacy data); keep the name as the card identity.
            conn.execute(
                "INSERT INTO lore_characters (name, data_json, seq) VALUES (?, ?, ?)",
                (name, json.dumps({"name": name}, ensure_ascii=False),
                 conn.execute("SELECT COALESCE(MAX(seq), -1) + 1 FROM lore_characters").fetchone()[0]),
            )
            character_id = _character_id(conn, name)
        conn.execute(
            "INSERT OR IGNORE INTO plot_chapters (chapter, data_json, seq) VALUES (?, '{}', ?)",
            (chapter, chapter),
        )
        conn.execute(
            "INSERT OR REPLACE INTO timeline_snapshots"
            " (character_id, chapter, stage, delta_json) VALUES (?, ?, ?, ?)",
            (character_id, chapter, stage, json.dumps(delta, ensure_ascii=False)),
        )
    conn.commit()
    return len(snapshots)


def _migrate_single_doc(novel_id: str, doc_key: str, path: str, *, dry_run: bool) -> int:
    data = _read_json(path)
    if data is None:
        return 0
    if dry_run:
        return 1
    from repositories.sqlite_store import get_connection

    conn = get_connection(_db_path(novel_id))
    conn.execute("DELETE FROM documents WHERE doc_key = ?", (doc_key,))
    conn.execute(
        "INSERT OR REPLACE INTO documents (doc_key, data_json) VALUES (?, ?)",
        (doc_key, json.dumps(data, ensure_ascii=False)),
    )
    conn.commit()
    return 1


def _migrate_novel_settings(novel_id: str, *, dry_run: bool) -> int:
    from utils.paths import novel_dir

    meta = _read_json(os.path.join(novel_dir(novel_id), "novel.json"))
    if not isinstance(meta, dict):
        return 0
    settings: dict = {}
    ps = meta.get("prose_style")
    if isinstance(ps, dict):
        settings["prose_style"] = ps
    sdtc = meta.get("sandbox_dialogue_turn_count")
    if isinstance(sdtc, int) and not isinstance(sdtc, bool):
        settings["sandbox_dialogue_turn_count"] = sdtc
    if not settings:
        return 0
    if dry_run:
        return 1
    from repositories.sqlite_store import get_connection

    conn = get_connection(_db_path(novel_id))
    conn.execute("DELETE FROM documents WHERE doc_key = 'novel_settings'")
    conn.execute(
        "INSERT OR REPLACE INTO documents (doc_key, data_json) VALUES (?, ?)",
        ("novel_settings", json.dumps(settings, ensure_ascii=False)),
    )
    conn.commit()
    return 1


def _migrate_token_ledger(novel_id: str, *, dry_run: bool) -> int:
    from utils.paths import novel_dir

    return _migrate_single_doc(
        novel_id, "token_ledger",
        os.path.join(novel_dir(novel_id), "token_ledger.json"),
        dry_run=dry_run,
    )


def _migrate_setup_chat_memory(novel_id: str, *, dry_run: bool) -> int:
    from utils.paths import novel_dir

    return _migrate_single_doc(
        novel_id, "setup_chat_memory",
        os.path.join(novel_dir(novel_id), "setup_chat", "memory.json"),
        dry_run=dry_run,
    )


def _migrate_recall_cooldown(novel_id: str, *, dry_run: bool) -> int:
    from utils.paths import recall_cooldown_path, use_novel

    with use_novel(novel_id):
        path = recall_cooldown_path()
    return _migrate_single_doc(novel_id, "recall_cooldown", path, dry_run=dry_run)


def _migrate_story_sandbox_branches(novel_id: str, *, dry_run: bool) -> int:
    from utils.paths import novel_dir

    return _migrate_single_doc(
        novel_id, "story_sandbox_branches",
        os.path.join(novel_dir(novel_id), "chapters", "_story_sandbox_branches.json"),
        dry_run=dry_run,
    )


def _migrate_legacy_docs(novel_id: str, *, dry_run: bool) -> int:
    from utils.paths import novel_dir

    root = novel_dir(novel_id)
    count = 0
    for doc_key, rel in (
        ("core_event_state", os.path.join("lore", "core_event_state.json")),
        ("character_schema", os.path.join("world", "character_schema.json")),
        ("core_events", os.path.join("world", "core_events.json")),
    ):
        count += _migrate_single_doc(novel_id, doc_key, os.path.join(root, rel), dry_run=dry_run)
    return count


def _migrate_entity_index(novel_id: str, *, dry_run: bool) -> int:
    from utils.paths import entity_index_cache_dir

    count = 0
    cache_dir = entity_index_cache_dir(novel_id)
    for kind, doc_key in (("character", "entity_index_character"), ("entity", "entity_index_entity")):
        count += _migrate_single_doc(
            novel_id, doc_key, os.path.join(cache_dir, f"{kind}.json"), dry_run=dry_run,
        )
    return count


def _migrate_attachments_index(novel_id: str, *, dry_run: bool) -> int:
    from utils.paths import novel_attachments_dir

    return _migrate_single_doc(
        novel_id, "attachments_index",
        os.path.join(novel_attachments_dir(novel_id), "index.json"),
        dry_run=dry_run,
    )


def _migrate_author_loop_skill_prefs(novel_id: str, *, dry_run: bool) -> int:
    from utils.paths import novel_dir

    return _migrate_single_doc(
        novel_id, "author_loop_skill_prefs",
        os.path.join(novel_dir(novel_id), "author_loop_skill_prefs.json"),
        dry_run=dry_run,
    )


def _migrate_snapshot_meta(novel_id: str, *, dry_run: bool) -> int:
    from utils.paths import novel_dir

    return _migrate_single_doc(
        novel_id, "snapshot_meta",
        os.path.join(novel_dir(novel_id), "setup_chat", "snapshot", "meta.json"),
        dry_run=dry_run,
    )


def _migrate_author_loop_checkpoints(novel_id: str, *, dry_run: bool) -> int:
    from utils.paths import novel_dir

    chapters_root = os.path.join(novel_dir(novel_id), "chapters")
    if not os.path.isdir(chapters_root):
        return 0
    count = 0
    doc_keys: list[str] = []
    payloads: list[str] = []
    for entry in os.listdir(chapters_root):
        m = _CHECKPOINT_RE.match(entry)
        if not m:
            continue
        cp_path = os.path.join(chapters_root, entry, "_author_loop_checkpoint.json")
        data = _read_json(cp_path)
        if data is None:
            continue
        chapter = int(m.group(1))
        doc_key = f"author_loop_checkpoint_ch{chapter}"
        doc_keys.append(doc_key)
        payloads.append(json.dumps(data, ensure_ascii=False))
        count += 1
    if dry_run or count == 0:
        return count
    from repositories.sqlite_store import get_connection

    conn = get_connection(_db_path(novel_id))
    if doc_keys:
        placeholders = ",".join("?" * len(doc_keys))
        conn.execute(
            f"DELETE FROM documents WHERE doc_key IN ({placeholders})",
            doc_keys,
        )
    for doc_key, payload in zip(doc_keys, payloads, strict=True):
        conn.execute(
            "INSERT OR REPLACE INTO documents (doc_key, data_json) VALUES (?, ?)",
            (doc_key, payload),
        )
    conn.commit()
    return count


def _encode_session_content(rec: dict) -> str:
    base = rec.get("content", "")
    extras = {k: rec[k] for k in ("thinking", "options") if k in rec}
    if extras:
        return json.dumps({"content": base, **extras}, ensure_ascii=False)
    return str(base)


def _migrate_session_messages(novel_id: str, *, dry_run: bool) -> int:
    from utils.paths import novel_dir

    path = os.path.join(novel_dir(novel_id), "session", "messages.json")
    data = _read_json(path)
    if not isinstance(data, list):
        return 0
    messages = [m for m in data if isinstance(m, dict) and m.get("id") and m.get("role")]
    if dry_run:
        return len(messages)
    from repositories.sqlite_store import get_connection

    conn = get_connection(_db_path(novel_id))
    conn.execute("DELETE FROM session_messages")
    for rec in messages:
        conn.execute(
            "INSERT INTO session_messages (id, role, content, seq, ts) VALUES (?, ?, ?, ?, ?)",
            (
                str(rec["id"]),
                str(rec["role"]),
                _encode_session_content(rec),
                int(rec.get("seq", 0)),
                int(rec.get("ts", 0)),
            ),
        )
    conn.commit()
    return len(messages)


def _migrate_sandbox_events(novel_id: str, *, dry_run: bool) -> int:
    from utils.paths import sandbox_event_log_path, use_novel

    with use_novel(novel_id):
        path = sandbox_event_log_path()
    data = _read_json(path)
    if not isinstance(data, dict):
        return 0
    entries = [e for e in (data.get("entries") or []) if isinstance(e, dict) and e.get("id")]
    if dry_run:
        return len(entries)
    from repositories.sqlite_store import get_connection

    conn = get_connection(_db_path(novel_id))
    conn.execute("DELETE FROM sandbox_events")
    for entry in entries:
        conn.execute(
            "INSERT INTO sandbox_events (id, chapter, turn_index, entry_json) VALUES (?, ?, ?, ?)",
            (
                str(entry["id"]),
                int(entry.get("chapter", 0)),
                int(entry.get("turn_index", 0)),
                json.dumps(entry, ensure_ascii=False),
            ),
        )
    conn.commit()
    return len(entries)


def _migrate_one(novel_id: str, *, dry_run: bool = False) -> dict[str, int]:
    from repositories.json_store import JsonStore
    from repositories.sqlite_store import SqliteStore
    from utils.paths import use_novel

    with use_novel(novel_id):
        json_store = JsonStore()
        json_store.scan()
        lore = json_store.list_lore_raw()
        plot = json_store.list_plot_raw()
        archives = _collect_archives(novel_id)

    counts: dict[str, int] = {
        "角色": len(lore),
        "章节": len(plot),
        "归档": len(archives),
        "关系边": _migrate_relationship_edges(novel_id, dry_run=dry_run),
        "文档": _migrate_documents(novel_id, dry_run=dry_run),
        "时间线": _migrate_timeline(novel_id, dry_run=dry_run),
        "小说设置": _migrate_novel_settings(novel_id, dry_run=dry_run),
        "token账本": _migrate_token_ledger(novel_id, dry_run=dry_run),
        "设定记忆": _migrate_setup_chat_memory(novel_id, dry_run=dry_run),
        "召回冷却": _migrate_recall_cooldown(novel_id, dry_run=dry_run),
        "故事线": _migrate_story_sandbox_branches(novel_id, dry_run=dry_run),
        "遗留文档": _migrate_legacy_docs(novel_id, dry_run=dry_run),
        "实体索引": _migrate_entity_index(novel_id, dry_run=dry_run),
        "附件索引": _migrate_attachments_index(novel_id, dry_run=dry_run),
        "主笔偏好": _migrate_author_loop_skill_prefs(novel_id, dry_run=dry_run),
        "快照元数据": _migrate_snapshot_meta(novel_id, dry_run=dry_run),
        "主笔检查点": _migrate_author_loop_checkpoints(novel_id, dry_run=dry_run),
        "会话消息": _migrate_session_messages(novel_id, dry_run=dry_run),
        "沙盒事件": _migrate_sandbox_events(novel_id, dry_run=dry_run),
    }

    if dry_run:
        return counts

    sqlite_store = SqliteStore(novel_id)
    try:
        sqlite_store.save_lore(lore)
        sqlite_store.save_plot(plot)
        for name, chapter, data in archives:
            sqlite_store.save_archive(name, chapter, data)
    finally:
        sqlite_store.close()

    return counts


def _novel_ids(explicit: str | None) -> list[str]:
    if explicit:
        return [explicit]
    from utils.paths import novels_dir

    root = novels_dir()
    if not os.path.isdir(root):
        return []
    return sorted(
        d for d in os.listdir(root)
        if os.path.isdir(os.path.join(root, d)) and d not in (".trash",)
    )


def migrate(
    novel_id: str | None = None,
    *,
    dry_run: bool = False,
) -> dict[str, dict[str, int]]:
    results: dict[str, dict[str, int]] = {}
    n_registry = _migrate_registry(dry_run=dry_run)
    results["__registry__"] = {"注册表": n_registry}
    for nid in _novel_ids(novel_id):
        results[nid] = _migrate_one(nid, dry_run=dry_run)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--novel", help="Novel id to migrate (default: all novels)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count entries only; do not write sqlite",
    )
    args = parser.parse_args()

    results = migrate(args.novel, dry_run=args.dry_run)
    if len(results) <= 1 and not any(k != "__registry__" for k in results):
        print("没有需要迁移的小说。")
        return

    label = "（dry-run，未写入）" if args.dry_run else ""
    if "__registry__" in results:
        n = results["__registry__"].get("注册表", 0)
        print(f"注册表{label}: {n} 本小说")
    for nid, counts in results.items():
        if nid == "__registry__":
            continue
        parts = ", ".join(f"{k} {v}" for k, v in counts.items())
        print(f"{nid}{label}: {parts}")


if __name__ == "__main__":
    main()
