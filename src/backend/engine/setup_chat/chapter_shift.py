"""Single mechanical entry point for renumbering a chapter's identity. Every store keyed by
chapter number must have its shift step registered here -- adding a new chapter-keyed store
anywhere else in the codebase means adding a shift step to this module too, or a chapter
insert/delete will silently leave that store's rows pointing at the wrong chapter. See
docs/superpowers/specs/2026-08-15-chapter-insert-character-fk-design.md Part B for the full
inventory and the reasoning behind each store's specific handling (bare UPDATE vs.
read-modify-write vs. cache-evict vs. clear-not-migrate)."""
from __future__ import annotations

import json
import os
import sqlite3


class ChapterBusyError(Exception):
    """A chapter in the requested shift range has an unfinished or uncleared author_loop
    checkpoint. This over-blocks slightly (a *finished* chapter whose checkpoint was never
    explicitly cleared also trips this, since author_loop doesn't auto-clear on finalize) --
    that's the safe direction to err in for an irreversible renumbering operation."""


def _conn() -> sqlite3.Connection:
    from repositories.sqlite_store import get_connection
    from utils.paths import active_novel_id, novel_db_path
    return get_connection(novel_db_path(active_novel_id()))


def _shift_order(from_chapter: int, delta: int, max_chapter: int) -> list[int]:
    rng = list(range(from_chapter, max_chapter + 1))
    return list(reversed(rng)) if delta > 0 else rng


def _assert_not_busy(chapters: list[int]) -> None:
    from utils.paths import author_loop_graph_checkpoint_path

    from engine.author_loop.dialogue_mode.chapter_checkpoint import scan_resumable_chapters
    resumable = set(scan_resumable_chapters(author_loop_graph_checkpoint_path()))
    hit = sorted(resumable & set(chapters))
    if hit:
        raise ChapterBusyError(
            f"第 {'、'.join(str(c) for c in hit)} 章有未清理的主笔生成记录（可能正在生成中，也"
            "可能是上次生成完成后未清理），请先完成/停止生成，或对该章走一次「重置本章」后重试。",
        )


def _shift_plot_chapters_row(conn: sqlite3.Connection, k: int, delta: int) -> None:
    row = conn.execute(
        "SELECT data_json, seq FROM plot_chapters WHERE chapter = ?", (k,),
    ).fetchone()
    if row is None:
        return
    data_json, seq = row
    data = json.loads(data_json)
    data["chapter"] = k + delta
    conn.execute("DELETE FROM plot_chapters WHERE chapter = ?", (k,))
    conn.execute(
        "INSERT INTO plot_chapters (chapter, data_json, seq) VALUES (?, ?, ?)",
        (k + delta, json.dumps(data, ensure_ascii=False), seq),
    )


def _shift_sandbox_events_rows(conn: sqlite3.Connection, k: int, delta: int) -> None:
    rows = conn.execute(
        "SELECT id, entry_json FROM sandbox_events WHERE chapter = ?", (k,),
    ).fetchall()
    for eid, entry_json in rows:
        entry = json.loads(entry_json)
        entry["chapter"] = k + delta
        conn.execute(
            "UPDATE sandbox_events SET chapter = ?, entry_json = ? WHERE id = ?",
            (k + delta, json.dumps(entry, ensure_ascii=False), eid),
        )


def _shift_timeline_snapshots_rows(conn: sqlite3.Connection, k: int, delta: int) -> None:
    # delta_json holds only the delta content (sliders/personality/etc), never the chapter
    # number itself -- a bare column UPDATE is safe here, unlike plot_chapters/sandbox_events.
    conn.execute("UPDATE timeline_snapshots SET chapter = ? WHERE chapter = ?", (k + delta, k))


