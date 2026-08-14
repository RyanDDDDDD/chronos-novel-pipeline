"""Tool set for setting up the co-creation dialogue agent: read summary/structured disk writing (in principle, no in-tool LLM).

Exception: write_chapter_skeleton calls into chapter_review.py once a whole
chapter's skeleton is complete, to run chapter-level review hooks in parallel
(transition + per-stage axes) — see chapter_review.py for details.
Exception: _add_character_core fires a non-blocking background relationship-inference LLM call when the roster already has other characters.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from langchain_core.tools import tool

from engine.archive.archive_error import assert_valid
from engine.setup.cast.cast_validator import validate_character_edit
from engine.setup.chat_summary import (
    format_tool_done,
    render_cast_chat,
    render_chapter_chat,
    render_character_chat,
    render_world_chat,
)
from engine.setup_chat.tool_args import (
    AddRelationshipEdgeArgs,
    AutoBuildSetupArgs,
    AutoExpandSkeletonArgs,
    ConstructWorldArgs,
    DeleteChapterArgs,
    DeleteCharacterArgs,
    GenerateOneChapterArgs,
    InsertChapterArgs,
    LoadSkillArgs,
    PatchChapterArgs,
    PatchOp,
    PatchTextFragmentArgs,
    PresentChoicesArgs,
    QueryCharacterVoiceArgs,
    ReadArchiveSeedArgs,
    ReadArchiveStatusArgs,
    ReadAuthorManuscriptArgs,
    ReadChapterSkeletonArgs,
    ReadCharacterArchiveArgs,
    ReadCharacterArgs,
    ReadProseStylePresetArgs,
    ReadRelationshipsArgs,
    ReadSetupSummaryArgs,
    ReadSkeletonSeedArgs,
    RefineWorldArgs,
    RemoveRelationshipEdgeArgs,
    RenameNovelTitleArgs,
    SetChapterDirectionArgs,
    SetStageExtensionsArgs,
    SetStageLensArgs,
    WriteChapterSkeletonArgs,
    WriteCharacterArchiveArgs,
    WriteProseStylePresetArgs,
    _EditCharacterPlaceholderArgs,
    _StaticCharacterFieldsArgs,
)

_pending_relationship_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]
# Serializes cast roster read-modify-write (add/edit/delete). JsonStore.save_lore is whole-file
# replace with no atomic append; parallel add_character tool calls would silently drop entries.
_cast_write_lock = asyncio.Lock()


def _read_domain(target: str):
    """
The current data of a certain setting field (read from repo); unknown field → 'unknown' sentinel."""
    from repositories import (
        get_lore_repo,
        get_plot_repo,
        get_world_repo,
    )
    if target == "world":
        return get_world_repo().get()
    if target == "cast":
        return get_lore_repo().list_raw()
    if target == "plot":
        return get_plot_repo().list_raw()
    return "unknown"


@tool(args_schema=ReadSetupSummaryArgs)
def read_setup_summary(target: str) -> str:
    """Read the [text summary] (not JSON) set in a certain field of the current novel. target ∈ {world, cast, plot}.
    You can adjust this tool to understand the current situation before refining. The complete structured content can be viewed on the "Settings Page"."""
    data = _read_domain(target)
    if data == "unknown":
        return f"未知 target「{target}」，只能是 world / cast / plot。"
    if not data:
        return f"{target} 尚未构建。"
    return _render_setup_summary(target, data)


def _render_plot_summary(chapters: list[Any]) -> str:
    if not chapters:
        return "（暂无章节）"
    lines: list[str] = []
    for i, ch in enumerate(chapters):
        if not isinstance(ch, dict):
            continue
        title = str(ch.get("title") or f"第{i + 1}章").strip()
        stages = ch.get("stages")
        stage_n = len(stages) if isinstance(stages, list) else 0
        suffix = f"（{stage_n} 个场景）" if stage_n else ""
        lines.append(f"第 {i + 1} 章：{title}{suffix}")
    return "\n".join(lines) if lines else "（暂无章节）"


def _render_setup_summary(target: str, data: object) -> str:
    if target == "world":
        return render_world_chat(data if isinstance(data, dict) else {})
    if target == "cast":
        return render_cast_chat(data if isinstance(data, list) else [])
    if target == "plot":
        return _render_plot_summary(data if isinstance(data, list) else [])
    return "未知类型"



@tool(args_schema=ConstructWorldArgs)
async def construct_world(
    tone: str,
    background: str,
    factions: list,
    geography: list,
    races: list,
    power_system: list,
    core_themes: list,
) -> str:
    """
Write a worldview from scratch (or start over). The main agent fills in the complete fields; the verification is completed by args_schema, and this tool only writes the disk.
    Just report the results and stop when you're done; don't continue to build characters or plot this round."""
    args = ConstructWorldArgs(
        tone=tone, background=background,
        factions=factions, geography=geography, races=races,
        power_system=power_system, core_themes=core_themes,
    )
    bible = args.to_bible()
    try:
        from repositories import get_world_repo
        get_world_repo().save(bible)
    except OSError as exc:
        return f"写盘失败：{exc}"
    # Always writes the full bible (factions/geography/races/power_system included every call) --
    # the process-level entity vocab cache (entity_index.py) must be invalidated so recall picks
    # up any new/renamed named entries on the very next sandbox turn, not just after a novel
    # switch or restart.
    from engine.memory_recall.entity_index import invalidate_entity_vocab_cache
    from engine.setup_chat.world_background_review import schedule_world_quality_review

    invalidate_entity_vocab_cache()
    schedule_world_quality_review(complete=True)
    return format_tool_done("已写入世界观。", render_world_chat(bible))


@tool(args_schema=RefineWorldArgs)
async def refine_world(
    tone: str,
    background: str,
    factions: list,
    geography: list,
    races: list,
    power_system: list,
    core_themes: list,
) -> str:
    """
