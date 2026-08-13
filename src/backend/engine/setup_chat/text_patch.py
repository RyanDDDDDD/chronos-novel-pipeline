"""文内手术式替换：literal/regex + match_policy，供 setup-chat patch_text_fragment 工具复用。"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import StrEnum

_CONTEXT_RADIUS = 40
_MAX_PATTERN_LEN = 500
_MAX_FIND_LEN = 2000


class TextPatchMode(StrEnum):
    LITERAL = "literal"
    REGEX = "regex"


class TextPatchMatchPolicy(StrEnum):
    UNIQUE = "unique"
    FIRST = "first"
    ALL = "all"


@dataclass
class MatchPreview:
    """单次命中在原文中的位置与上下文（供 agent 加长 find）。"""

    occurrence: int
    start: int
    end: int
    context: str


@dataclass
class PatchStepReport:
    mode: str
    find: str
    replace: str
    match_policy: str
    hits: int
    replaced: int
    previews: list[MatchPreview] = field(default_factory=list)
    error: str | None = None


@dataclass
class ApplyPatchesResult:
    ok: bool
    text: str
    steps: list[PatchStepReport]
    error: str | None = None


@dataclass
class TextPatchOp:
    find: str
    replace: str
    mode: TextPatchMode | str = TextPatchMode.LITERAL
    match_policy: TextPatchMatchPolicy | str = TextPatchMatchPolicy.UNIQUE

    def normalized(self) -> TextPatchOp:
        return TextPatchOp(
            mode=TextPatchMode(str(self.mode)),
            find=self.find,
            replace=self.replace,
            match_policy=TextPatchMatchPolicy(str(self.match_policy)),
        )


def _context_snippet(text: str, start: int, end: int) -> str:
    before = text[max(0, start - _CONTEXT_RADIUS) : start]
    matched = text[start:end]
    after = text[end : end + _CONTEXT_RADIUS]
    return f"…{before}【{matched}】{after}…"


def _compile_regex(pattern: str) -> re.Pattern[str]:
    if len(pattern) > _MAX_PATTERN_LEN:
        raise ValueError(f"正则 pattern 过长（>{_MAX_PATTERN_LEN} 字符）")
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"正则无效：{exc}") from exc


def find_match_spans(text: str, *, find: str, mode: TextPatchMode) -> list[tuple[int, int]]:
    """返回非重叠命中区间列表 [(start, end), ...]。"""
    if not find:
        return []
    if len(find) > _MAX_FIND_LEN:
        raise ValueError(f"find 过长（>{_MAX_FIND_LEN} 字符）")
    if mode == TextPatchMode.LITERAL:
        spans: list[tuple[int, int]] = []
        start = 0
        while True:
            idx = text.find(find, start)
            if idx == -1:
                break
            spans.append((idx, idx + len(find)))
            start = idx + len(find)
        return spans
    pat = _compile_regex(find)
    return [(m.start(), m.end()) for m in pat.finditer(text)]


def _spans_for_policy(
    spans: list[tuple[int, int]], policy: TextPatchMatchPolicy,
) -> tuple[list[tuple[int, int]], str | None]:
    if not spans:
        return [], "find 未命中任何内容"
    if policy == TextPatchMatchPolicy.UNIQUE:
        if len(spans) != 1:
            return [], f"find 命中 {len(spans)} 处（要求 unique）；请加长 find 唯一定位，或设 match_policy=all/first"
        return spans, None
    if policy == TextPatchMatchPolicy.FIRST:
        return spans[:1], None
    return spans, None


def _replace_spans(text: str, spans: list[tuple[int, int]], replacement: str) -> str:
    if not spans:
        return text
    out: list[str] = []
    last = 0
    for start, end in sorted(spans, key=lambda s: s[0]):
        out.append(text[last:start])
        out.append(replacement)
        last = end
    out.append(text[last:])
    return "".join(out)


def apply_text_patches(text: str, patches: list[TextPatchOp]) -> ApplyPatchesResult:
    """串行应用补丁；任一步失败则回滚（返回原文 + error）。"""
    original = text
    current = text
    steps: list[PatchStepReport] = []
    for raw in patches:
        op = raw.normalized()
        #normalized() 在运行时把 mode/match_policy 转成了真枚举，但字段标注仍是
        #`TextPatchMode | str`（要接 agent 传来的裸字符串），mypy 推不出已收窄——
        #这里显式转一次，后续统一用这两个局部变量而非 op.mode/op.match_policy。
        mode = TextPatchMode(op.mode)
        match_policy = TextPatchMatchPolicy(op.match_policy)
        try:
            spans = find_match_spans(current, find=op.find, mode=mode)
        except ValueError as exc:
            return ApplyPatchesResult(
                ok=False, text=original, steps=steps, error=str(exc),
            )
        previews = [
            MatchPreview(
                occurrence=i + 1,
                start=s,
                end=e,
                context=_context_snippet(current, s, e),
            )
            for i, (s, e) in enumerate(spans[:8])
        ]
        picked, err = _spans_for_policy(spans, match_policy)
        if err:
            steps.append(PatchStepReport(
                mode=mode.value,
                find=op.find,
                replace=op.replace,
                match_policy=match_policy.value,
                hits=len(spans),
                replaced=0,
                previews=previews,
                error=err,
            ))
            return ApplyPatchesResult(ok=False, text=original, steps=steps, error=err)

        new_text = _replace_spans(current, picked, op.replace)
        if new_text == current:
            err = "替换后与原文相同（无变更）"
            steps.append(PatchStepReport(
                mode=mode.value,
                find=op.find,
                replace=op.replace,
                match_policy=match_policy.value,
                hits=len(spans),
                replaced=0,
                previews=previews,
                error=err,
            ))
            return ApplyPatchesResult(ok=False, text=original, steps=steps, error=err)
        if not new_text.strip() and original.strip():
            err = "替换后文本为空，已拒绝"
            steps.append(PatchStepReport(
                mode=mode.value,
                find=op.find,
                replace=op.replace,
                match_policy=match_policy.value,
                hits=len(spans),
                replaced=len(picked),
                previews=previews,
                error=err,
            ))
            return ApplyPatchesResult(ok=False, text=original, steps=steps, error=err)

        steps.append(PatchStepReport(
            mode=mode.value,
            find=op.find,
            replace=op.replace,
            match_policy=match_policy.value,
            hits=len(spans),
            replaced=len(picked),
            previews=previews,
        ))
        current = new_text
    return ApplyPatchesResult(ok=True, text=current, steps=steps)


def split_manuscript_blocks(md: str) -> list[str]:
    text = (md or "").strip()
    if not text:
        return []
    parts = text.split("\n\n---\n\n")
    return [p.strip() for p in parts if p.strip()]


def join_manuscript_blocks(blocks: list[str]) -> str:
    return "\n\n---\n\n".join(b.strip() for b in blocks if b.strip())


def slice_manuscript_blocks(blocks: list[str], *, stage_num: int, stage_to: int | None = None) -> str:
    if not blocks:
        return ""
    if len(blocks) == 1:
        if stage_num != 1 or (stage_to not in (None, 1)):
            raise ValueError("该章成稿无可切片 stage（仅支持 stage 1）。")
        return blocks[0]
    start = stage_num
    end = stage_to if stage_to is not None else stage_num
    if start < 1 or end < start:
        raise ValueError("stage 范围无效")
    if start > len(blocks) or end > len(blocks):
        raise ValueError(f"stage 超范围：现有 1..{len(blocks)}")
    return join_manuscript_blocks(blocks[start - 1 : end])


def write_manuscript_blocks(chapter: int, blocks: list[str]) -> str:
    from api.services.pipeline_catalog import author_manuscript_path

    path = author_manuscript_path(chapter)
    if not path.is_file():
        raise FileNotFoundError(f"第 {chapter} 章暂无保存的主笔成稿")
    body = join_manuscript_blocks(blocks)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(tmp, path)
    return str(path)


def format_patch_report(
    *,
    label: str,
    result: ApplyPatchesResult,
    dry_run: bool,
    text_preview: str = "",
) -> str:
    lines = [label]
    if dry_run:
        lines[0] += "（dry_run，未写盘）"
    if not result.ok:
        lines.append(f"失败：{result.error}")
    for i, step in enumerate(result.steps, 1):
        status = "✓" if not step.error else "✗"
        lines.append(
            f"{status} 补丁{i} [{step.mode}/{step.match_policy}] "
            f"命中 {step.hits} / 替换 {step.replaced}"
        )
        if step.error:
            lines.append(f"   → {step.error}")
        for pv in step.previews[:5]:
            lines.append(f"   [{pv.occurrence}] {pv.context}")
    if result.ok and text_preview:
        preview = text_preview[:200].replace("\n", " ")
        lines.append(f"变更后开头：{preview}…")
    return "\n".join(lines)
