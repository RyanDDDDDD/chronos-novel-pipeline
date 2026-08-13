"""Pipeline state type and chapter assembly function.

The state type used by the main cycle context (hook type annotation) + the chapter assembly pure function.
The LangGraph reducer (merge_outputs/max_step/replace_character_archives) and L3 validation have been removed with the DAG."""

from typing import NotRequired, TypedDict

#── State type (type annotation for hook context stage; non-execution orchestration) ──────────────────────────

class SegmentState(TypedDict):
    index: int
    title: str
    location: str
    text: str                            #Paragraph content: when init = original outline, gradually covered by modifications by each agent
    characters: NotRequired[list[str]]   #The name of the character present when slicing (possibly none)
    stage_num: NotRequired[int]          #真实 stage 序号（1-based）；缺省回退用 index+1（两者在"一拍一 stage"时才相等）


class PipelineState(TypedDict):
    chapter: int
    segments: list[SegmentState]


#──Chapter Assembly───────────────────────────────────────────────────────────

_HANZI = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九"]


def hanzi_num(n: int) -> str:
    if 1 <= n <= 9:
        return _HANZI[n]
    if n == 10:
        return "十"
    if 11 <= n <= 19:
        return f"十{_HANZI[n - 10]}"
    return str(n)


def assemble_chapter_file(chapter: int, segments: list, md_block_provider=None) -> str:
    parts = []
    for seg in segments:
        title = seg.get("title", "")
        location = seg.get("location", "")
        text = seg.get("text", "")
        if title:
            ordinal = seg.get("stage_num") or (seg["index"] + 1)
            header = f"### 【阶段{hanzi_num(ordinal)}：{title}】"
            block = header
            if location:
                block += f"\n\n- **【地点场景】**：{location}"
            extra = md_block_provider(seg["index"]) if md_block_provider else ""
            if extra and extra.strip():
                block += f"\n\n{extra.rstrip()}"
            block += f"\n\n- **【过程描述】**：{text}"
            parts.append(block)
        else:
            parts.append(text)
    return "\n\n---\n\n".join(parts)