Refining the world view: The main agent transfers the complete new settings and overwrites the disk. Must already have world_bible; use construct_world from scratch."""
    from repositories import get_world_repo
    bible = get_world_repo().get()
    if not isinstance(bible, dict) or not bible:
        return "世界观尚未构建，请先 construct_world。"
    args = RefineWorldArgs(
        tone=tone, background=background,
        factions=factions, geography=geography, races=races,
        power_system=power_system, core_themes=core_themes,
    )
    merged = args.to_bible()
    try:
        get_world_repo().save(merged)
    except OSError as exc:
        return f"写盘失败：{exc}"
    # Always writes the full bible (factions/geography/races/power_system included every call) --
    # the process-level entity vocab cache (entity_index.py) must be invalidated so recall picks
    # up any new/renamed named entries on the very next sandbox turn, not just after a novel
    # switch or restart.
    from engine.memory_recall.entity_index import invalidate_entity_vocab_cache
    from engine.setup_chat.world_background_review import schedule_world_quality_review

    invalidate_entity_vocab_cache()
    schedule_world_quality_review(complete=True)
    return format_tool_done("已更新世界观。", render_world_chat(merged))


def _name_key(c: dict) -> str:
    return str(c.get("name") or c.get("given_name") or "").strip()


def _dump_sliders(sliders: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """args_schema 校验后拿到的是 dict[str, SliderInitArgs]（langchain 不会自动 dump 嵌套 model）；
    落盘前转成普通 dict，否则 json.dump 会报 SliderInitArgs not JSON serializable。"""
    return {
        k: (v.model_dump() if hasattr(v, "model_dump") else v)
        for k, v in (sliders or {}).items()
    }


def _build_character_dict(
    given_name: str,
    role: str,
    gender: str,
    race: str,
    causal_anchors: dict[str, str],
    physique: dict[str, str],
    clothing_color_palette: list[str],
    clothing_materials: list[str],
    clothing_signature_outfit: str,
    clothing_accessories: list[str],
    sliders: dict[str, dict[str, Any]],
    identity_background: str,
    hobbies: list[str],
    verbal_tic: str,
    personality: str,
) -> dict[str, Any]:
    name = given_name
    return {
        "name": name, "given_name": name, "role": role, "gender": gender, "race": race,
        "causal_anchors": causal_anchors, "physique": physique,
        "clothing_dna": {
            "color_palette": clothing_color_palette,
            "materials_preference": clothing_materials,
            "signature_outfit": clothing_signature_outfit,
            "accessories": clothing_accessories,
        },
        "sliders": _dump_sliders(sliders),
        "identity_background": identity_background,
        "hobbies": hobbies,
        "verbal_tic": verbal_tic,
        "personality": personality,
    }


def _remaining_build_note(current_count: int, configured_count: int, unit: str) -> str:
    """逐个手动创建角色/章节时，提示离「流水线配置」面板设的目标数量还差多少——帮弱模型
    自行判断是否已建够,不用等用户数数。已达到或超过目标（如目标 8 人已建到第 9 人）不再提示。"""
    remaining = configured_count - current_count
    if remaining <= 0:
        return ""
    return f"\n（已建 {current_count}/{configured_count} {unit}，剩余 {remaining} {unit}待创建。）"


def _find_character_index(roster: list, lookup: str) -> int | None:
    for i, c in enumerate(roster):
        if not isinstance(c, dict):
            continue
        if c.get("name") == lookup or c.get("given_name") == lookup:
            return i
    return None


async def _add_character_core(
    given_name: str,
    role: str,
    gender: str,
    causal_anchors: dict[str, str],
    physique: dict[str, str],
    clothing_color_palette: list[str],
    clothing_materials: list[str],
    clothing_signature_outfit: str,
    clothing_accessories: list[str],
    sliders: dict[str, dict[str, Any]],
    personality: str,
    identity_background: str,
    race: str = "",
    hobbies: list[str] | None = None,
    verbal_tic: str = "",
    notify_chat: bool = True,
    **extra: Any,
) -> tuple[bool, str, dict[str, Any] | None]:
    from repositories import get_lore_repo
    hobbies = hobbies if hobbies is not None else []
    name = given_name

    char = _build_character_dict(
        given_name, role, gender, race,
        causal_anchors, physique, clothing_color_palette, clothing_materials,
        clothing_signature_outfit, clothing_accessories, sliders,
        identity_background, hobbies, verbal_tic, personality,
    )
    char.update(extra)

    prior_roster: list = []
    saved_count = 0
    async with _cast_write_lock:
        roster = get_lore_repo().list_raw()
        prior_roster = roster
        existing = [_name_key(c) for c in roster if isinstance(c, dict)]
        if name in existing:
            return False, f"角色「{name}」已存在，请换个名字。", None
        new_roster = [*roster, char]
        roster_errs = validate_character_edit(char, new_roster, strict_race_membership=False)
        if roster_errs:
            return False, "群像校验未通过，未写入：\n" + "\n".join(f"- {e}" for e in roster_errs), None
        try:
            get_lore_repo().save_all(new_roster)
        except OSError as exc:
            return False, f"写盘失败：{exc}", None
        saved_count = len(new_roster)

    from engine.memory_recall.entity_index import invalidate_entity_vocab_cache

    invalidate_entity_vocab_cache()

    from engine.setup_chat.character_background_review import schedule_character_quality_review

    schedule_character_quality_review(name, notify_chat=notify_chat)

    from engine.setup_chat.character_visual_tags import schedule_extract_visual_tags

    schedule_extract_visual_tags(name)

    if prior_roster:
        from engine.setup.cast.incremental_relationship import generate_edges_for_new_character

        task = asyncio.create_task(generate_edges_for_new_character(char, prior_roster))
        _pending_relationship_tasks.add(task)
        task.add_done_callback(_pending_relationship_tasks.discard)

    from engine.modes.author_loop_skill_prefs import (
        DEFAULT_AUTO_BUILD_CHARACTER_COUNT,
        load_dialogue_prefs,
    )
    target = load_dialogue_prefs().get("auto_build_character_count", DEFAULT_AUTO_BUILD_CHARACTER_COUNT)
    note = _remaining_build_note(saved_count, target, "人")
    return True, format_tool_done(f"已添加角色「{name}」。{note}", render_character_chat(char)), char


@tool(args_schema=_StaticCharacterFieldsArgs)  # placeholder -- build_agent() overwrites .args_schema per-build (see agent.py)
async def add_character(
    given_name: str,
    role: str,
    gender: str,
    causal_anchors: dict[str, str],
    physique: dict[str, str],
    clothing_color_palette: list[str],
    clothing_materials: list[str],
    clothing_signature_outfit: str,
    clothing_accessories: list[str],
    sliders: dict[str, dict[str, Any]],
    personality: str,
    identity_background: str,
    race: str = "",
    hobbies: list[str] | None = None,
    verbal_tic: str = "",
    **extra: Any,
) -> str:
    """新增一个角色并入 cast。主 agent 直接填全字段；校验由 args_schema 完成。
    本工具只查重+入册。**extra 收纳 hook 声明的自定义字段（哪些字段已注册见 args_schema）。
    成功时若在场角色数未达「流水线配置」面板设的目标人数（auto_build_character_count），
    返回文案会附带"剩余 N 人待创建"提示；已达标或超额则不提示。"""
    _ok, msg, _char = await _add_character_core(
        given_name, role, gender, causal_anchors, physique, clothing_color_palette,
        clothing_materials, clothing_signature_outfit, clothing_accessories, sliders,
        personality, identity_background, race, hobbies, verbal_tic,
        **extra,
    )
    return msg


async def _edit_character_core(
    name: str,
    given_name: str,
    role: str,
    gender: str,
    causal_anchors: dict[str, str],
    physique: dict[str, str],
    clothing_color_palette: list[str],
    clothing_materials: list[str],
    clothing_signature_outfit: str,
    clothing_accessories: list[str],
    sliders: dict[str, dict[str, Any]],
    personality: str,
    identity_background: str,
    race: str = "",
    hobbies: list[str] | None = None,
    verbal_tic: str = "",
    portrait_visual_tags: str | None = None,
    notify_chat: bool = True,
    **extra: Any,
) -> tuple[bool, str, dict[str, Any] | None]:
    from repositories import get_lore_repo
    hobbies = hobbies if hobbies is not None else []

    char = _build_character_dict(
        given_name, role, gender, race,
        causal_anchors, physique, clothing_color_palette, clothing_materials,
        clothing_signature_outfit, clothing_accessories, sliders,
        identity_background, hobbies, verbal_tic, personality,
    )
    char.update(extra)

    from utils.paths import active_novel_id

    from engine.setup_chat.character_background_review import cancel_active_character_fix

    await cancel_active_character_fix(active_novel_id(), name)

    visual_changed = False
    async with _cast_write_lock:
        roster = get_lore_repo().list_raw()
        if not roster:
            return False, "当前没有人物设定（cast 尚未构建）。", None
        idx = _find_character_index(roster, name)
        if idx is None:
            names = "、".join(
                str(c.get("name") or c.get("given_name") or "?") for c in roster if isinstance(c, dict)
            )
            return False, f"未找到角色「{name}」。现有角色：{names}", None

        new_name = given_name
        for i, c in enumerate(roster):
            if i == idx or not isinstance(c, dict):
                continue
            if _name_key(c) == new_name:
                return False, f"角色「{new_name}」已存在，请换个名字。", None

        old_char = roster[idx]
        visual_changed = (
            old_char.get("gender") != char.get("gender")
            or old_char.get("physique") != char.get("physique")
            or old_char.get("clothing_dna") != char.get("clothing_dna")
        )
        if portrait_visual_tags is not None:
            # Explicit manual override (e.g. the cast detail panel) -- appearance-field
            # changes in this same edit still win below via schedule_extract_visual_tags,
            # since a real appearance change makes any hand-typed tags stale.
            char["portrait_visual_tags"] = portrait_visual_tags.strip()
        elif not visual_changed and isinstance(old_char.get("portrait_visual_tags"), str):
            char["portrait_visual_tags"] = old_char["portrait_visual_tags"]

        roster[idx] = char
        roster_errs = validate_character_edit(char, roster, strict_race_membership=False)
        if roster_errs:
            return False, "群像校验未通过，未写入：\n" + "\n".join(f"- {e}" for e in roster_errs), None
        try:
            get_lore_repo().save_all(roster)
        except OSError as exc:
            return False, f"写盘失败：{exc}", None

    from engine.memory_recall.entity_index import invalidate_entity_vocab_cache

    invalidate_entity_vocab_cache()

    from engine.setup_chat.character_background_review import schedule_character_quality_review

    schedule_character_quality_review(given_name, notify_chat=notify_chat)

    if visual_changed:
        from engine.setup_chat.character_visual_tags import schedule_extract_visual_tags

        schedule_extract_visual_tags(given_name)

    from engine.archive.archive_view import delete_character_archives
    from engine.setup_chat.timeline_auto import schedule_timeline_cascade

    result = delete_character_archives(name)
    removed_stages = result["removed_stages"]
    removed_archives = result["deleted_chapters"]
    schedule_timeline_cascade(1, names=name, notify_chat=notify_chat)
    cleared_note = ""
    if removed_stages or removed_archives:
        cleared_note = (
            f"\n（角色底层字段已改，原角色档案已清空：{removed_stages} 条 stage delta、"
            f"{len(removed_archives)} 章 archive；需要重新调用 write_character_archive 逐章重构。）"
        )
    return True, format_tool_done(f"已更新角色「{name}」。" + cleared_note, render_character_chat(char)), char


@tool(args_schema=_EditCharacterPlaceholderArgs)  # placeholder -- build_agent() overwrites .args_schema per-build (see agent.py)
async def edit_character(
    name: str,
    given_name: str,
    role: str,
    gender: str,
    causal_anchors: dict[str, str],
    physique: dict[str, str],
    clothing_color_palette: list[str],
    clothing_materials: list[str],
    clothing_signature_outfit: str,
    clothing_accessories: list[str],
    sliders: dict[str, dict[str, Any]],
    personality: str,
    identity_background: str,
    race: str = "",
    hobbies: list[str] | None = None,
    verbal_tic: str = "",
    **extra: Any,
) -> str:
    """Change [an existing] character in cast. The main agent fills in the new settings; the verification is completed by args_schema. This tool only locates + checks for duplicates + places the order.
    Cast is a purely static original file before chapter construction (initial settings such as role, body shape, clothing DNA, causal anchor points, etc.);
    Do not dynamically adjust characters, relationships, or status based on the plot or chapter progress, unless the user explicitly requests to change the file itself.

    副作用：写入成功后会清空该角色已有的角色档案（character_timeline delta 全部 stage + 各章 resolved
    archive.json + 内存缓存），因为它们是基于改动前的底层字段（physique/causal_anchors 等）推演出来的，
    edit 之后就是脏数据。清空后需要重新调用 write_character_archive 逐章重新构造该角色的角色档案。"""
    _ok, msg, _char = await _edit_character_core(
        name, given_name, role, gender, causal_anchors, physique, clothing_color_palette,
        clothing_materials, clothing_signature_outfit, clothing_accessories, sliders,
        personality, identity_background, race, hobbies, verbal_tic,
        **extra,
    )
    return msg


async def _delete_chapter_core(chapter: int) -> tuple[bool, str, dict]:
    """Delete one chapter entirely: plot entry + manuscript/temp/archives on disk, then shift
    every later chapter down by one (mirror of insert_chapter). Only the deleted chapter's own
    roster gets rescheduled for re-derivation -- a later chapter's characters who never
    appeared in the deleted chapter keep their archive content untouched; they're only
    relabeled to their new chapter number by shift_chapters."""
    from repositories import get_plot_repo

    chapters = get_plot_repo().list_raw()
    if not any(isinstance(c, dict) and c.get("chapter") == chapter for c in chapters):
        return False, f"未找到第 {chapter} 章。", {}

    from engine.setup_chat.timeline_seed import _chapter_roster
    roster = _chapter_roster(chapter)

    from repositories import get_archive_repo
    get_archive_repo().evict_from(chapter)
    # timeline_snapshots rows for this exact chapter, across every character who appeared in
    # it: truncate_from(name, chapter) would also remove that character's LATER chapters,
    # which is wrong here (delete-then-shift must only clear the deleted chapter's own delta;
    # later chapters for the same character get relabeled by shift_chapters below, not wiped).
    import context.character_timeline as character_timeline
    for name in roster:
        for snap in character_timeline.load_timeline(name)["snapshots"]:
            if snap["chapter"] == chapter:
                character_timeline.remove_stage(name, chapter, snap["stage"])

    new_chapters = [c for c in chapters if not (isinstance(c, dict) and c.get("chapter") == chapter)]
    try:
        get_plot_repo().save_all(new_chapters)
    except OSError as exc:
        return False, f"写盘失败：{exc}", {}

    import shutil

    from utils.paths import get_chapter_dir

    cdir = get_chapter_dir(chapter)
    if os.path.isdir(cdir):
        shutil.rmtree(cdir)

    from engine.setup_chat.chapter_shift import ChapterBusyError, shift_chapters
    try:
        await shift_chapters(chapter + 1, -1)
    except ChapterBusyError as exc:
        return False, str(exc), {}

    if roster:
        from engine.setup_chat.timeline_auto import schedule_timeline_cascade
        schedule_timeline_cascade(chapter, names=roster)

    detail = {"chapter": chapter, "rescoped_characters": roster}
    msg = f"已删除第 {chapter} 章（大纲/骨架/正文/角色档案），后续章节已顺延前移一位。"
    if roster:
        msg += f" 涉及角色（{', '.join(roster)}）的后续档案将重新推演；未涉及的角色档案原样保留，仅坐标随行迁移。"
    return True, msg, detail


async def _delete_character_core(name: str) -> tuple[bool, str, dict]:
    """Remove a character card from cast, cascading to every chapter whose outline/beat text
    mentions them (scan_characters must run before the roster write below, since its vocab is
    built from the live lore roster -- deleting the character first would make the scan blind to
    their own name) and to every relationship-graph edge touching them."""
    from utils.paths import active_novel_id

    from engine.setup_chat.character_background_review import cancel_active_character_fix

    await cancel_active_character_fix(active_novel_id(), name)

    from repositories import get_lore_repo, get_plot_repo

    roster = get_lore_repo().list_raw()
    idx = _find_character_index(roster, name)
    if idx is None:
        return False, f"未找到角色「{name}」。", {}

    from engine.memory_recall.entity_index import scan_characters

    affected_chapters: list[int] = []
    for ch in get_plot_repo().list_raw():
        if not isinstance(ch, dict):
            continue
        text_parts: list[str] = []
        for st in ch.get("stages", []):
            if not isinstance(st, dict):
                continue
            text_parts.append(str(st.get("description") or ""))
            for b in st.get("beats", []) or []:
                if isinstance(b, dict):
                    text_parts.append(str(b.get("text") or ""))
        if name in scan_characters("\n".join(text_parts)):
            affected_chapters.append(ch["chapter"])

    deleted_chapters: list[int] = []
    # Highest-first so each delete's shift-down cannot renumber a still-pending target.
    for ch_num in sorted(affected_chapters, reverse=True):
        ok, _msg, _detail = await _delete_chapter_core(ch_num)
        if ok:
            deleted_chapters.append(ch_num)

    from engine.setup.cast.relationship_graph import edges_for_character, load_graph, remove_edge

    edges = edges_for_character(load_graph(), name)
    for e in edges:
        remove_edge(e["from"], e["to"])

    async with _cast_write_lock:
        fresh = get_lore_repo().list_raw()
        fresh_idx = _find_character_index(fresh, name)
        if fresh_idx is None:
            return False, f"未找到角色「{name}」。", {}
        new_roster = [c for i, c in enumerate(fresh) if i != fresh_idx]
        try:
            get_lore_repo().save_all(new_roster)
        except OSError as exc:
            return False, f"写盘失败：{exc}", {}

    from engine.archive.archive_view import delete_character_archives
    from engine.setup_chat.timeline_auto import schedule_timeline_cascade

    delete_character_archives(name)
    schedule_timeline_cascade(1, names=name)

    from engine.memory_recall.entity_index import invalidate_entity_vocab_cache

    invalidate_entity_vocab_cache()

    removed_edges = [f"{e['from']}→{e['to']}" for e in edges]
    detail = {
        "name": name,
        "deleted_chapters": deleted_chapters,
        "removed_edges": removed_edges,
    }
    msg = f"已删除角色「{name}」。"
    if deleted_chapters:
        msg += f" 因大纲/分拍提及该角色，连带删除章节：{'、'.join(f'第{c}章' for c in deleted_chapters)}。"
    if edges:
        msg += f" 清理关系边 {len(edges)} 条：{'、'.join(removed_edges)}。"
    return True, msg, detail


def _clear_skeleton(chapter: dict) -> dict:
    """剥掉各 stage 的分拍底稿（beats）：章纲一改，旧写作底稿基于旧走向即失效，须重扩。

    连遗留 skeleton 键一起清（防旧库残留被误当「已扩写」跳过重建）。"""
    for st in chapter.get("stages", []):
        if isinstance(st, dict):
            st.pop("beats", None)
            st.pop("skeleton", None)
    return chapter


def _clear_archives_from(from_chapter: int) -> str:
    """description 改动会让该章及以后所有角色的 rolling archive 变脏（后续章节的 archive 是基于本章
    resolve 出来的），复用手动删档同一套 delete_archives_from：该章及以后 archive.json + timeline delta
    全清，返回给 agent 的提示文案（无清空则返回空串）。"""
    from engine.archive.archive_view import delete_archives_from

    result = delete_archives_from(from_chapter)
    chapters = result["deleted"]["chapters"]
    characters = result["deleted"]["characters"]
    if not chapters:
        return ""
    from engine.setup_chat.plan_runner import record_invalidation

    record_invalidation([
        {"id": f"repair-tl-ch{c}", "kind": "timeline",
         "title": f"重建第{c}章角色档案", "params": {"chapter": c}}
        for c in chapters
    ])
    from engine.setup_chat.timeline_auto import schedule_timeline_cascade
    schedule_timeline_cascade(from_chapter)
    return (
        f"\n第 {from_chapter} 章及以后的角色档案已清空（{len(chapters)} 章、"
        f"{len(characters)} 个角色：{', '.join(characters)}）——需重新调用 write_character_archive "
        "逐章重构。"
    )


async def _generate_one_chapter_impl(
    chapter_index: int,
    title: str,
    core_xp: list[str],
    stages: list,
) -> tuple[bool, str]:
    from repositories import get_plot_repo
    chapters = get_plot_repo().list_raw()
    n = len(chapters)
    if chapter_index < 1 or chapter_index > n + 1:
        return False, (f"第 {chapter_index} 章无法写入：当前共 {n} 章，"
                        f"只能改第 1..{n} 章或追加第 {n + 1} 章。")
    args = GenerateOneChapterArgs.model_validate({
        "chapter_index": chapter_index, "title": title, "core_xp": core_xp, "stages": stages,
    })
    built_chapter = args.to_chapter(chapter_index)

    from engine.setup_chat.tool_args import load_plot_grounding, validate_plot_chapters
    g = load_plot_grounding()
    errs = validate_plot_chapters([built_chapter], character_names=g.get("character_names", []))
    if errs:
        return False, "校验未通过，未写入：\n" + "\n".join(f"- {e}" for e in errs)

    replacing = chapter_index != n + 1
    if replacing:
        from utils.paths import active_novel_id

        from engine.setup_chat.skeleton_background_review import cancel_active_review

        await cancel_active_review(active_novel_id(), chapter_index, restarting=False)

    chapter = _clear_skeleton(built_chapter)
    if replacing:
        chapters[chapter_index - 1] = chapter
    else:
        chapters.append(chapter)
    try:
        get_plot_repo().save_all(chapters)
    except OSError as exc:
        return False, f"写盘失败：{exc}"
    verb = "更新" if replacing else "追加"
    tail = (
        "\n该章分拍底稿（beats）已重置——请重新讨论本章骨架并用 read_skeleton_seed → write_chapter_skeleton 重建后再写作。"
        if replacing else
        "\n新章尚无分拍底稿——写作前请先扩写骨架（read_skeleton_seed → write_chapter_skeleton）。"
    )
    #整章替换无法逐段 diff description，无条件清该章及以后 archive/timeline（新增章节尚未构建，天然 no-op）。
    tail += _clear_archives_from(chapter_index) if replacing else ""
    if not replacing:
        from engine.setup_chat.timeline_auto import schedule_timeline_cascade
        from engine.setup_chat.timeline_seed import _chapter_roster
        schedule_timeline_cascade(chapter_index, names=_chapter_roster(chapter_index))
        from engine.modes.author_loop_skill_prefs import (
            DEFAULT_AUTO_BUILD_CHAPTER_COUNT,
            load_dialogue_prefs,
        )
        target = load_dialogue_prefs().get("auto_build_chapter_count", DEFAULT_AUTO_BUILD_CHAPTER_COUNT)
        tail += _remaining_build_note(len(chapters), target, "章")
    return True, format_tool_done(
        f"已{verb}第 {chapter_index} 章。{tail}", render_chapter_chat(chapter, chapter_index))


@tool(args_schema=GenerateOneChapterArgs)
async def generate_one_chapter(
    chapter_index: int,
    title: str,
    core_xp: list[str],
    stages: list,
) -> str:
    """
