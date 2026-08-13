"""Pipeline Table of Contents: Chapter Listing and Disk Cleanup."""
from __future__ import annotations

import json
import re
import shutil as _shutil
from pathlib import Path

from api.services.paths import chapters_dir, plot_library_path

_CHAPTER_DIR_RE = re.compile(r"^第(\d+)章$")
_EXCLUDED_DISK_CHAPTERS = frozenset({999})


def author_manuscript_path(chapter: int) -> Path:
    """The path of the entire chapter saved by the main author (consistent with the save_author_loop_chapter placement rule)."""
    return chapters_dir() / f"第{chapter}章" / f"第{chapter}章_主笔.md"


def list_author_manuscripts() -> list[dict]:
    """
Scan the disk and return the chapter numbers (in ascending order) that have been written by the main author."""
    cd = chapters_dir()
    if not cd.is_dir():
        return []
    out: list[dict] = []
    for child in cd.iterdir():
        m = _CHAPTER_DIR_RE.match(child.name)
        if not m:
            continue
        ch = int(m.group(1))
        path = author_manuscript_path(ch)
        if path.is_file():
            out.append({"chapter": ch, "path": str(path)})
    return sorted(out, key=lambda x: x["chapter"])


def read_author_manuscript(chapter: int) -> dict:
    """Read the author's draft of the specified chapter; no file → FileNotFoundError."""
    if chapter < 1:
        raise ValueError("chapter 须 ≥ 1")
    path = author_manuscript_path(chapter)
    if not path.is_file():
        raise FileNotFoundError(f"第 {chapter} 章暂无保存的主笔成稿")
    return {"chapter": chapter, "path": str(path), "content": path.read_text(encoding="utf-8")}


def list_chapters() -> list[dict]:
    """
Merge the plot library and the disk chapter directory to return a chapter list that can be selected by the front-end drop-down."""
    meta: dict[int, str | None] = {}

    plp = plot_library_path()
    if plp.is_file():
        try:
            plots = json.loads(plp.read_text(encoding="utf-8"))
            if isinstance(plots, list):
                for entry in plots:
                    if not isinstance(entry, dict):
                        continue
                    ch = entry.get("chapter")
                    if isinstance(ch, int) and ch > 0:
                        title = entry.get("title")
                        meta[ch] = title if isinstance(title, str) else None
        except (json.JSONDecodeError, OSError):
            pass

    plot_nums = set(meta)
    cd = chapters_dir()
    if cd.is_dir():
        for child in cd.iterdir():
            m = _CHAPTER_DIR_RE.match(child.name)
            if not m:
                continue
            ch = int(m.group(1))
            if ch in plot_nums or ch in _EXCLUDED_DISK_CHAPTERS:
                continue
            progress = child / "temp" / ".pipeline_progress.json"
            if progress.is_file():
                meta[ch] = None

    if not meta:
        return [{"chapter": 1, "title": None}]

    return [{"chapter": ch, "title": meta[ch]} for ch in sorted(meta)]


def clear_chapter_disk(chapter: int) -> None:
    """Delete the disk products and temp/ of each chapter; keep the character files under characters/.

    Product cleanup: Delete all .md in the chapter directory (including the file names left by the old pipeline),
    No longer relies on the current manifest output template enum."""

    #Parse to the chapters of the active novel (consistent with runtime get_chapter_dir);
    #The old PROJECT_ROOT/chapters static path will clear the wrong directory after multiple novels are isolated.
    #As a result, the real .pipeline_progress.json remains, and "completes" immediately after resetting and restarting.
    chapter_dir = chapters_dir() / f"第{chapter}章"
    if not chapter_dir.exists():
        return

    for md in chapter_dir.rglob("*.md"):
        md.unlink()

    temp_dir = chapter_dir / "temp"
    if temp_dir.exists():
        _shutil.rmtree(temp_dir)
