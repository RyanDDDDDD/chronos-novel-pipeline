"""Chapter skeleton -> manuscript expansion analysis (setup_chat beats vs author output).

Beat dialogue design (once a separate `dialogue` field) is now woven directly into
`beat.text` at construction time (beat-dialogue-design plot-extension), so beat size
is just `text` length -- no separate dialogue-chars breakdown anymore."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from utils.paths import author_loop_journal_path, get_chapter_dir, plot_library_path


def cn_chars(text: str) -> int:
    """Character count excluding whitespace (project-wide 字数 convention)."""
    return len(re.sub(r"\s+", "", text))


def prose_from_manuscript(md: str) -> str:
    """Keep only 【过程描述】 narrative blocks from assembled chapter markdown."""
    parts: list[str] = []
    for block in re.split(r"\n---\n", md):
        m = re.search(r"- \*\*【过程描述】\*\*：(.*)", block, re.DOTALL)
        if m:
            parts.append(m.group(1).strip())
    return "\n\n".join(parts)


@dataclass
class BeatSkeleton:
    stage_num: int
    beat_index: int
    beat_chars: int


@dataclass
class StageExpandReport:
    stage_num: int
    beat_count: int
    beat_chars: int
    intent_chars: int | None = None
    segment_chars: int | None = None

    @property
    def segment_ratio(self) -> float | None:
        if self.intent_chars and self.segment_chars is not None:
            return self.segment_chars / self.intent_chars
        return None


@dataclass
class ChapterExpandReport:
    chapter: int
    title: str
    beats: list[BeatSkeleton] = field(default_factory=list)
    stages: list[StageExpandReport] = field(default_factory=list)
    prose_chars: int = 0
    full_chars: int = 0
    has_manuscript: bool = False
    has_journal: bool = False

    @property
    def beat_chars(self) -> int:
        return sum(b.beat_chars for b in self.beats)

    @property
    def meta_chars(self) -> int:
        return max(0, self.full_chars - self.prose_chars)

    @property
    def intent_chars(self) -> int | None:
        if not self.has_journal:
            return None
        return sum(s.intent_chars or 0 for s in self.stages)

    @property
    def segment_chars(self) -> int | None:
        if not self.has_journal:
            return None
        total = sum(s.segment_chars or 0 for s in self.stages)
        return total

    def ratio(self, num: int, den: int) -> float | None:
        return num / den if den else None


def _load_plot() -> list[dict]:
    path = Path(plot_library_path())
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [c for c in data if isinstance(c, dict)]


def _manuscript_path(chapter: int) -> Path:
    return Path(get_chapter_dir(chapter)) / f"第{chapter}章_主笔.md"


def _journal_path(chapter: int) -> Path:
    return Path(author_loop_journal_path(chapter))


def _journal_segments(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    segs: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if obj.get("type") == "author_loop_segment":
            segs.append(obj)
    return segs


def analyze_chapter(chapter_data: dict) -> ChapterExpandReport:
    chapter = int(chapter_data.get("chapter") or 0)
    report = ChapterExpandReport(chapter=chapter, title=str(chapter_data.get("title") or ""))

    stage_map: dict[int, StageExpandReport] = {}
    for stage in chapter_data.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        sn = int(stage.get("stage_num") or 0)
        st = stage_map.setdefault(
            sn,
            StageExpandReport(stage_num=sn, beat_count=0, beat_chars=0),
        )
        for i, beat in enumerate(stage.get("beats") or []):
            if not isinstance(beat, dict):
                continue
            bt = str(beat.get("text") or "").strip()
            bc = cn_chars(bt)
            report.beats.append(BeatSkeleton(sn, i, bc))
            st.beat_count += 1
            st.beat_chars += bc

    journal_segs = _journal_segments(_journal_path(chapter))
    if journal_segs:
        report.has_journal = True
        for i, seg in enumerate(journal_segs):
            sn = i + 1
            st = stage_map.setdefault(
                sn,
                StageExpandReport(stage_num=sn, beat_count=0, beat_chars=0),
            )
            st.intent_chars = cn_chars(str(seg.get("intent") or ""))
            st.segment_chars = cn_chars(str(seg.get("text") or ""))

    ms_path = _manuscript_path(chapter)
    if ms_path.is_file():
        md = ms_path.read_text(encoding="utf-8")
        report.has_manuscript = True
        report.full_chars = cn_chars(md)
        report.prose_chars = cn_chars(prose_from_manuscript(md))

    report.stages = sorted(stage_map.values(), key=lambda s: s.stage_num)
    return report


def list_analyzable_chapters() -> list[int]:
    chapters: list[int] = []
    for ch in _load_plot():
        num = ch.get("chapter")
        if not isinstance(num, int):
            continue
        stages = ch.get("stages") or []
        has_beats = any(
            isinstance(s, dict) and isinstance(s.get("beats"), list) and s["beats"]
            for s in stages
        )
        if has_beats:
            chapters.append(num)
    return sorted(chapters)


def analyze_chapters(chapter_nums: list[int] | None = None) -> list[ChapterExpandReport]:
    by_num = {int(c["chapter"]): c for c in _load_plot() if isinstance(c.get("chapter"), int)}
    nums = chapter_nums if chapter_nums is not None else list_analyzable_chapters()
    return [analyze_chapter(by_num[n]) for n in nums if n in by_num]


def _fmt_ratio(r: float | None) -> str:
    return f"{r:.2f}x" if r is not None else "—"


def _fmt_delta(delta: int | None) -> str:
    if delta is None:
        return "—"
    return f"{delta:+,}"


def format_chapter_report(report: ChapterExpandReport, *, detail: bool = False) -> str:
    lines = [
        f"第 {report.chapter} 章 · {report.title or '（无标题）'}",
        f"  stage {len(report.stages)} · 拍 {len(report.beats)}",
        f"  底稿: {report.beat_chars:,}",
    ]
    if report.has_manuscript:
        lines.append(
            f"  成稿正文: {report.prose_chars:,}  成稿全文: {report.full_chars:,}  "
            f"(元数据 {report.meta_chars:,})"
        )
        lines.append(
            f"  底稿→正文: {_fmt_delta(report.prose_chars - report.beat_chars)}  "
            f"{_fmt_ratio(report.ratio(report.prose_chars, report.beat_chars))}  |  "
            f"底稿→全文: {_fmt_delta(report.full_chars - report.beat_chars)}  "
            f"{_fmt_ratio(report.ratio(report.full_chars, report.beat_chars))}"
        )
    else:
        lines.append("  成稿: （未找到主笔稿）")

    if report.has_journal and report.intent_chars is not None and report.segment_chars is not None:
        lines.append(
            f"  journal intent→segment: {report.intent_chars:,}→{report.segment_chars:,}  "
            f"{_fmt_delta(report.segment_chars - report.intent_chars)}  "
            f"{_fmt_ratio(report.ratio(report.segment_chars, report.intent_chars))}"
        )
    elif not report.has_journal:
        lines.append("  journal: （未找到）")

    if detail and report.stages:
        lines.append("  --- 按 stage ---")
        for st in report.stages:
            base = f"    stage{st.stage_num}: {st.beat_count}拍  底稿{st.beat_chars:,}"
            if st.intent_chars is not None and st.segment_chars is not None:
                base += (
                    f"  |  intent{st.intent_chars:,}→正文{st.segment_chars:,}  "
                    f"{_fmt_ratio(st.segment_ratio)}"
                )
            lines.append(base)

    if detail and report.beats:
        lines.append("  --- 按拍 ---")
        for b in report.beats:
            lines.append(f"    stage{b.stage_num}拍{b.beat_index}: 底稿{b.beat_chars}")

    return "\n".join(lines)


def format_summary_table(reports: list[ChapterExpandReport]) -> str:
    hdr = (
        f"{'章':>3}  {'拍':>3}  {'底稿':>7}  "
        f"{'正文':>7}  {'全文':>7}  {'底→正':>6}"
    )
    sep = "─" * len(hdr.encode("utf-8"))
    rows = [hdr, sep]
    for r in reports:
        if not r.has_manuscript:
            rows.append(
                f"{r.chapter:>3}  {len(r.beats):>3}  {r.beat_chars:>7,}  "
                f"{'—':>7}  {'—':>7}  {'—':>6}"
            )
            continue
        rows.append(
            f"{r.chapter:>3}  {len(r.beats):>3}  {r.beat_chars:>7,}  "
            f"{r.prose_chars:>7,}  {r.full_chars:>7,}  "
            f"{_fmt_ratio(r.ratio(r.prose_chars, r.beat_chars)):>6}"
        )
    return "\n".join(rows)


def format_markdown_report(reports: list[ChapterExpandReport], *, detail: bool = False) -> str:
    parts = ["# 扩写增效报告", ""]
    if len(reports) > 1:
        parts.extend([format_summary_table(reports), ""])
    for r in reports:
        parts.append("## " + (r.title or f"第{r.chapter}章"))
        parts.append("")
        parts.append("```")
        parts.append(format_chapter_report(r, detail=detail))
        parts.append("```")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"