Write/replace the [Chapter Outline] of a certain chapter (complete chapter: title/core_xp/stages, stages is required). Upsert by chapter number:
    1. Chapter number = replace the chapter, chapter number + 1 = append, if the number is skipped, an error will be reported. Verification is done by args_schema.
    ⚠ Use this tool only when creating a new chapter or rearranging a whole chapter; you only want to change the fields of certain paragraphs in an existing chapter (description/skeleton, etc.)
    Or add or delete individual stages, use patch_chapter to make partial changes. Do not rewrite the entire chapter just to change one place.

    ⚠ 重写章纲会清掉该章已扩的分拍底稿（beats 基于旧 description，章纲一改即失效）：
    替换既有章后须和用户重新讨论本章骨架，read_skeleton_seed → write_chapter_skeleton 重建
    分拍底稿后才能进写作。新增章天然无 beats，同样先扩再写。

    追加新章成功且总章数未达「流水线配置」面板设的目标章数（auto_build_chapter_count）时，
    返回文案会附带"剩余 N 章待创建"提示；替换既有章或已达标/超额则不提示。"""
    _ok, msg = await _generate_one_chapter_impl(chapter_index, title, core_xp, stages)
    return msg


@tool(args_schema=InsertChapterArgs)
async def insert_chapter(
    after_chapter: int,
    title: str,
    core_xp: list[str],
    stages: list,
) -> str:
    """在第 after_chapter 章之后插入一个全新章节（after_chapter=0 表示插到全书最前面），后面
    每一章的章号自动 +1（大纲/角色档案/正文/沙盒记录/磁盘目录全部随行）。跟 generate_one_chapter
    不同：这个工具只会新增章节，绝不会替换已有章节的内容。挪号是纯机械操作，不产生任何 LLM
    调用；只有新插入这一章里实际出场的角色，才会被排队重新推演角色档案——没在这章出现过的角色，
    档案原样保留，只是坐标随行搬迁。"""
    from repositories import get_plot_repo

    from engine.setup_chat.chapter_shift import ChapterBusyError, shift_chapters
    from engine.setup_chat.timeline_auto import schedule_timeline_cascade
    from engine.setup_chat.timeline_seed import _chapter_roster
    from engine.setup_chat.tool_args import load_plot_grounding, validate_plot_chapters

    new_chapter_index = after_chapter + 1
    args = InsertChapterArgs.model_validate({
        "after_chapter": after_chapter, "title": title, "core_xp": core_xp, "stages": stages,
    })
    built_chapter = args.to_chapter(new_chapter_index)

    g = load_plot_grounding()
    errs = validate_plot_chapters([built_chapter], character_names=g.get("character_names", []))
    if errs:
        return "校验未通过，未写入：\n" + "\n".join(f"- {e}" for e in errs)

    try:
        await shift_chapters(new_chapter_index, 1)
    except ChapterBusyError as exc:
        return str(exc)

    chapter = _clear_skeleton(built_chapter)
    chapters = get_plot_repo().list_raw()
    chapters.append(chapter)
    try:
        get_plot_repo().save_all(chapters)
    except OSError as exc:
        return f"写盘失败：{exc}"

    roster = _chapter_roster(new_chapter_index)
    schedule_timeline_cascade(new_chapter_index, names=roster)

    tail = "\n新章尚无分拍底稿——写作前请先扩写骨架（read_skeleton_seed → write_chapter_skeleton）。"
    if roster:
        tail += f"\n涉及角色（{', '.join(roster)}）的后续已构建章节档案将重新推演；未涉及的角色档案原样保留。"
    return format_tool_done(
        f"已插入第 {new_chapter_index} 章，原第 {new_chapter_index}..{new_chapter_index + len(chapters) - 1} "
        f"章及以后依次顺延一位。{tail}",
        render_chapter_chat(chapter, new_chapter_index),
    )


@tool(args_schema=AutoBuildSetupArgs)
async def auto_build_setup(brief: str) -> str:
    """AUTO 模式专用：小说完全空白时一次性建完世界观+角色+剧情，不逐步等待确认。手动模式或
    小说已有部分设定时，这个工具不会出现在可选工具里（tool_router 收窄 + gate_tool_call
    双重防御），别在其它场景调用它。人数/章节数由「对话」配置面板控制（不再是 LLM 自己决定的
    参数），见 author_loop_skill_prefs.load_dialogue_prefs()。"""
    import time

    from domain.token_usage import extract_usage
    from langchain_core.messages import HumanMessage, SystemMessage
    from llm.factory import get_cloud_llm
    from llm.prompt_logger import PromptLogger

    from engine.modes.author_loop_skill_prefs import (
        load_dialogue_prefs,
        node_llm_sampling_kwargs,
        resolve_node_base_llm,
    )
    from engine.setup_chat.auto_construct import run_auto_build

    prefs = load_dialogue_prefs()
    character_count = prefs["auto_build_character_count"]
    chapter_count = prefs["auto_build_chapter_count"]

    #Every sub-call in run_auto_build (build_world/plan_character_outline/build_characters/
    #build_chapters) shares this one call_llm closure, so binding once here covers all of
    #them uniformly -- unlike chapter_review.py's _review_llm which binds per-call. Split
    #into resolve_node_base_llm + node_llm_sampling_kwargs (what bind_node_llm does
    #internally) instead of calling bind_node_llm directly so model_name below is read off
    #the pre-sampling-bind model -- a configured sampling override wraps it in a
    #RunnableBinding, whose .model/.model_name would otherwise read as empty.
    import_params = prefs["import_llm_params"]
    base_llm = resolve_node_base_llm(get_cloud_llm(), "auto_build_setup", import_params)
    model_name = str(getattr(base_llm, "model", "") or getattr(base_llm, "model_name", "") or "cloud")
    sampling = node_llm_sampling_kwargs(base_llm, "auto_build_setup", import_params)
    llm = base_llm.bind(**sampling) if sampling else base_llm
    #chapter=0 sentinel -- this tool's calls draft world/characters/chapters from scratch, not
    #tied to any single already-existing chapter (matches the chapter_000 convention other
    #non-chapter-specific engine calls already use in logs/engine_server/).
    prompt_logger = PromptLogger(0)
    step = 0

    async def call_llm(system: str, user: str) -> str:
        nonlocal step
        step += 1
        t0 = time.monotonic()
        resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        content = resp.content if hasattr(resp, "content") else str(resp)
        text = content if isinstance(content, str) else str(content)
        tin, tout, tcached = extract_usage(resp)
        prompt_logger.log_llm_call(
            step=step, agent="auto_build_setup", model=model_name,
            system=system, user=user, response=text,
            tokens_in=tin, tokens_out=tout, tokens_cached=tcached,
            duration_s=time.monotonic() - t0,
        )
        return text

    try:
        return await run_auto_build(brief, character_count, chapter_count, call_llm)
    finally:
        prompt_logger.close()


def _apply_stage_ops(
    work_stages: list[dict], ops: list
) -> tuple[list[dict], list[int], list[int]]:
    """
