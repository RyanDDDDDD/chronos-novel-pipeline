"""world_bible.json 手动编辑单字段合并写：设定页手动编辑入口用，绕开 setup_chat 对话。

与 writer.py 的整文档覆盖（construct_world/refine_world）不同：只合并一个 key，
其余字段原样保留。没有现成的细粒度写工具可复用（construct_world 只做整文档覆盖），
因此这里是新写的最小实现，不接 LLM 校验。"""
from __future__ import annotations

from typing import Any

_SCALAR_FIELDS = {"tone", "background"}
_LIST_FIELDS = {"factions", "geography", "races", "core_themes", "power_system"}
# Every _LIST_FIELDS entry is now scanned -- core_themes participates via its optional per-entry
# keywords (see engine/memory_recall/recall.py); editing it must still invalidate the cache like
# the others so a renamed entry/updated keywords take effect on the next scan.
_VOCAB_SCANNED_FIELDS = {"factions", "geography", "races", "power_system", "core_themes"}


def patch_world_field(field: str, value: Any) -> tuple[bool, str]:
    if field not in _SCALAR_FIELDS and field not in _LIST_FIELDS:
        return False, f"未知字段「{field}」。"
    from repositories import get_world_repo

    doc = dict(get_world_repo().get() or {})
    doc[field] = value
    try:
        get_world_repo().save(doc)
    except OSError as exc:
        return False, f"写盘失败：{exc}"
    if field in _VOCAB_SCANNED_FIELDS:
        # Adding/renaming a named entry here changes what recall_relevant_context's entity scan
        # should recognize -- without this, the process-level Aho-Corasick cache in
        # entity_index.py keeps the pre-edit names until a novel switch or restart, silently
        # breaking recall for anything just added/renamed.
        from engine.memory_recall.entity_index import invalidate_entity_vocab_cache

        invalidate_entity_vocab_cache()
    return True, f"已更新世界观「{field}」。"
