"""Main author's writing and sharing tools: checkpoint cleaning/dropping, pre-built skeleton reading, status merging helper.

Dialogue mode and REST routing share this module; the classic beat-by-beat engine has been retired."""
from __future__ import annotations

import re
from dataclasses import dataclass

from loguru import logger
from utils.paths import (
    author_loop_graph_checkpoint_path,
    author_loop_journal_path,
)


def clear_author_loop(chapter: int) -> None:
    """Clear the chapter checkpoint (LangGraph thread) + journal (used for "restarting"). Ignore if not present."""
    import os

    # Local, like the checkpoint import below: keeps media out of this module's import graph,
    # which the REST layer and the dialogue engine both pull in on startup.
    from media.scene.author_store import clear_author_stage_scene_images

    from engine.author_loop.dialogue_mode.chapter_checkpoint import clear_chapter_thread

    clear_chapter_thread(author_loop_graph_checkpoint_path(), f"ch{chapter}")
    try:
        os.remove(author_loop_journal_path(chapter))
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning("[author-loop] 清理 journal 失败 chapter={}：{}", chapter, e)

    # The per-stage scene images are keyed by (chapter, stage_index) in their own sidecar doc, so
    # a re-run of this chapter would otherwise hang last run's art off the new stages.
    clear_author_stage_scene_images(chapter)


def save_author_loop_chapter(chapter: int) -> str:
    """
Put the checkpoint per-stage text + character status into a whole chapter .md, then return to the writing path."""
    import os

    from utils.paths import get_chapter_dir

    from engine.author_loop.dialogue_mode.chapter_checkpoint import read_chapter_checkpoint_values
    from engine.state import assemble_chapter_file

    cp_path = author_loop_graph_checkpoint_path()
    thread_id = f"ch{chapter}"
    cv = read_chapter_checkpoint_values(cp_path, thread_id)
    parts_raw = cv.get("parts")
    parts = [str(p) for p in parts_raw] if isinstance(parts_raw, list) else []
    if not parts:
        raise ValueError("该章暂无主笔产出，无法保存")

    #parts[j] 源自 stages[part_stage_idx[j]]（正文为空的 stage 被引擎跳过，两者不能按位置对齐）。
    cp_stages_raw = cv.get("stages")
    cp_stages = list(cp_stages_raw) if isinstance(cp_stages_raw, list) else []
    idx_raw = cv.get("part_stage_idx")
    part_stage_idx = [int(x) for x in idx_raw] if isinstance(idx_raw, list) else list(range(len(parts)))
    states_raw = cv.get("part_character_states")
    part_character_states = list(states_raw) if isinstance(states_raw, list) else []

    _title, outline_stages = fetch_chapter_outline(chapter)
    meta_by_stage = {int(s.get("stage_num", i + 1)): s for i, s in enumerate(outline_stages or [])}
    segments = []
    for i, text in enumerate(parts):
        stage_idx = part_stage_idx[i] if i < len(part_stage_idx) else i
        cp_stage = cp_stages[stage_idx] if stage_idx < len(cp_stages) and isinstance(cp_stages[stage_idx], dict) else {}
        stage_num = int(cp_stage.get("stage", 0) or 0)
        stage_meta = meta_by_stage.get(stage_num, {})
        segments.append({
            "index": i,
            "stage_num": stage_num,
            "characters": list(cp_stage.get("characters") or []),
            "title": str(stage_meta.get("title", "")),
            "location": str(stage_meta.get("location", "")),
            "text": (text or "").strip(),
            "character_states": part_character_states[i] if i < len(part_character_states) else {},
        })
    body = assemble_chapter_file(
        chapter,
        segments,
        md_block_provider=lambda i: _format_stage_state_block(segments[i], chapter=chapter),
    )
    chapter_dir = get_chapter_dir(chapter)
    os.makedirs(chapter_dir, exist_ok=True)
    path = os.path.join(chapter_dir, f"第{chapter}章_主笔.md")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(tmp, path)
    _export_prompt_dump(chapter)
    return path


def _export_prompt_dump(chapter: int) -> None:
    """保存章节时把本章最新一轮的全部 prompt 收发导出成可读文本(纯增益,失败不阻塞保存)。

    复用 scripts/prompt_parse.py 的 -c(取该章最新日志)而不复制其解析逻辑;
    子进程隔离脚本崩溃。本章无日志(如纯手工导入)直接跳过,不空转。"""
    import glob
    import os
    import subprocess
    import sys

    from utils.paths import SCRIPTS_DIR, engine_logs_dir, prompt_dump_path

    if getattr(sys, "frozen", False):
        # scripts/ isn't bundled and sys.executable is the PyInstaller bootloader, not
        # a Python interpreter — this diagnostic export only applies to source checkouts.
        return
    if not glob.glob(os.path.join(engine_logs_dir(), f"chapter_{chapter:03d}_*.json")):
        return
    out = prompt_dump_path(chapter)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    script = os.path.join(SCRIPTS_DIR, "prompt_parse.py")
    try:
        subprocess.run(
            [sys.executable, script, "-c", str(chapter), "-o", out],
            capture_output=True, timeout=60, check=False,
        )
        logger.info("[author-loop] 本章 prompt 全量导出 → {}", out)
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("[author-loop] prompt 导出失败 chapter={}：{}", chapter, e)