Rebuild the stages according to ops (positioned according to the original number) and rearrange 1..N, return (new list, original segment number of the cleared skeleton, final stage_num of content-touched stages).

    replace changes the field in place (the description is changed and the new skeleton is not given at the same time → the old skeleton becomes invalid and cleared);
    add inserts according to after_stage_num (0=front); remove marks deletion. The whole process is positioned according to the [original] number, and the end is rearranged uniformly.
    Therefore, multiple operations in the same batch are not interfered with by rearrangements. The input parameter work_stages should be a copy (the original data will not be polluted in case of failure).

    `touched`: final (post-renumber) stage_num of any stage whose beat content
    changed (replace-with-beats/replace_beat) or whose immediate original
    neighbor was removed (may become newly adjacent) -- candidates for
    patch_chapter's scoped review (run_stage_local_review), tracked by dict
    object identity so renumbering/removal don't need separate bookkeeping."""

    from engine.setup_chat.tool_args import PatchOp as _Op

    by_num = {s["stage_num"]: s for s in work_stages if isinstance(s, dict)}
    ordered_orig = sorted((s for s in work_stages if isinstance(s, dict)),
                          key=lambda s: s.get("stage_num", 0))
    orig_index = {s["stage_num"]: idx for idx, s in enumerate(ordered_orig)}
    removed: set[int] = set()
    cleared: list[int] = []
    adds_by_after: dict[int, list[dict]] = {}
    touched_objs: list[dict] = []
    for op in ops:
        if op.op == _Op.REPLACE and op.stage_num is not None and op.fields is not None:
            st = by_num[op.stage_num]
            patch = op.fields.applied()
            if ("description" in patch and "beats" not in patch
                    and patch["description"] != st.get("description")):
                st.pop("beats", None)
                st.pop("skeleton", None)
                cleared.append(op.stage_num)
            else:
                touched_objs.append(st)
            st.update(patch)
        elif op.op == _Op.REPLACE_BEAT and op.stage_num is not None and op.beat is not None:
            #预检（patch_chapter 里）已保证 beats 存在且 beat_idx 界内，这里直接整拍替换
            st = by_num[op.stage_num]
            st["beats"][op.beat_idx] = op.beat.model_dump()
            touched_objs.append(st)
        elif op.op == _Op.SET_BEAT_DIALOGUE and op.stage_num is not None and op.beat_idx is not None:
            #单字段局部更新，不加入 touched_objs——跟改叙事内容的 replace_beat/replace 不同，
            #不该触发保真/过渡审查
            st = by_num[op.stage_num]
            st["beats"][op.beat_idx]["dialogue_draft"] = op.dialogue_draft
        elif op.op == _Op.REMOVE and op.stage_num is not None:
            removed.add(op.stage_num)
            idx = orig_index.get(op.stage_num)
            if idx is not None:
                if idx > 0:
                    touched_objs.append(ordered_orig[idx - 1])
                if idx + 1 < len(ordered_orig):
                    touched_objs.append(ordered_orig[idx + 1])
        elif op.op == _Op.ADD and op.stage is not None and op.after_stage_num is not None:
            new_stage_dict = op.stage.model_dump()
            adds_by_after.setdefault(op.after_stage_num, []).append(new_stage_dict)

    new_stages: list[dict] = [*adds_by_after.get(0, [])]
    for s in work_stages:
        if not isinstance(s, dict):
            continue
        sid = s.get("stage_num")
        if sid in removed:
            continue
        new_stages.append(s)
        if isinstance(sid, int):
            new_stages.extend(adds_by_after.get(sid, []))
    for i, s in enumerate(new_stages, 1):
        s["stage_num"] = i

    still_present = {id(s) for s in new_stages}
    touched = sorted({s["stage_num"] for s in touched_objs if id(s) in still_present})
    return new_stages, cleared, touched


async def _fill_dialogue_drafts(
    chapter: int, by_num: dict[int, dict], generated: dict[int, list[dict]],
) -> None:
    """并发为 generated 里每一拍起草联合台词（见 dialogue_draft.draft_beat_dialogue），原地写回
    每个 beat dict 的 dialogue_draft 键。prev_text 取本 stage 内上一拍（同批次已生成）；若是本
    stage 首拍则取上一段最后一拍——优先从 generated（本次调用同批次重扩的段）取，否则退回磁盘上
    已有的段（_stage_beats），都没有则空字符串（本章第一段第一拍，没有最近上下文）。"""
    from loguru import logger
    from utils.timer import setup_chat_step_timer

    from engine.setup_chat import dialogue_draft
    from engine.setup_chat.construction_plan import _stage_beats

    tasks = [
        (stage_num, beat_idx)
        for stage_num, beats in generated.items()
        for beat_idx in range(len(beats))
    ]
    batch_meta = {
        "chapter": chapter,
        "beat_count": len(tasks),
        "stage_nums": sorted(generated),
        "concurrency": len(tasks),
    }

    from engine.memory_recall.entity_index import scan_characters

    async def _one(stage_num: int, beat_idx: int) -> tuple[int, int, str]:
        t0 = time.perf_counter()
        beats = generated[stage_num]
        # plot stage no longer persists `characters` (see 2026-07-31 elimination); derive the
        # same roster stages_to_segments / skeleton_seed use for author_loop consumption.
        characters = scan_characters(str(by_num[stage_num].get("description") or ""))
        if beat_idx > 0:
            prev_text = str(beats[beat_idx - 1].get("text") or "")
        else:
            prev_stage_beats = generated.get(stage_num - 1) or _stage_beats(chapter, stage_num - 1) or []
            prev_text = str(prev_stage_beats[-1].get("text") or "") if prev_stage_beats else ""
        draft = await dialogue_draft.draft_beat_dialogue(
            chapter, stage_num, str(beats[beat_idx].get("text") or ""), characters, prev_text,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "[setup_chat_perf] fill_dialogue_drafts beat done | elapsed_ms={:.2f} | "
            "chapter={} stage_num={} beat_idx={} draft_chars={}",
            elapsed_ms, chapter, stage_num, beat_idx, len(draft),
        )
        return stage_num, beat_idx, draft

    async with setup_chat_step_timer("fill_dialogue_drafts", extra_meta=batch_meta):
        results = await asyncio.gather(*(_one(sn, bi) for sn, bi in tasks))
    for stage_num, beat_idx, draft in results:
        generated[stage_num][beat_idx]["dialogue_draft"] = draft


async def _patch_chapter_core(
    chapter: int,
    ops: list,
    core_xp: list[str] | None = None,
    *,
    run_review: bool = True,
    is_reviewed: bool = False,
) -> tuple[bool, str]:
    from utils.paths import active_novel_id

    from engine.setup_chat.skeleton_background_review import cancel_active_review

    novel_id = active_novel_id()
    await cancel_active_review(novel_id, chapter)

    import copy

    from repositories import get_plot_repo

    from engine.setup_chat.tool_args import (
        PatchChapterArgs as _Args,
    )
    from engine.setup_chat.tool_args import (
        load_plot_grounding,
        validate_plot_chapters,
    )

    chapters = get_plot_repo().list_raw()
    ch = next((c for c in chapters if isinstance(c, dict) and c.get("chapter") == chapter), None)
    if ch is None:
        return False, f"第 {chapter} 章不存在于 plot（请先写本章 plot）。"
    args = _Args.model_validate({"chapter": chapter, "ops": ops, "core_xp": core_xp})

    orig_stages = [s for s in (ch.get("stages") or []) if isinstance(s, dict)]
    nums: set[int] = {s["stage_num"] for s in orig_stages if isinstance(s.get("stage_num"), int)}
    n = len(orig_stages)
    for op in args.ops:
        if (
            op.op in (PatchOp.REPLACE, PatchOp.REMOVE, PatchOp.REPLACE_BEAT, PatchOp.SET_BEAT_DIALOGUE)
            and op.stage_num not in nums
        ):
            return False, f"第 {chapter} 章无 stage {op.stage_num}（现有：{sorted(nums)}）。"
        if op.op == PatchOp.ADD and op.after_stage_num is not None and not (0 <= op.after_stage_num <= n):
            return False, f"add 的 after_stage_num={op.after_stage_num} 越界（应在 0..{n}）。"
        if op.op in (PatchOp.REPLACE_BEAT, PatchOp.SET_BEAT_DIALOGUE):
            st0 = next(s for s in orig_stages if s.get("stage_num") == op.stage_num)
            bl = st0.get("beats")
            if not isinstance(bl, list) or not bl:
                action = "replace_beat" if op.op == PatchOp.REPLACE_BEAT else "set_beat_dialogue"
                return (False, f"stage {op.stage_num} 尚未分拍扩写，无法 {action}"
                        "（先 skeleton-expansion）。")
            if not (0 <= (op.beat_idx or 0) < len(bl)):
                return False, f"stage {op.stage_num} 无拍 {op.beat_idx}（现有 0..{len(bl) - 1}）。"

    #Make changes + verification on the copy and submit it only after passing - the original plot (memory and disk) will not be contaminated when it fails.
    new_stages, cleared, touched = _apply_stage_ops(
        copy.deepcopy(orig_stages), args.ops
    )
    if not new_stages:
        return False, "操作后本章无 stage（至少需保留 1 个 stage），未写入。"

    candidate = {**ch, "stages": new_stages}
    if args.core_xp is not None:
        candidate["core_xp"] = args.core_xp
    g = load_plot_grounding()
    errs = validate_plot_chapters([candidate], character_names=g.get("character_names", []))
    if errs:
        return False, "校验未通过，未写入：\n" + "\n".join(f"- {e}" for e in errs)

    ch["stages"] = new_stages
    if args.core_xp is not None:
        ch["core_xp"] = args.core_xp
    try:
        get_plot_repo().save_all(chapters)
    except OSError as exc:
        return False, f"写盘失败：{exc}"
    #无条件补一次级联调度，不只在 cleared（description 改动）时——add/remove/replace_beat 这些不
    #触发 cleared 的 op 也可能改变本章在场角色（如 add 插入带新角色的 stage），missing_timeline_
    #targets 是按当前 roster 现算的（自愈式，见 timeline_auto.py 模块 docstring），所以这里重复
    #调度是安全的：cleared 分支下面 _clear_archives_from 已经调度过一次，SCHEDULER.schedule_once
    #的 dedup=True 会把这次去重掉，不会重复执行。
    from engine.setup_chat.timeline_auto import schedule_timeline_cascade
    from engine.setup_chat.timeline_seed import _chapter_roster
    schedule_timeline_cascade(chapter, names=_chapter_roster(chapter))

    if cleared:
        from engine.setup_chat.chapter_review import set_chapter_skeleton_reviewed

        set_chapter_skeleton_reviewed(chapter, False)

    from engine.setup_chat.chapter_review import maybe_schedule_skeleton_chapter_review

    await maybe_schedule_skeleton_chapter_review(
        chapter, new_stages,
        is_reviewed=is_reviewed,
        invalidate_reviewed=not is_reviewed,
    )

    note = (
        f"\n段 {sorted(cleared)} 的 description 已改、对应分拍底稿（beats）已失效——"
        "需重新扩写（read_skeleton_seed → write_chapter_skeleton）。"
        if cleared else ""
    )
    if cleared:
        from engine.setup_chat.plan_runner import (
            pending_invalidation_note,
            record_invalidation,
        )

        repair: list[dict] = []
        for sn in sorted(cleared):
            repair.append({"id": f"repair-skel-ch{chapter}-s{sn}", "kind": "skeleton_stage",
                           "title": f"重扩第{chapter}章 stage{sn} 骨架",
                           "params": {"chapter": chapter, "stage_num": sn}})
        record_invalidation(repair)
        note += _clear_archives_from(chapter)
        note += pending_invalidation_note()

    if touched and run_review:
        from engine.setup_chat.chapter_review import (
            StageReview,
            TransitionReview,
            render_chapter_review_report,
            run_stage_local_review,
        )

        results = await asyncio.gather(*(
            run_stage_local_review(new_stages, sn) for sn in touched
        ))
        seen_transitions: dict[tuple[int, int], TransitionReview] = {}
        seen_stages: dict[int, StageReview] = {}
        for transitions, stage_reviews in results:
            for tr in transitions:
                seen_transitions[(tr.from_stage, tr.to_stage)] = tr
            for sr in stage_reviews:
                seen_stages[sr.stage_num] = sr
        review_report = render_chapter_review_report(
            sorted(seen_transitions.values(), key=lambda t: (t.from_stage, t.to_stage)),
            sorted(seen_stages.values(), key=lambda s: s.stage_num),
        )
        if review_report:
            note += f"\n{review_report}"

    core_xp_note = "，题材基调已替换" if args.core_xp is not None else ""
    return True, format_tool_done(
        f"已局部更新第 {chapter} 章（{len(args.ops)} 项操作{core_xp_note}）。{note}",
        render_chapter_chat(ch, chapter),
    )


@tool(args_schema=PatchChapterArgs)
async def patch_chapter(
    chapter: int, ops: list, core_xp: list[str] | None = None, is_reviewed: bool = False,
) -> str:
    """
局部编辑某章，不必为改一处重投整章。ops 有序，stage 号均指调用时的当前编号：
    - replace: {op, stage_num, fields}，只改 fields 给的字段（description/beats/characters…），
      未给字段与其它段不动；改 description 而不同时给新 beats → 该段分拍底稿失效被清、需重扩。
    - replace_beat: {op, stage_num, beat_idx, beat:{text}}，整拍替换该段第 beat_idx 拍
      （0 起）；只想微调局部用 patch_text_fragment 手术式替换，别为改几个字整拍重写。
    - add: {op, after_stage_num, stage}，在某段后插完整新段（after_stage_num=0 插到最前）。
    - remove: {op, stage_num}，删一段。
    add/remove 后自动重排 stage_num（1..N 不跳号）。core_xp 是章级字段（可选）：给了就整章
    替换本章核心体验/题材基调，不给不动；ops 和 core_xp 至少给一个，都不给会报错。
    整章校验通过才写盘，失败整批不写。内容变化涉及的段（replace 给了新 beats /
    replace_beat / remove 后新形成的相邻对）会自动做一次局部审查（只查这几段+邻段过渡，
    不是整章重查），结果附在返回文本里。按后台审查通知改骨架时设 is_reviewed=true，
    写盘后不再触发全章过渡/文风审查（每章审查周期只允许这一次终稿修正）。"""
    _ok, msg = await _patch_chapter_core(
        chapter, ops, core_xp, run_review=True, is_reviewed=is_reviewed,
    )
    return msg


