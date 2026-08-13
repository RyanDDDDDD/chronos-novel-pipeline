"""plot_library.json 手动编辑章级元数据：title 改名。与 patch_chapter（stage 级 ops
+ core_xp）分开——title 不属于 PatchChapterOpArgs 覆盖的字段。"""
from __future__ import annotations


def patch_plot_chapter_title(chapter: int, title: str) -> tuple[bool, str]:
    from repositories import get_plot_repo

    chapters = get_plot_repo().list_raw()
    ch = next((c for c in chapters if isinstance(c, dict) and c.get("chapter") == chapter), None)
    if ch is None:
        return False, f"第 {chapter} 章不存在于 plot。"
    ch["title"] = title
    try:
        get_plot_repo().save_all(chapters)
    except OSError as exc:
        return False, f"写盘失败：{exc}"
    return True, f"已更新第 {chapter} 章标题。"
