"""A read-only grounding assembly of a chapter's skeleton expansion: world bible + chapter
character archive + thick outline + character list.

Reuse the same material in the author_loop skeleton stage (plot thick outline + roster +
world/archive context); read_skeleton_seed (one-shot) and skeleton_pipeline.active_seed_injection
(persistent, per-turn) both render through this module. Pure reading, no writing to disk."""
from __future__ import annotations


def build_skeleton_seed(chapter: int) -> dict:
    """
Assembling a chapter to expand grounding. There is no chapter → stages/roster is empty.
    world_summary/archive_summary are always present, empty-safe (render to a placeholder /
    header-only string when the novel has no world bible yet or this chapter has no derived
    archive yet). Roster/per-stage characters are derived at read time from each stage's
    `description` via entity_index.scan_characters, not from a persisted `characters` field."""
    from repositories import get_plot_repo, get_world_repo

    from engine.archive.archive_view import render_archive_summary, render_chapter_archives
    from engine.memory_recall.entity_index import scan_characters
    from engine.setup.chat_summary import render_world_chat

    chapters = get_plot_repo().list_raw()
    ch = next((c for c in chapters if isinstance(c, dict) and c.get("chapter") == chapter), {})
    raw_stages = ch.get("stages") or []

    roster: list[str] = []
    stages: list[dict] = []
    for s in raw_stages:
        chars = scan_characters(str(s.get("description") or ""))
        for c in chars:
            if c not in roster:
                roster.append(c)
        stages.append({
            "stage_num": s.get("stage_num"),
            "description": s.get("description", ""),
            "location": s.get("location", ""),
            "characters": chars,
        })

    world_summary = render_world_chat(get_world_repo().get())
    archive_data = render_chapter_archives(chapter)
    archive_summary = render_archive_summary(chapter, archive_data.get("characters") or [])

    return {
        "chapter": chapter, "roster": roster, "stages": stages,
        "world_summary": world_summary, "archive_summary": archive_summary,
    }


def render_skeleton_seed(seed: dict) -> str:
    """Render a build_skeleton_seed() dict into the four-block grounding text: world bible,
    chapter character archive, chapter outline + roster."""
    lines = [
        f"第 {seed['chapter']} 章 · 骨架扩写 grounding",
        "## 世界观",
        seed.get("world_summary") or "（空）",
        "## 角色档案",
        seed.get("archive_summary") or "（暂无角色档案）",
        "本章角色名单（大纲里『他们/众人』指代只能落到这些全名）："
        f"{'、'.join(seed.get('roster') or []) or '（无）'}",
        "各段粗大纲（逐段扩写成含细节的写作底稿）：",
    ]
    for s in seed.get("stages") or []:
        chars = "、".join(s.get("characters") or []) or "（无）"
        lines.append(f"  - stage{s['stage_num']}（在场：{chars}）：{s['description']}")
    return "\n".join(lines)