@tool(args_schema=PresentChoicesArgs)
def present_choices(question: str, options: list[str], recommended: str) -> str:
    """
It needs to be called when the user checks a discrete option (the front end will render it as a checkable option + confirmation).
    After the call, the current round ends here, waiting for the user to make a selection; do not let the user type in the text column 1/2/3.
    `recommended` must be filled even in manual mode (ignored there) -- in AUTO mode it is
    what gets picked instead of waiting for the user."""
    from engine.setup_chat.mode import is_auto_mode

    if not is_auto_mode():
        return f"已向用户展示 {len(options)} 个选项，等待其勾选确认。本轮到此结束。"
    picked = recommended if recommended in options else options[0]
    return f"已自动选定「{picked}」（AUTO 模式，无需等待用户确认，请直接继续）。"


@tool(args_schema=RenameNovelTitleArgs)
def rename_novel_title(new_title: str) -> str:
    """将当前小说的标题改为 new_title（只改 novel.json 的 name 字段，目录/id 不变）。
    仅在用户已通过 present_choices 明确同意后调用，不要单方面直接改，也不要没有明确理由
    地随意提议。"""
    from api.services.novels import rename_novel
    from utils.paths import active_novel_id

    new_title = new_title.strip()
    if not new_title:
        return "标题不能为空，未修改。"
    rename_novel(active_novel_id(), new_title)
    return f"已将小说标题改为「{new_title}」。"


@tool(args_schema=LoadSkillArgs)
def load_skill(name: str) -> str:
    """
Load the complete content of the guidance skills by name (such as worldview dimension-by-dimension interview guidance).
    Before starting a certain type of construction/refinement, first adjust the tool for guidance according to the skill index of the system prompt, and then strictly follow it."""
    from engine.setup_chat.skills import (
        expand_skill_placeholders,
        list_skill_index,
        load_skill_body,
        setup_chat_skill_dirs,
    )

    dirs = setup_chat_skill_dirs()
    body = load_skill_body(name, dirs)
    if body is None:
        names = "、".join(s["name"] for s in list_skill_index(dirs)) or "（无）"
        return f"未找到技能「{name}」。可用技能：{names}"
    return expand_skill_placeholders(body, dirs)


def _persist_archive(name: str, chapter: int, archive: dict) -> None:
    """Download the parsed file + update the memory index (extracted for monkeypatch testing).

    Place it in chapters/chapterN/characters/{name}_chNN_archive.json (same path as the old builder) - archive page overview,
    Delete, rebuild, and indexer preload all read these files; if only the memory cache is updated without writing to disk, the process will be lost and the page will not see the role."""

    from repositories import get_archive_repo

    get_archive_repo().save(name, chapter, archive)


def _resolve_archive(name: str, chapter: int) -> dict:
    """Fold the completed delta timeline into this chapter's full profile: lore static/identity
    fields and the resolved evolving fields (sliders/gender/physique/personality/...) sit flat,
    side by side, on one top-level dict -- no per-stage nesting. write_character_archive always
    appends at stage=1 (one profile per chapter, see _delta_allowed_fields/append_stage below), so
    resolving at stage=1 is exactly this chapter's one snapshot; resolve_from's coordinate folding
    naturally ignores any stray stage>1 snapshot left over from the old per-stage regime."""
    from context import character_timeline
    from context.character_resolver import resolve_from

    from engine.archive.archive_fields import _STAGE_BOUND_FIELDS
    from engine.archive.hook_loader import collect_merge_strategies
    from engine.setup_chat.timeline_seed import _char_lore

    lore = _char_lore(name)
    strategies = collect_merge_strategies()
    snaps = character_timeline.load_timeline(name)["snapshots"]
    archive: dict = {k: v for k, v in lore.items()
                     if k not in _STAGE_BOUND_FIELDS and k != "personality"}
    archive.setdefault("extensions", {})
    #These are the top level identity/base fields (name/role/causal_anchors/race/given_name…) + base
    #dress preferences; resolve_from starts from the entire lore (including lore's own "sliders"
    #baseline, already excluded above via _STAGE_BOUND_FIELDS), so the stage-resolved state carries
    #them forward -- peeled off here, leaving only the evolved state.
    _identity_keys = {k for k in lore if k not in _STAGE_BOUND_FIELDS
                      and k not in ("personality", "hobbies", "verbal_tic")} | {
        "clothing_dna"}
    resolved = resolve_from(lore, snaps, chapter, 1, strategies)
    entry = {k: v for k, v in resolved.items() if k not in _identity_keys}
    archive.update(entry)
    return archive


#The set of fields allowed by delta (stage fields that will be consumed downstream): All other self-made keys will be stripped off to prevent drift.
#Streamlined: removed thought_process (pure build reasoning, no one consumes, overlaps with state.psychology), phase_name
#(dead old marker), location (automatically filled in by plot, not written by agent); structured tracking of collapse degree is still carried by sliders.
_CORE_DELTA_FIELDS = frozenset({
    "sliders", "gender", "physique", "race", "identity_background",
    "address_ref", "self_ref", "personality", "verbal_tic", "hobbies",
})


def _delta_allowed_fields() -> frozenset[str]:
    """核心 delta 字段 + 已激活内容包里 timeline_delta=True 的自定义字段。"""
    from context.content_packs import custom_fields
    extra = frozenset(spec.name for spec in custom_fields() if spec.timeline_delta)
    return _CORE_DELTA_FIELDS | extra


def _normalize_delta(delta: dict) -> tuple[dict, list[str]]:
    """规范化 agent 产出的 delta：白名单字段 + self_ref/address_ref 收拢 per-target dict +
    sliders 形态校验（{"level":int,"text":str}，D1；旧形态裸字符串/缺字段 → 整个 sliders 丢弃，
    计入 dropped，逼 agent 按新形态重发，而非静默接受判不出档位的散文）。
    返回 (规范化后的 delta, 被剥掉的槽外键列表)。"""

    from context.dialogue.scene_aware import as_target_pool_map

    from engine.archive.sliders import valid_slider_value_shape

    raw = dict(delta or {})

    out: dict = {}
    dropped: list[str] = []
    for k, v in raw.items():
        if k not in _delta_allowed_fields():
            dropped.append(k)
            continue
        if k in ("self_ref", "address_ref"):
            out[k] = as_target_pool_map(
                v, legacy_default_key="_default" if k == "self_ref" else None
            )
        elif k == "sliders":
            if valid_slider_value_shape(v):
                out[k] = v
            else:
                dropped.append(k)
        elif k == "hobbies":
            if isinstance(v, list):
                out[k] = [str(x).strip() for x in v if str(x).strip()]
            else:
                dropped.append(k)
        else:
            out[k] = v
    return out, dropped


def _write_timeline_delta(chapter: int, name: str, profile: dict) -> dict | str:
    """Normalize + validate + persist + resolve one character's chapter delta. Returns the
    resolved archive dict on success, or a human-readable rejection string on validation
    failure (empty personality / out-of-range slider level / schema violation). Shared by
    write_character_archive (agent-facing refine tool) and timeline_auto's automatic
    background derivation -- extracted so both paths validate/persist identically."""
    from context import character_timeline

    from engine.archive.archive_view import (
        render_archive_summary,  # noqa: F401 -- re-exported via caller
    )
    from engine.archive.sliders import character_rubrics, valid_levels

    rubrics = character_rubrics(name)
    from repositories import get_lore_repo
    if get_lore_repo().get_character(name) is None:
        return f"角色「{name}」不在花名册中，请先用 add_character 建档，或检查名字是否有误。未写入。"
    nd, dropped = _normalize_delta(profile or {})

    pers = nd.get("personality")
    if "personality" in nd and (not isinstance(pers, str) or not str(pers).strip()):
        return "personality 须为非空散文描述。未写入，请改正后重发。"

    bad_level: list[str] = []
    for axis, val in (nd.get("sliders") or {}).items():
        legal = valid_levels(rubrics, axis)
        level = val.get("level") if isinstance(val, dict) else None
        if legal and level is not None and int(level) not in legal:
            bad_level.append(f"{axis}={val['level']}（合法档位：{sorted(legal)}）")
    if bad_level:
        return "以下滑块档位越界：" + "、".join(bad_level) + "。未写入，请改正后重发。"

    # Capture the pre-call state at this exact coordinate so a validation failure below can be
    # rolled back -- append_stage must run before _resolve_archive can fold it in (resolve reads
    # committed timeline state from disk), but if assert_valid then rejects the result, leaving
    # the speculative delta committed would make missing_timeline_targets() permanently consider
    # this chapter already built (its check is timeline-presence-only) even though archive.json
    # was never persisted -- "一键构建" would report 0 missing forever with no way to retry.
    prev_stage = character_timeline.get_stage(name, chapter, 1)

    character_timeline.append_stage(name, chapter, 1, nd)
    archive = _resolve_archive(name, chapter)
    try:
        assert_valid(archive)
    except Exception as exc:  # noqa: BLE001 -- validation failure returns a readable message
        if prev_stage is not None:
            character_timeline.append_stage(name, chapter, 1, prev_stage["delta"])
        else:
            character_timeline.remove_stage(name, chapter, 1)
        return f"档案校验未通过：{exc}"
    _persist_archive(name, chapter, archive)
    return {"archive": archive, "dropped": dropped}


@tool(args_schema=WriteCharacterArchiveArgs)
async def write_character_archive(chapter: int, name: str, profile: dict) -> str:
    """写这一章角色的完整初始档案(整章一次，不再逐 stage 分批)：规范化(白名单字段 +
    self_ref/address_ref 收拢 per-target dict) → 校验(personality 非空、滑块档位合法) →
    落库(character_timeline 固定用 stage=1 存一条快照) → 折叠出完整档案 →
    落盘 → 返回摘要。
    sliders 每轴须给 {level, text}：level=合法档位号，text=贴合此刻的一句叙述。Unchanged fields are
    mechanically inherited by resolve and should not be completely rewritten；only fill in the
    fixed field set, do not create your own slots。
    verbal_tic（口癖）是可选宏观字段，跟 personality 同机制：人格没有转折就不必每章重填，只有说话
    习惯真的该变时才整句改写。
    hobbies（爱好）是可选列表字段，剧情导致兴趣变化时可整表替换（未给的章沿用前值，跟 verbal_tic
    一样 replace 语义）。
    race（种族）、identity_background（身份背景）现在也走这套宏观角色档案 delta 机制——种族转换/
    身份揭露没发生就不必每章重填，跟 personality/verbal_tic 同一套"没变就不提"的语义。
    这是精修工具：正常情况下章节的角色档案由引擎自动推演，只有需要手动修正细节时才调用本工具。"""
    from engine.archive.archive_view import render_archive_summary

    result = _write_timeline_delta(chapter, name, profile)
    if isinstance(result, str):
        return result
    archive, dropped = result["archive"], result["dropped"]
    from engine.setup_chat import world_pipeline
    world_pipeline.clear_timeline_active(chapter, name)
    summary = render_archive_summary(chapter, [{**archive, "name": name}])
    if dropped:
        summary += f"\n（已忽略槽外字段：{'、'.join(sorted(dropped))}——只收固定字段集，勿自造。）"
    return summary


@tool(args_schema=SetChapterDirectionArgs)
def set_chapter_direction(chapter: int, direction: str) -> str:
    """记录本章整体叙事走向（skeleton-expansion 第2步，章级一次）。skeleton_pipeline 的
    DIRECTION 阶段——没调用过这个，任何段的 set_stage_lens 都会被引擎拒绝。"""
    from engine.setup_chat import skeleton_pipeline

    skeleton_pipeline.set_chapter_direction(chapter, direction)
    return f"已记录第 {chapter} 章整体走向。"


@tool(args_schema=SetStageLensArgs)
def set_stage_lens(chapter: int, stage_num: int, angles: list[str]) -> str:
    """记录某段选定的分镜/突出角度（skeleton-expansion 3a 完成后必做）。skeleton_pipeline 的
    LENS 阶段——没调用过这个，set_stage_extensions 会被引擎拒绝。"""
    from engine.setup_chat import skeleton_pipeline

    skeleton_pipeline.set_stage_lens(chapter, stage_num, angles)
    return f"已记录第 {chapter} 章 stage {stage_num} 的分镜角度。"