def _format_stage_state_block(
    segment: dict,
    *,
    chapter: int,
) -> str:
    """Single stage additional block: runtime-derived dynamic state of the roles present
    (dropped before process description).

    角色动态态来自图内 checkpoint 的逐 part 快照(见 react_graph.py 的 part_character_states)，
    不再现读 archive——archive 已不含 psychology/posture/clothing/action/demeanor 这些字段。"""
    from engine.author_loop.dialogue_mode.chapter_state import render_state_view

    character_states = segment.get("character_states") or {}
    char_lines: list[str] = []
    for name in segment.get("characters") or []:
        n = str(name).strip()
        if not n:
            continue
        dynamic_state = character_states.get(n)
        if dynamic_state:
            char_lines.append(f"  - **{n}**：\n{render_state_view(dynamic_state)}")
    if not char_lines:
        return ""
    return "- **【角色状态】**：\n" + "\n".join(char_lines)


def fetch_chapter_outline(chapter: int):
    from repositories import get_plot_repo
    return get_plot_repo().chapter_segments(chapter)


def _lore_repo():
    """
Quote lore repo (module-level thin packaging, easy to test monkeypatch)."""
    from repositories import get_lore_repo
    return get_lore_repo()


def _archive_repo():
    from repositories import get_archive_repo
    return get_archive_repo()





class SkeletonNotBuiltError(Exception):
    """本章骨架尚未在对话里分拍扩写（plot stage 缺 beats 字段或有空拍）。"""

def load_prebuilt_skeleton(chapter: int) -> list[dict]:
    """读 plot 各 stage 预建的分拍底稿（beats）拼写作骨架；任一 stage 缺拍/有空拍即报错。"""
    _title, stages = fetch_chapter_outline(chapter)
    segs: list[dict] = []
    for s in stages or []:
        beats = [b for b in (s.get("beats") or []) if isinstance(b, dict)]
        if not beats or any(not str(b.get("text") or "").strip() for b in beats):
            raise SkeletonNotBuiltError(
                f"第 {chapter} 章 stage {s.get('stage_num')} 尚未分拍扩写——"
                f"请先在对话里扩写第 {chapter} 章骨架（skeleton-expansion）。"
            )
        seg = dict(s)
        seg["description"] = str(s.get("text", "") or "").strip()  #粗大纲留给进入态 seed
        seg["beats"] = beats
        segs.append(seg)
    if not segs:
        raise SkeletonNotBuiltError(f"第 {chapter} 章无 plot/stages，无法写作。")
    return segs


_STATE_LINE = re.compile(r"^\s*(?P<name>[^：:\n]+?)\s*[：:]\s*(?P<body>.+?)\s*$")


def _parse_state_lines(
    block: str, roster: set[str]
) -> tuple[dict[str, str], list[str]]:
    """Parse `name: text` line → ({sitename: text}, [unattributable source line])."""
    attributed: dict[str, str] = {}
    residual: list[str] = []
    for raw in block.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _STATE_LINE.match(line)
        if m and m.group("name") in roster:
            attributed[m.group("name")] = m.group("body").strip()
        else:
            residual.append(line)
    return attributed, residual


def merge_state_blocks(
    psych_block: str, phys_block: str, *, characters: list[str]
) -> str:
    """
Interlace the two pieces "Name: Psychology" and "Name: Physiology; Clothing" according to the presence list to form `### Name/-Psychology/-Physiology/Posture`."""
    roster = set(characters)
    psy, psy_residual = _parse_state_lines(psych_block, roster)
    phy, phy_residual = _parse_state_lines(phys_block, roster)

    blocks: list[str] = []
    for name in characters:
        p = psy.get(name, "")
        f = phy.get(name, "")
        if not p and not f:
            continue
        if p and not f:
            logger.warning("[state-merge] 在场角色 {} 缺物理状态行（滚动产出未覆盖），仅注入心理", name)
        seg_lines = [f"### {name}"]
        if p:
            seg_lines.append(f"- 心理：{p}")
        if f:
            seg_lines.append(f"- 生理/姿态：{f}")
        blocks.append("\n".join(seg_lines))

    for line in phy_residual:
        if _STATE_LINE.match(line):
            logger.warning("[state-merge] 物理状态出现名单外角色行「{}」，原样保留", line)
    residual = psy_residual + phy_residual
    if residual:
        blocks.append("\n".join(residual))
    return "\n\n".join(blocks).strip()


@dataclass
class BeatDerivation:
    """Beat-by-beat lightweight feedforward product: rolling state + neutral outline (including ending freeze frame)."""
    running: str
    recap: str


_RECAP_MARK = "【梗概】"
_STATE_MARK = "【状态】"


def parse_beat_derivation(raw: str, *, prior: str) -> BeatDerivation:
    """
The original reply to split roll is (running, recap)."""
    text = (raw or "").strip()
    if not text:
        return BeatDerivation(running=prior, recap="")
    if _RECAP_MARK in text:
        head, _, tail = text.partition(_RECAP_MARK)
        running = head.replace(_STATE_MARK, "").strip()
        return BeatDerivation(running=running or prior, recap=tail.strip())
    return BeatDerivation(running=text.replace(_STATE_MARK, "").strip(), recap="")
