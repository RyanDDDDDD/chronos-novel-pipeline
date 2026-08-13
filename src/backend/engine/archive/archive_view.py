"""Character profile management page (read-only browsing + delete and rebuild) back-end logic.

The page is read-only and archive.json has been constructed (no recalculation); the slider numbers are rendered into rubric text for display.
Deletion is at the entire chapter level (from_chapter): archive.json file + timeline truncation of each character + memory index evict
Clearing three places at the same time - clearing any one of them will cause the reconstruction to read stale data."""
from __future__ import annotations

from typing import Any

from engine.archive.sliders import render_slider


def _built_chapters() -> dict[int, list[str]]:
    """All chapters with at least one persisted archive, and which characters. SQLite is the
    sole source of truth (2026-08-09 fix: replaced a stale filesystem scan left over from the
    pre-SQLite archive.json era -- see docs/superpowers/specs/2026-08-09-archive-view-sqlite-
    migration-gap-fix.md)."""
    from repositories import get_archive_repo

    return get_archive_repo().list_built()


def _plot_chapters() -> list[int]:
    """Every chapter with a persisted plot entry (SQLite plot_chapters table). Mirrors
    engine/setup_chat/construction_plan.py's own _plot_chapters() -- both independently need
    "which chapters exist in the plot", and both now read the same source correctly
    (2026-08-09 fix: this one used to read plot_library_path()'s JSON file, which
    SqlitePlotRepository's SQLite-backed writes never touch)."""
    from repositories import get_plot_repo

    chapters = get_plot_repo().list_raw()
    return sorted(
        int(c["chapter"]) for c in chapters
        if isinstance(c, dict) and isinstance(c.get("chapter"), int)
    )


def list_archive_overview() -> dict:
    """Overview: built chapters x characters, plus every plotted chapter annotated with its
    roster (from plot) and which of those characters already have an archive -- the
    character archive page diffs roster against built to decide whether to show the
    "one-click build" affordance for a chapter."""
    from engine.setup_chat.timeline_seed import _chapter_roster

    built = _built_chapters()
    return {
        "built": [{"chapter": ch, "characters": built[ch]} for ch in sorted(built)],
        "plot_chapters": [
            {"chapter": ch, "roster": _chapter_roster(ch), "built": built.get(ch, [])}
            for ch in _plot_chapters()
        ],
    }


def _render_stage_sliders(rubrics: dict, sliders: dict[str, Any]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for axis, value in (sliders or {}).items():
        if isinstance(value, int):
            out[axis] = {"value": value, "label": render_slider(rubrics, axis, value)}
        elif isinstance(value, dict) and "level" in value and "text" in value:
            out[axis] = {"value": value["level"], "label": str(value["text"])}
        else:
            out[axis] = {"value": value, "label": str(value)}
    return out


#Cast-level constants never forwarded to the archive page (mirrors the pre-flatten response's
#implicit contract: only name/role/causal_anchors + the evolving profile fields were exposed).
_BASE_ONLY_FIELDS = {
    "name", "given_name", "role", "race", "causal_anchors", "extensions",
}


def render_character_profile(name: str, arc: dict) -> dict:
    from engine.archive.sliders import character_rubrics

    rubrics = character_rubrics(name)
    profile = {k: v for k, v in arc.items() if k not in _BASE_ONLY_FIELDS}
    profile["sliders"] = _render_stage_sliders(rubrics, arc.get("sliders") or {})
    return {"name": name, "role": arc.get("role", ""), "causal_anchors": arc.get("causal_anchors", {}), **profile}


def render_chapter_archives(chapter: int) -> dict:
    """All character files in this chapter, flat (no per-stage nesting); the slider is rendered
    as {value,label}; no files → characters are empty."""
    from repositories import get_archive_repo

    raw = get_archive_repo().preload(chapter)
    characters = [render_character_profile(name, raw[name]) for name in sorted(raw)]
    return {"chapter": chapter, "characters": characters}


def render_archive_summary(chapter: int, chars: list[dict]) -> str:
    """Character archive list (shape from render_chapter_archives, flat) → concise Chinese
    summary text — never raw JSON, per base-prompt output convention."""
    lines = [f"第 {chapter} 章角色档案："]
    for c in chars:
        name = c.get("name", "?")
        role = c.get("role", "")
        anchors = c.get("causal_anchors") or {}
        lines.append(f"- {name}（{role}）")
        for k, v in anchors.items():
            if isinstance(v, str) and v.strip():
                lines.append(f"    · {k}：{v}")
        parts: list[str] = []
        if c.get("location"):
            parts.append(f"@{c['location']}")
        sr = c.get("self_ref") or {}
        if isinstance(sr, dict):
            default = sr.get("_default")
            if default:
                parts.append(f"自称：{default}")
        vt = c.get("verbal_tic")
        if isinstance(vt, str) and vt.strip():
            parts.append(f"口癖：{vt}")
        sl = c.get("sliders") or {}
        if sl:
            parts.append(f"滑块：{sl}")
        if parts:
            lines.append(f"    · {' · '.join(str(p) for p in parts)}")
    return "\n".join(lines)


def delete_archives_from(from_chapter: int) -> dict:
    """Delete every archived character at or after from_chapter (SQLite character_archives
    rows, via evict_from) + truncate each affected character's timeline from that chapter.
    Both stores are the sole persistence for their data now, so evicting is the deletion --
    no separate on-disk file pass needed (2026-08-09 fix: the old file-removal loop here had
    been silently iterating an always-empty directory since the SQLite migration)."""
    from repositories import get_archive_repo, get_timeline_repo

    built = _built_chapters()
    deleted_chapters = [ch for ch in sorted(built) if ch >= from_chapter]
    affected_before: set[str] = {
        name for ch in deleted_chapters for name in built.get(ch, [])
    }

    timeline_repo = get_timeline_repo()
    affected: list[str] = [
        name
        for name in timeline_repo.list_names()
        if timeline_repo.truncate_from(name, from_chapter)
    ]
    get_archive_repo().evict_from(from_chapter)
    return {
        "from_chapter": from_chapter,
        "deleted": {
            "chapters": deleted_chapters,
            "characters": sorted(affected_before | set(affected)),
        },
    }


def delete_character_archives(name: str) -> dict:
    """删除单个角色在所有已构建章节下的 resolved archive.json（含 .bak 备份）+ 内存缓存 +
    该角色的整条 timeline（不动同章其它角色）。

    cast 编辑改动角色底层字段（physique/causal_anchors 等）后，旧 archive 是基于改动前的底数据 resolve
    出来的，必须连带清掉，否则章节写作/档案页会继续读到跟当前 cast 对不上的 stale 档案。timeline 同样
    要清——旧 delta 也是基于改动前的底数据推演的，留着不清会让 missing_timeline_targets()（只看 timeline
    快照存不存在，不看 archive.json）把这些坐标永远当成"已完成"，"一键构建"再也不会补上被删掉的
    archive.json。self-contained：调用方不必自己再另外调 timeline 清理（对齐 delete_archives_from 的
    自洽设计）。"""
    from repositories import get_archive_repo, get_timeline_repo

    deleted_chapters = sorted(
        ch for ch, names in _built_chapters().items() if name in names
    )
    get_archive_repo().evict_for(name)
    removed_stages = get_timeline_repo().truncate_from(name, 0)
    return {
        "name": name, "deleted_chapters": deleted_chapters,
        "removed_stages": removed_stages,
    }