@tool(args_schema=SetStageExtensionsArgs)
def set_stage_extensions(chapter: int, stage_num: int, extensions: list[str]) -> str:
    """记录某段选定的情景拓展（skeleton-expansion 3b 完成后必做，用户选"都不用"时传空列表）。
    skeleton_pipeline 的 EXTENSIONS 阶段——没调用过这个，write_chapter_skeleton 对该段的
    首次展开会被引擎拒绝。"""
    from engine.setup_chat import skeleton_pipeline

    skeleton_pipeline.set_stage_extensions(chapter, stage_num, extensions)
    return f"已记录第 {chapter} 章 stage {stage_num} 的情景拓展。"


@tool(args_schema=WriteChapterSkeletonArgs)
async def write_chapter_skeleton(
    chapter: int, stages: list, is_reviewed: bool = False,
) -> str:
    """内部生成本章各段的分拍写作底稿（粗大纲 description 不动）：不再接收现成拍文，接收每段的
    overview——首次展开=本段概述（补充 3a/3b 已记录的分镜/拓展之外的细节，可留空）；改这段（该
    stage 已有 beats）=修改意见，此时不可为空。按 stage_num 定位，逐段展开时每段调用一次；一次
    调用里每段各自独立发起一次内部生成，全部成功才落盘，任一段失败则整次调用不写盘，报错指出
    哪段失败，可重试。只改某一拍用 patch_chapter 的 replace_beat，别整段重写。本章全部 stage
    骨架都写完后，会自动并行审查相邻 stage 间的过渡，结果附在返回文本里。本章骨架全部写完后，
    告诉用户可以跳转到主笔页面执行正文创作。收到后台审查通知后按反馈改骨架时设 is_reviewed=true，
    写盘后不再触发全章过渡/文风审查（每章审查周期只允许这一次终稿修正）。"""

    args = WriteChapterSkeletonArgs.model_validate({
        "chapter": chapter, "stages": stages, "is_reviewed": is_reviewed,
    })

    from utils.paths import active_novel_id

    from engine.setup_chat.skeleton_background_review import cancel_active_review

    novel_id = active_novel_id()
    await cancel_active_review(novel_id, chapter)

    from repositories import get_plot_repo
    chapters = get_plot_repo().list_raw()
    ch = next((c for c in chapters if isinstance(c, dict) and c.get("chapter") == chapter), None)
    if ch is None:
        return f"第 {chapter} 章不存在于 plot，无法写骨架（请先写本章 plot）。"
    by_num = {s.get("stage_num"): s for s in ch.get("stages") or []}

    from loguru import logger
    from utils.timer import setup_chat_step_timer

    from engine.setup_chat import skeleton_pipeline, skeleton_writer

    stage_nums = [sa.stage_num for sa in args.stages]
    call_meta = {"chapter": chapter, "stage_nums": stage_nums, "is_reviewed": is_reviewed}
    t_call = time.perf_counter()

    generated: dict[int, list[dict]] = {}
    async with setup_chat_step_timer("write_chapter_skeleton", extra_meta=call_meta):
        for sa in args.stages:
            st = by_num.get(sa.stage_num)
            if st is None:
                return f"第 {chapter} 章无 stage {sa.stage_num}（现有：{sorted(by_num)}）。"
            is_revision = skeleton_pipeline._is_expanded(chapter, sa.stage_num)
            t_stage = time.perf_counter()
            result = await skeleton_writer.generate_stage_beats(
                chapter, sa.stage_num, overview=sa.overview, is_revision=is_revision,
            )
            stage_elapsed_ms = (time.perf_counter() - t_stage) * 1000
            if isinstance(result, str):
                logger.warning(
                    "[setup_chat_perf] write_chapter_skeleton stage failed | elapsed_ms={:.2f} | "
                    "chapter={} stage_num={} error={}",
                    stage_elapsed_ms, chapter, sa.stage_num, result,
                )
                return f"第 {chapter} 章 stage {sa.stage_num} 分拍生成失败：{result}"
            generated[sa.stage_num] = result
            logger.info(
                "[setup_chat_perf] write_chapter_skeleton stage done | elapsed_ms={:.2f} | "
                "chapter={} stage_num={} beat_count={} is_revision={}",
                stage_elapsed_ms, chapter, sa.stage_num, len(result), is_revision,
            )

        await _fill_dialogue_drafts(chapter, by_num, generated)

    logger.info(
        "[setup_chat_perf] write_chapter_skeleton call finished | elapsed_ms={:.2f} | meta={}",
        (time.perf_counter() - t_call) * 1000, call_meta,
    )

    written: list[int] = []
    beat_counts: list[str] = []
    for stage_num, beats in generated.items():
        st = by_num[stage_num]
        st["beats"] = beats
        st.pop("skeleton", None)  #清遗留旧字段，防被误当已扩写
        written.append(stage_num)
        beat_counts.append(f"stage{stage_num}（{len(beats)}拍）")

    try:
        get_plot_repo().save_all(chapters)
    except OSError as exc:
        return f"写盘失败：{exc}"
    for sn in written:
        skeleton_pipeline.clear_stage_markers(chapter, sn)

    from engine.setup_chat.chapter_review import (
        chapter_skeleton_complete,
        maybe_schedule_skeleton_chapter_review,
    )

    report = ""
    all_stages = ch.get("stages") or []
    if chapter_skeleton_complete(all_stages):
        skeleton_pipeline.clear_chapter_active(chapter)
        await maybe_schedule_skeleton_chapter_review(
            chapter, all_stages,
            is_reviewed=args.is_reviewed,
            invalidate_reviewed=not args.is_reviewed,
        )
        if not args.is_reviewed:
            report = "过渡/文风审查已转入后台自动进行，完成前本章其它操作会被暂缓，完成后我会告诉你结果。"
    return format_tool_done(
        f"已生成第 {chapter} 章骨架（{'、'.join(beat_counts)}）。", report)


@tool(args_schema=AutoExpandSkeletonArgs)
async def auto_expand_skeleton(chapter: int) -> str:
    """AUTO 模式专用：该章骨架完全未展开时一次性把全部段的分镜/情景拓展/写作底稿扩完，不逐段
    停顿确认。已展开过任意一段的章节，或手动模式，这个工具不会出现在可选工具里（tool_router
    收窄 + gate_tool_call 双重防御），别在其它场景调用它——那些情况请改用交互式
    skeleton-expansion 流程继续未完成的段。"""
    import time

    from domain.token_usage import extract_usage
    from langchain_core.messages import HumanMessage, SystemMessage
    from llm.factory import get_cloud_llm
    from llm.prompt_logger import PromptLogger

    from engine.modes.author_loop_skill_prefs import (
        load_dialogue_prefs,
        node_llm_sampling_kwargs,
        resolve_node_base_llm,
    )
    from engine.setup_chat.skeleton_auto_construct import run_auto_expand_skeleton

    prefs = load_dialogue_prefs()
    import_params = prefs["import_llm_params"]
    base_llm = resolve_node_base_llm(get_cloud_llm(), "auto_expand_skeleton", import_params)
    model_name = str(getattr(base_llm, "model", "") or getattr(base_llm, "model_name", "") or "cloud")
    sampling = node_llm_sampling_kwargs(base_llm, "auto_expand_skeleton", import_params)
    llm = base_llm.bind(**sampling) if sampling else base_llm
    prompt_logger = PromptLogger(chapter)
    step = 0

    async def call_llm(system: str, user: str) -> str:
        nonlocal step
        step += 1
        t0 = time.monotonic()
        resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        content = resp.content if hasattr(resp, "content") else str(resp)
        text = content if isinstance(content, str) else str(content)
        tin, tout, tcached = extract_usage(resp)
        prompt_logger.log_llm_call(
            step=step, agent="auto_expand_skeleton", model=model_name,
            system=system, user=user, response=text,
            tokens_in=tin, tokens_out=tout, tokens_cached=tcached,
            duration_s=time.monotonic() - t0,
        )
        return text

    try:
        return await run_auto_expand_skeleton(chapter, call_llm)
    finally:
        prompt_logger.close()


@tool(args_schema=ReadSkeletonSeedArgs)
def read_skeleton_seed(chapter: int) -> str:
    """扩写某章骨架前先调本工具：一次性拿到世界观、本章角色档案、粗大纲+角色名单、伏笔召回
    四块事实记忆。调用后引擎会在此章骨架扩完前的每一轮对话里持续重新注入同样的内容，无需
    重复调用，也不必再另外调 read_setup_summary/read_character_archive 去补这些。
    扩写好的写作底稿用 write_chapter_skeleton 写回。"""
    from engine.setup_chat import skeleton_pipeline
    from engine.setup_chat.skeleton_seed import build_skeleton_seed, render_skeleton_seed

    seed = build_skeleton_seed(chapter)
    if not seed.get("stages"):
        return f"第 {chapter} 章无 plot（请先写本章 plot 再扩骨架）。"
    skeleton_pipeline.mark_chapter_active(chapter)
    return render_skeleton_seed(seed)


@tool(args_schema=ReadChapterSkeletonArgs)
def read_chapter_skeleton(chapter: int, stage_num: int | None = None) -> str:
    """读某章已扩写的【分拍底稿】（write_chapter_skeleton 写回的 beats：逐拍 text，若设计了台词已织入其中）。
    修订/精修/台词设计前先调此工具看现状；省略 stage_num=整章各段，给 stage_num=只看该段。
    未分拍的段标「（待扩写）」。"""
    from repositories import get_plot_repo
    chapters = get_plot_repo().list_raw()
    ch = next((c for c in chapters if isinstance(c, dict) and c.get("chapter") == chapter), None)
    if ch is None:
        return f"第 {chapter} 章不存在于 plot。"
    stages = ch.get("stages") or []
    if stage_num is not None:
        stages = [s for s in stages if s.get("stage_num") == stage_num]
        if not stages:
            return f"第 {chapter} 章无 stage {stage_num}。"
    lines = [f"第 {chapter} 章分拍底稿："]
    for s in stages:
        lines.append(f"\n— stage{s.get('stage_num')} —")
        beats = s.get("beats")
        if not isinstance(beats, list) or not beats:
            lines.append("（待扩写）")
            continue
        for i, b in enumerate(beats):
            if not isinstance(b, dict):
                continue
            lines.append(f"【拍{i}】{str(b.get('text') or '').strip()}")
            notes = [str(x).strip() for x in (b.get("sensation_notes") or []) if str(x).strip()]
            if notes:
                lines.append("  体感参考：" + "／".join(notes))
    return "\n".join(lines)


_MANUSCRIPT_METADATA_PREFIXES = ("- **【地点场景】**", "- **【摘要】**", "- **【角色状态】**")


def _strip_manuscript_metadata(block: str) -> str:
    """chat agent 读成稿只看阶段标题 + 过程描述，地点/摘要/角色状态等结构化元数据不给它看。"""
    paragraphs = block.split("\n\n")
    kept = [p for p in paragraphs if not p.lstrip().startswith(_MANUSCRIPT_METADATA_PREFIXES)]
    return "\n\n".join(kept)


def _slice_author_manuscript_stages(md: str, *, stage_num: int, stage_to: int | None) -> str:
    from engine.setup_chat.text_patch import slice_manuscript_blocks, split_manuscript_blocks

    blocks = [_strip_manuscript_metadata(b) for b in split_manuscript_blocks(md)]
    return slice_manuscript_blocks(
        blocks,
        stage_num=stage_num,
        stage_to=stage_to,
    )


def _to_patch_ops(patches: list) -> list:
    from engine.setup_chat.text_patch import TextPatchOp

    return [
        TextPatchOp(
            mode=p["mode"] if isinstance(p, dict) else p.mode,
            find=p["find"] if isinstance(p, dict) else p.find,
            replace=p["replace"] if isinstance(p, dict) else p.replace,
            match_policy=p["match_policy"] if isinstance(p, dict) else p.match_policy,
        )
        for p in patches
    ]


def _patch_result_is_error(out: str) -> bool:
    """True when a text-patch tool returned without persisting (validation/write failure)."""
    prefixes = ("校验未通过", "写盘失败", "不存在于 plot", "无 stage", "尚未分拍", "为空，无法")
    return any(out.startswith(p) or p in out[:40] for p in prefixes)


