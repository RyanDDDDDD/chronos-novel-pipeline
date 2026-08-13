"""Summary of existing settings for the current novel: only inject llm_input_messages, not checkpoint/front-end."""
from __future__ import annotations

from engine.setup.chat_summary import render_world_chat

_STATUS_HEADER_PREFIX = "## 当前小说构建状态"

_CONTEXT_HEADER = (
    f"{_STATUS_HEADER_PREFIX}\n"
    "以下以**磁盘现稿**为准，每轮推理前自动注入（清空对话后仍有效）；精修须延续已有设定，"
    "勿因对话历史为空而假设尚未构建，也不要未经确认就整盘重做世界观。"
    "需要某域完整文字摘要时再调 read_setup_summary(world|cast|plot)。"
)
# Legacy prefix — assistant text from older sessions may still contain this block.
_LEGACY_CONTEXT_HEADER_PREFIX = "## 当前小说已有设定"


def strip_novel_context_for_display(content: str) -> str:
    """Remove the novel setup injection block in model retelling."""
    for prefix in (_STATUS_HEADER_PREFIX, _LEGACY_CONTEXT_HEADER_PREFIX):
        if prefix in content:
            content = _strip_block_starting_with(content, prefix)
    return content


def _strip_block_starting_with(content: str, prefix: str) -> str:
    lines = content.split("\n")
    if not lines or not lines[0].strip().startswith(prefix):
        return content
    i = 1
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("- "):
            i += 1
            continue
        if stripped.startswith("###"):
            i += 1
            continue
        if line.startswith("  "):
            i += 1
            continue
        if "：" in line[:40]:
            i += 1
            continue
        # Explainer paragraph glued to the ## header (before status bullets).
        if i == 1:
            i += 1
            continue
        break
    return "\n".join(lines[i:]).lstrip()


def _world_built() -> bool:
    from repositories import get_world_repo

    from engine.setup.world.validator import validate_world_bible

    wb = get_world_repo().get()
    return isinstance(wb, dict) and bool(wb) and not validate_world_bible(wb)


def _cast_roster() -> list[str]:
    from repositories import get_lore_repo

    names: list[str] = []
    for char in get_lore_repo().list_raw():
        if not isinstance(char, dict):
            continue
        name = str(char.get("given_name") or char.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _plot_chapter_nums() -> list[int]:
    from repositories import get_plot_repo

    nums: list[int] = []
    for ch in get_plot_repo().list_raw():
        if isinstance(ch, dict) and isinstance(ch.get("chapter"), int):
            nums.append(int(ch["chapter"]))
    return sorted(set(nums))


def _format_cast_status(names: list[str]) -> str:
    if not names:
        return "- 角色：未建"
    if len(names) <= 6:
        detail = f"（{'、'.join(names)}）"
    else:
        detail = f"（{'、'.join(names[:6])} 等 {len(names)} 人）"
    return f"- 角色：{len(names)} 人{detail}"


def _format_plot_status(chapters: list[int]) -> str:
    if not chapters:
        return "- 剧情：未建"
    if len(chapters) <= 5:
        detail = "、".join(f"第{n}章" for n in chapters)
        return f"- 剧情：{len(chapters)} 章（{detail}）"
    return f"- 剧情：{len(chapters)} 章（第{chapters[0]}–{chapters[-1]}章）"


def build_novel_setup_status() -> str:
    """Compact artifact-derived status: world / cast / plot — always computable from disk."""
    world_line = f"- 世界观：{'已建' if _world_built() else '未建'}"
    cast_line = _format_cast_status(_cast_roster())
    plot_line = _format_plot_status(_plot_chapter_nums())
    return "\n".join([world_line, cast_line, plot_line])


def build_inherited_setup_context() -> str:
    """Per-turn injection: build status overview + optional world summary when world exists."""
    from repositories import get_world_repo

    parts: list[str] = [_CONTEXT_HEADER, "", build_novel_setup_status()]
    wb = get_world_repo().get()
    if isinstance(wb, dict) and wb:
        body = render_world_chat(wb)
        if body and body != "（空）":
            parts.extend(["", "### 世界观摘要", body])
    return "\n".join(parts)