def _shift_disk_dir(k: int, delta: int) -> None:
    from utils.paths import get_chapter_dir
    src, dst = get_chapter_dir(k), get_chapter_dir(k + delta)
    if os.path.isdir(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.rename(src, dst)


def _clear_author_loop_checkpoint(k: int) -> None:
    from utils.paths import author_loop_graph_checkpoint_path

    from engine.author_loop.dialogue_mode.chapter_checkpoint import clear_chapter_thread
    clear_chapter_thread(author_loop_graph_checkpoint_path(), f"ch{k}")


def _shift_story_sandbox_branches(k: int, delta: int) -> None:
    from engine.story_sandbox import branches as sandbox_branches
    doc = sandbox_branches._load()
    changed = False
    for b in doc["branches"]:
        if b.get("chapter") == k:
            b["chapter"] = k + delta
            changed = True
    if changed:
        sandbox_branches._save(doc)


def _sandbox_branch_ids_for(k: int) -> list[str]:
    from engine.story_sandbox import branches as sandbox_branches
    return [b["id"] for b in sandbox_branches.list_branches(k)]


def _clear_sandbox_checkpoints(k: int, branch_ids: list[str]) -> None:
    from utils.paths import active_novel_id, story_sandbox_checkpoint_path

    from engine.author_loop.dialogue_mode.chapter_checkpoint import clear_chapter_thread
    from engine.story_sandbox.graph import _thread_id
    cp_path = story_sandbox_checkpoint_path()
    novel_id = active_novel_id()
    for branch_id in branch_ids:
        clear_chapter_thread(cp_path, _thread_id(novel_id, k, branch_id))


async def shift_chapters(from_chapter: int, delta: int) -> None:
    """Renumber every chapter-keyed store's rows at or after `from_chapter` by `delta`.
    delta=+1 vacates `from_chapter` (used by insert_chapter, called with
    from_chapter=after_chapter+1). delta=-1 collapses the gap left by a just-deleted chapter
    (used by delete_chapter, called with from_chapter=<deleted chapter>+1, i.e. after the
    deleted row itself has already been removed). No-op if there's nothing at/after
    from_chapter. Zero LLM calls -- purely mechanical."""
    if delta not in (1, -1):
        raise ValueError("delta 只能是 +1 或 -1")
    conn = _conn()
    max_row = conn.execute("SELECT MAX(chapter) FROM plot_chapters").fetchone()
    max_chapter = max_row[0] if max_row else None
    if max_chapter is None or from_chapter > max_chapter:
        return

    order = _shift_order(from_chapter, delta, max_chapter)
    _assert_not_busy(order)
    branch_ids_by_k = {k: _sandbox_branch_ids_for(k) for k in order}

    conn.execute("PRAGMA defer_foreign_keys = ON")
    conn.execute("BEGIN")
    try:
        for k in order:
            _shift_plot_chapters_row(conn, k, delta)
            _shift_sandbox_events_rows(conn, k, delta)
            _shift_timeline_snapshots_rows(conn, k, delta)
        evict_from = min(from_chapter, from_chapter + delta)
        conn.execute("DELETE FROM character_archives WHERE chapter >= ?", (evict_from,))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise

    # Filesystem + checkpoint cleanup happen after the DB commit succeeds -- if either of these
    # fails partway, the DB is already in its correct final state (nothing to roll back to) and
    # the failure is a filesystem-permissions-class problem the operator can fix and retry
    # (re-running shift_chapters is safe: rows already at k+delta are simply skipped since
    # _shift_plot_chapters_row's SELECT at k finds nothing).
    from repositories import get_archive_repo, get_sandbox_vector_memory_repo
    get_archive_repo().evict_from(evict_from)
    vector_repo = get_sandbox_vector_memory_repo()
    for k in order:
        _shift_disk_dir(k, delta)
        _clear_author_loop_checkpoint(k)
        _clear_sandbox_checkpoints(k, branch_ids_by_k[k])
        _shift_story_sandbox_branches(k, delta)
        await vector_repo.shift_chapter(k, delta)