def _patch_plot_text(
    *,
    chapter: int,
    field: str,
    scope: str,
    stage_num: int | None,
    patches: list,
    dry_run: bool,
) -> str:
    import copy

    from repositories import get_plot_repo

    from engine.setup_chat.text_patch import apply_text_patches, format_patch_report
    from engine.setup_chat.tool_args import load_plot_grounding, validate_plot_chapters

    chapters = get_plot_repo().list_raw()
    ch = next((c for c in chapters if isinstance(c, dict) and c.get("chapter") == chapter), None)
    if ch is None:
        return f"第 {chapter} 章不存在于 plot。"

    stages = [s for s in (ch.get("stages") or []) if isinstance(s, dict)]
    if not stages:
        return f"第 {chapter} 章无 stage。"

    ops = _to_patch_ops(patches)
    reports: list[str] = []
    snapshot = copy.deepcopy(ch)

    targets: list[tuple[int, dict]] = []
    if scope == "stage":
        assert stage_num is not None
        st = next((s for s in stages if s.get("stage_num") == stage_num), None)
        if st is None:
            nums = sorted(v for s in stages if isinstance(v := s.get("stage_num"), int))
            return f"第 {chapter} 章无 stage {stage_num}（现有：{nums}）。"
        targets = [(stage_num, st)]
    else:
        for st in stages:
            sid = st.get("stage_num")
            if isinstance(sid, int):
                targets.append((sid, st))

    for sid, st in targets:
        old = str(st.get(field) or "")
        if not old.strip():
            if scope == "stage":
                return f"第 {chapter} 章 stage {sid} 的 {field} 为空，无法替换。"
            reports.append(f"stage {sid} · {field}：跳过（空）")
            continue
        result = apply_text_patches(old, ops)
        label = f"第 {chapter} 章 stage {sid} · {field}"
        if not result.ok:
            ch.clear()
            ch.update(snapshot)
            return format_patch_report(label=label, result=result, dry_run=dry_run, text_preview=old)
        if not dry_run:
            st[field] = result.text
        reports.append(format_patch_report(
            label=label, result=result, dry_run=dry_run, text_preview=result.text,
        ))

    if not dry_run and reports:
        g = load_plot_grounding()
        errs = validate_plot_chapters([ch], character_names=g.get("character_names", []))
        if errs:
            ch.clear()
            ch.update(snapshot)
            return "校验未通过，未写入：\n" + "\n".join(f"- {e}" for e in errs)
        get_plot_repo().save_all(chapters)

    head = f"plot {field} 补丁完成" if not dry_run else f"plot {field} dry_run 预览"
    return format_tool_done(head, "\n\n".join(reports))


def _patch_beat_text(
    *,
    chapter: int,
    stage_num: int,
    beat_idx: int,
    patches: list,
    dry_run: bool,
) -> str:
    """单拍 text 的手术式替换：只动 beats[beat_idx]["text"]，其它字段原样保留。"""
    import copy

    from repositories import get_plot_repo

    from engine.setup_chat.text_patch import apply_text_patches, format_patch_report
    from engine.setup_chat.tool_args import load_plot_grounding, validate_plot_chapters

    chapters = get_plot_repo().list_raw()
    ch = next((c for c in chapters if isinstance(c, dict) and c.get("chapter") == chapter), None)
    if ch is None:
        return f"第 {chapter} 章不存在于 plot。"
    stages = [s for s in (ch.get("stages") or []) if isinstance(s, dict)]
    st = next((s for s in stages if s.get("stage_num") == stage_num), None)
    if st is None:
        nums = sorted(v for s in stages if isinstance(v := s.get("stage_num"), int))
        return f"第 {chapter} 章无 stage {stage_num}（现有：{nums}）。"
    beats = st.get("beats")
    if not isinstance(beats, list) or not beats:
        return f"stage {stage_num} 尚未分拍扩写，无法替换（先 skeleton-expansion）。"
    if not (0 <= beat_idx < len(beats)):
        return f"stage {stage_num} 无拍 {beat_idx}（现有 0..{len(beats) - 1}）。"
    old = str(beats[beat_idx].get("text") or "")
    if not old.strip():
        return f"stage {stage_num} 拍 {beat_idx} 的 text 为空，无法替换。"

    snapshot = copy.deepcopy(ch)
    result = apply_text_patches(old, _to_patch_ops(patches))
    label = f"第 {chapter} 章 stage {stage_num} · 拍{beat_idx}"
    if not result.ok:
        return format_patch_report(label=label, result=result, dry_run=dry_run, text_preview=old)
    if not dry_run:
        beats[beat_idx]["text"] = result.text
        g = load_plot_grounding()
        errs = validate_plot_chapters([ch], character_names=g.get("character_names", []))
        if errs:
            ch.clear()
            ch.update(snapshot)
            return "校验未通过，未写入：\n" + "\n".join(f"- {e}" for e in errs)
        try:
            get_plot_repo().save_all(chapters)
        except OSError as exc:
            ch.clear()
            ch.update(snapshot)
            return f"写盘失败：{exc}"
    head = "拍文补丁完成" if not dry_run else "拍文 dry_run 预览"
    return format_tool_done(head, format_patch_report(
        label=label, result=result, dry_run=dry_run, text_preview=result.text,
    ))


def _patch_manuscript_text(
    *,
    chapter: int,
    scope: str,
    stage_num: int | None,
    patches: list,
    dry_run: bool,
) -> str:
    from api.services.pipeline_catalog import read_author_manuscript

    from engine.setup_chat.text_patch import (
        apply_text_patches,
        format_patch_report,
        split_manuscript_blocks,
        write_manuscript_blocks,
    )

    try:
        body = read_author_manuscript(chapter)
        content = str(body.get("content") or "")
    except FileNotFoundError:
        return f"第 {chapter} 章暂无保存的主笔成稿。"
    except OSError as exc:
        return f"读取成稿失败：{exc}"

    blocks = split_manuscript_blocks(content)
    if not blocks:
        return f"第 {chapter} 章成稿为空。"

    ops = _to_patch_ops(patches)
    reports: list[str] = []
    originals = list(blocks)

    def _patch_block(idx: int, block: str) -> tuple[str, bool]:
        old = block
        if not old.strip():
            return f"stage {idx + 1}：跳过（空块）", True
        result = apply_text_patches(old, ops)
        label = f"第 {chapter} 章成稿 stage {idx + 1}"
        if not result.ok:
            return format_patch_report(
                label=label, result=result, dry_run=dry_run, text_preview=old,
            ), False
        blocks[idx] = result.text
        return format_patch_report(
            label=label, result=result, dry_run=dry_run, text_preview=result.text,
        ), True

    if scope == "manuscript_stage":
        assert stage_num is not None
        if stage_num < 1 or stage_num > len(blocks):
            return f"stage 超范围：现有 1..{len(blocks)}"
        rep, ok = _patch_block(stage_num - 1, blocks[stage_num - 1])
        if not ok:
            blocks[:] = originals
            return rep
        reports.append(rep)
    else:
        for i in range(len(blocks)):
            rep, ok = _patch_block(i, blocks[i])
            if not ok:
                blocks[:] = originals
                return rep
            reports.append(rep)

    if not dry_run:
        try:
            write_manuscript_blocks(chapter, blocks)
        except (FileNotFoundError, OSError) as exc:
            blocks[:] = originals
            return f"写盘失败：{exc}"

    head = "成稿补丁完成" if not dry_run else "成稿 dry_run 预览"
    return format_tool_done(head, "\n\n".join(reports))


@tool(args_schema=PatchTextFragmentArgs)
async def patch_text_fragment(
    source: str,
    chapter: int,
    patches: list,
    scope: str = "stage",
    stage_num: int | None = None,
    beat_idx: int | None = None,
    dry_run: bool = False,
    is_reviewed: bool = False,
) -> str:
    """
对大纲/分拍底稿/主笔成稿做文内手术式替换（literal 或 regex），避免整段重写失真与 token 过大。

    - plot_description：scope=stage（需 stage_num）改单段；scope=chapter 对本章每段逐段应用同一组补丁。
    - plot_skeleton：单拍定位（需 stage_num + beat_idx），只改该拍 text（若已织入台词，一并按字面替换）。
    - manuscript：scope=manuscript_stage（需 stage_num）或 manuscript_chapter（逐 stage 块）。
    - match_policy 默认 unique：命中 0 或多处会失败并返回上下文预览，请加长 find 或改用 all/first。
    - dry_run=true 只预览命中，不写盘。手术式改 description 不会清空 beats。
    按后台审查通知改 plot 字段时设 is_reviewed=true，写盘后不再触发全章过渡/文风审查。"""
    args = PatchTextFragmentArgs.model_validate({
        "source": source,
        "chapter": chapter,
        "scope": scope,
        "stage_num": stage_num,
        "beat_idx": beat_idx,
        "patches": patches,
        "dry_run": dry_run,
        "is_reviewed": is_reviewed,
    })
    patch_dicts = [p.model_dump() for p in args.patches]

    if args.source == "plot_description":
        out = _patch_plot_text(
            chapter=args.chapter,
            field="description",
            scope=args.scope,
            stage_num=args.stage_num,
            patches=patch_dicts,
            dry_run=args.dry_run,
        )
    elif args.source == "plot_skeleton":
        assert args.stage_num is not None and args.beat_idx is not None  #args 校验已保证
        out = _patch_beat_text(
            chapter=args.chapter,
            stage_num=args.stage_num,
            beat_idx=args.beat_idx,
            patches=patch_dicts,
            dry_run=args.dry_run,
        )
    else:
        return _patch_manuscript_text(
            chapter=args.chapter,
            scope=args.scope,
            stage_num=args.stage_num,
            patches=patch_dicts,
            dry_run=args.dry_run,
        )

    if args.dry_run or _patch_result_is_error(out):
        return out

    from utils.paths import active_novel_id

    from engine.setup_chat.skeleton_background_review import cancel_active_review

    await cancel_active_review(active_novel_id(), args.chapter)

    from repositories import get_plot_repo

    from engine.setup_chat.chapter_review import maybe_schedule_skeleton_chapter_review

    ch = next(
        (c for c in get_plot_repo().list_raw()
         if isinstance(c, dict) and c.get("chapter") == args.chapter),
        None,
    )
    stages = [s for s in (ch.get("stages") or []) if isinstance(s, dict)] if ch else []
    await maybe_schedule_skeleton_chapter_review(
        args.chapter, stages,
        is_reviewed=args.is_reviewed,
        invalidate_reviewed=not args.is_reviewed,
    )
    return out


@tool(args_schema=ReadAuthorManuscriptArgs)
def read_author_manuscript(chapter: int, stage_num: int, stage_to: int | None = None) -> str:
    """
按指定 stage 区间读取已保存的主笔成稿（供 chat agent 增量参考，而非一次性整章加载）。

只保留阶段标题与【过程描述】正文，地点场景/摘要/角色状态等结构化元数据不返回——
chat agent 该看的是写出来的过程描述，不是这些底层状态字段。
"""
    args = ReadAuthorManuscriptArgs(chapter=chapter, stage_num=stage_num, stage_to=stage_to)
    try:
        from api.services.pipeline_catalog import read_author_manuscript as _read

        body = _read(args.chapter)
        content = str(body.get("content") or "")
    except FileNotFoundError:
        return f"第 {args.chapter} 章暂无保存的主笔成稿。"
    except (OSError, ValueError) as exc:
        return f"读取成稿失败：{exc}"

    try:
        sliced = _slice_author_manuscript_stages(content, stage_num=args.stage_num, stage_to=args.stage_to)
    except ValueError as exc:
        return f"切片失败：{exc}"

    rng = (
        f"stage {args.stage_num}..{args.stage_to}"
        if args.stage_to is not None and args.stage_to != args.stage_num
        else f"stage {args.stage_num}"
    )
    return format_tool_done(f"已读取第 {args.chapter} 章主笔成稿（{rng}）。", sliced)


@tool(args_schema=QueryCharacterVoiceArgs)
def query_character_voice(character: str, chapter: int, stage_num: int) -> str:
    """设计某拍台词前调用：取该角色本章本段的声线接地——人格 personality、口癖、自称池。
    据此写台词语气，别凭空发挥声线（角色人格/口癖变了，声线也该跟着变）。"""
    from context.dialogue.scene_aware import as_target_pool_map
    from context.personality import resolved_personality

    from engine.author_loop.dialogue_mode.chapter_state import resolve_card_state

    resolved = resolve_card_state(character, chapter, stage_num)
    if not resolved:
        return f"{character} 无档案（先建角色档案/lore），无法取声线。"
    personality = resolved_personality(resolved)
    lines = [
        f"{character} · 第 {chapter} 章 stage{stage_num} 声线接地：",
        f"人格：{personality or '（无）'}",
    ]
    tic = str(resolved.get("verbal_tic") or "").strip()
    lines.append(f"口癖：{tic or '（无）'}")
    self_ref = (
        as_target_pool_map(resolved.get("self_ref"), legacy_default_key="_default")
        if resolved.get("self_ref") else {}
    )
    default_self = self_ref.get("_default") or []
    if default_self:
        lines.append(f"自称池：{'／'.join(default_self)}")
    return "\n".join(lines)


@tool(args_schema=ReadArchiveStatusArgs)
def read_archive_status(chapter: int) -> str:
    """
Look at the character archive progress of a certain chapter: List the characters appearing in this chapter + each has been pushed/to be pushed. Use it to pick the next character when spawning from character to character."""
    from context import character_timeline

    from engine.setup_chat.timeline_seed import _chapter_roster

    roster = _chapter_roster(chapter)
    if not roster:
        return f"第 {chapter} 章 plot 无出场角色（请先写本章 plot）。"
    lines = [f"第 {chapter} 章角色档案进度："]
    for name in roster:
        snaps = character_timeline.load_timeline(name)["snapshots"]
        built = any(s.get("chapter") == chapter for s in snaps)
        lines.append(f"  - {name}：{'已推 ✓' if built else '待推'}")
    return "\n".join(lines)


@tool(args_schema=ReadArchiveSeedArgs)
def read_archive_seed(chapter: int, name: str) -> str:
    """派生某角色某章档案前先调本工具：拿前序快照（种子）、滑块档位、本章出场 stage 概览。
    调用后引擎会在这个角色这一章档案写完前的每一轮对话里持续重新注入同样的内容，无需重复调用。
    据此一次性写出整章档案，再用 write_character_archive 写回（不用也不该逐 stage 分批写）。"""
    from engine.setup_chat import world_pipeline
    from engine.setup_chat.timeline_seed import build_timeline_seed, render_timeline_seed

    seed = build_timeline_seed(name, chapter)
    if not seed["stages"]:
        return f"{name} 不在第 {chapter} 章出场（plot 无其 stage）。"
    world_pipeline.mark_timeline_active(chapter, name)
    return render_timeline_seed(seed)


@tool(args_schema=ReadCharacterArchiveArgs)
def read_character_archive(chapter: int, name: str | None = None) -> str:
    """
Check the derived character profile (status/growth axis/causal anchor point, etc.) of a chapter. Name is omitted = the entire chapter, given name = only the character."""
    from engine.archive.archive_view import render_archive_summary, render_chapter_archives

    data = render_chapter_archives(chapter)
    chars = data.get("characters") or []
    if name:
        chars = [c for c in chars if c.get("name") == name]
        if not chars:
            return f"第 {chapter} 章没有角色「{name}」的档案。"
    if not chars:
        return f"第 {chapter} 章暂无角色档案。"
    return render_archive_summary(data["chapter"], chars)


@tool(args_schema=ReadCharacterArgs)
def read_character(name: str) -> str:
    """读某个角色的完整基础设定卡（因果设定/着装DNA/身份背景/人格/爱好/口癖等 lore 底稿）。
    这是静态创建期设定，不含运行期派生状态（某章的滑块/自称/物理异化等）——那些用
    read_character_archive。"""
    from repositories import get_lore_repo

    for c in get_lore_repo().list_raw():
        if isinstance(c, dict) and c.get("name") == name:
            return render_character_chat(c)
    return f"未找到角色「{name}」。"


def _render_relationship_edges(edges: list[dict]) -> str:
    lines = []
    for e in edges:
        s = f"- 「{e['from']}」→「{e['to']}」：{e['nature']}"
        if e["relationship_anchor"]:
            s += f"（{e['relationship_anchor']}）"
        terms = []
        if e["from_ref_terms"]:
            terms.append(f"{e['to']} 称 {e['from']} 为「{'/'.join(e['from_ref_terms'])}」")
        if e["to_ref_terms"]:
            terms.append(f"{e['from']} 称 {e['to']} 为「{'/'.join(e['to_ref_terms'])}」")
        if terms:
            s += "；" + "，".join(terms)
        lines.append(s)
    return "\n".join(lines)


@tool(args_schema=ReadRelationshipsArgs)
def read_relationships(name: str) -> str:
    """查关系图谱里某角色作为 from 或 to 出现的所有边（两个方向都返回）。写关系边前先查一下，
    避免跟已有边重复或矛盾。查不到人不代表没关系，也可能是当陌生人没建边（宁缺毋滥）。"""
    from engine.setup.cast.relationship_graph import edges_for_character, load_graph

    edges = edges_for_character(load_graph(), name)
    if not edges:
        return f"角色「{name}」在关系图谱里没有任何边。"
    return _render_relationship_edges(edges)


@tool(args_schema=AddRelationshipEdgeArgs)
def add_relationship_edge(
    from_name: str,
    to_name: str,
    nature: str,
    relationship_anchor: str = "",
    from_ref_terms: list[str] | None = None,
    to_ref_terms: list[str] | None = None,
) -> str:
    """新增/覆盖一条关系边（frm→to）。frm/to 必须是花名册里的真实角色全名。若该方向的边已
    存在，本次写入会覆盖旧的 nature/anchor（同一对角色重复调用=更新，不是叠加）。"""
    from repositories import get_lore_repo

    from engine.setup.cast.relationship_graph import append_edge, validate_edge

    names = {
        str(c.get("given_name") or c.get("name") or "").strip()
        for c in get_lore_repo().list_raw() if isinstance(c, dict)
    }
    edge = {
        "from": from_name,
        "to": to_name,
        "nature": nature,
        "relationship_anchor": relationship_anchor,
        "from_ref_terms": from_ref_terms or [],
        "to_ref_terms": to_ref_terms or [],
    }
    errs = validate_edge(edge, names)
    if errs:
        return "关系边校验未通过，未写入：\n" + "\n".join(f"- {e}" for e in errs)
    try:
        append_edge(edge)
    except OSError as exc:
        return f"写盘失败：{exc}"
    return format_tool_done(f"已写入关系边「{from_name}」→「{to_name}」（{nature}）。")


@tool(args_schema=RemoveRelationshipEdgeArgs)
def remove_relationship_edge(from_name: str, to_name: str) -> str:
    """删除一条关系边（逻辑删除，不影响反方向的边）。删除前建议先用 read_relationships 确认
    这条边确实存在。"""
    from engine.setup.cast.relationship_graph import directed_edge, load_graph, remove_edge

    if directed_edge(load_graph(), from_name, to_name) is None:
        return f"没有找到「{from_name}」→「{to_name}」这条边，无需删除。"
    try:
        remove_edge(from_name, to_name)
    except OSError as exc:
        return f"写盘失败：{exc}"
    return format_tool_done(f"已删除关系边「{from_name}」→「{to_name}」。")


@tool(args_schema=DeleteCharacterArgs)
async def delete_character(name: str) -> str:
    """删除一个角色：花名册档案 + 大纲/分拍文本提及该角色的章节（整章级联删除，含该章正文与
    角色档案）+ 关系图谱里涉及该角色的所有边。不可逆，删除前建议先用 read_character /
    read_relationships 确认。"""
    _ok, msg, _detail = await _delete_character_core(name)
    return msg


@tool(args_schema=DeleteChapterArgs)
async def delete_chapter(chapter: int) -> str:
    """删除一整章：大纲/骨架条目 + 已生成的正文成稿 + 该章所有角色档案；后续每一章的章号自动
    -1（正文/角色档案/沙盒记录/磁盘目录全部随行）。只有这一章里实际出场过的角色，其后续章节
    档案才会被重新推演——没在这章出现过的角色，档案原样保留，只是坐标随行迁移。不可逆，删除前
    建议先用 read_chapter_skeleton / read_author_manuscript 确认。"""
    _ok, msg, _detail = await _delete_chapter_core(chapter)
    return msg


@tool(args_schema=WriteProseStylePresetArgs)
async def write_prose_style_preset(
    slug: str,
    title: str,
    opening: str,
    techniques: list[str],
    examples: list[dict],
    taboos: list[str],
) -> str:
    """按用户在对话中描述的文风要求，创建一份新的可选用文风预设卡片（与静态预设同构：
    标题+开场定位+发挥方向+风格样例+忌讳）。仅用于新建：slug 不能和任何已存在的预设（静态
    手写的或此前已创建的）重名，撞了会直接报错不落盘——静态预设受保护无法覆盖，撞到已有的
    自建/自动预设则改用 edit_prose_style_preset 去修改它。新建请用未出现过的 slug，且不要以
    auto- 开头（该前缀被小说导入自动生成的专属预设占用）。写完后用 read_prose_style_preset
    确认效果；要在某本小说里实际启用，需要用户去前端「设定→文风」选它（这一步不由本工具完成）。"""
    from engine.execution.prose_style import (
        is_static_preset,
        prose_styles_dir,
        render_prose_style_card,
    )

    if is_static_preset(slug):
        return f"「{slug}」是静态预设的 id，受保护，不能用同名 slug 创建，请换一个未占用的 slug。"
    data_path = os.path.join(prose_styles_dir(), f"{slug}.md")
    if os.path.exists(data_path):
        return f"「{slug}」已存在，如果是想修改它，请用 edit_prose_style_preset；如果想新建，请换一个未占用的 slug。"

    #langchain resolves nested list items against args_schema's ProseStyleExampleArgs, not the
    #bare `dict` type hint above -- same dance as _dump_sliders/_dump_roles for nested models.
    dumped_examples = [
        e.model_dump() if hasattr(e, "model_dump") else e for e in examples
    ]
    card = render_prose_style_card(
        title=title,
        opening=opening,
        techniques=techniques,
        examples=[{"label": e.get("label", ""), "text": e.get("text", "")} for e in dumped_examples],
        taboos=taboos,
    )
    try:
        out_dir = prose_styles_dir()
        os.makedirs(out_dir, exist_ok=True)
        tmp = data_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(card)
        os.replace(tmp, data_path)
    except OSError as exc:
        return f"写盘失败：{exc}"
    return format_tool_done(f"已写入文风预设「{slug}」。", card)


@tool(args_schema=WriteProseStylePresetArgs)
async def edit_prose_style_preset(
    slug: str,
    title: str,
    opening: str,
    techniques: list[str],
    examples: list[dict],
    taboos: list[str],
) -> str:
    """修改一份已存在的、非静态的文风预设（agent 自建的和小说导入自动生成的 auto-<novel_id>
    均可，静态手写预设受保护、无法编辑）。全卡重写：所有字段需要按修改后的完整内容传入，不是
    只传变化的字段。改之前建议先用 read_prose_style_preset 读一遍原卡，把不想改的部分原样
    抄进对应字段。"""
    from engine.execution.prose_style import (
        is_static_preset,
        prose_styles_dir,
        render_prose_style_card,
    )

    if is_static_preset(slug):
        return f"「{slug}」是静态预设，受保护，无法编辑。"
    data_path = os.path.join(prose_styles_dir(), f"{slug}.md")
    if not os.path.exists(data_path):
        return f"未找到可编辑的预设「{slug}」，可用 list_prose_style_presets 查看现有列表；如果是要新建，请用 write_prose_style_preset。"

    dumped_examples = [
        e.model_dump() if hasattr(e, "model_dump") else e for e in examples
    ]
    card = render_prose_style_card(
        title=title,
        opening=opening,
        techniques=techniques,
        examples=[{"label": e.get("label", ""), "text": e.get("text", "")} for e in dumped_examples],
        taboos=taboos,
    )
    try:
        tmp = data_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(card)
        os.replace(tmp, data_path)
    except OSError as exc:
        return f"写盘失败：{exc}"
    return format_tool_done(f"已更新文风预设「{slug}」。", card)


@tool
def list_prose_style_presets() -> str:
    """列出当前所有可选文风预设（静态手写+自动/chat 生成），返回 id｜标题（来源）列表。
    「静态·不可改」的不能调 edit_prose_style_preset；「可编辑」的才能改。基于现有某个预设
    改之前，先用这个工具找到它的 id，再用 read_prose_style_preset 读全文。"""
    from engine.execution import prose_style

    presets = prose_style.list_prose_style_presets()
    if not presets:
        return "暂无任何文风预设。"
    lines = []
    for p in presets:
        tag = "静态·不可改" if p.get("origin") == "static" else "可编辑"
        lines.append(f"- {p['id']}｜{p['title']}（{tag}）")
    return "\n".join(lines)


@tool(args_schema=ReadProseStylePresetArgs)
def read_prose_style_preset(preset_id: str) -> str:
    """读取某个文风预设的完整卡片正文（静态或自动/chat 生成均可）。"""
    from engine.execution.prose_style import load_preset_card

    card = load_preset_card(preset_id)
    if not card:
        return f"未找到预设「{preset_id}」，可用 list_prose_style_presets 查看现有列表。"
    return card
