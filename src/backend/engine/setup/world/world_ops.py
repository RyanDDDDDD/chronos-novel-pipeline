"""Per-dimension read/write helpers for world_bible (setup-chat dimension tools + settings UI)."""
from __future__ import annotations

from typing import Any

from engine.setup.world.validator import validate_world_bible

WORLD_SCALAR_FIELDS = frozenset({"tone", "background"})
WORLD_LIST_FIELDS = frozenset({"factions", "geography", "races", "power_system", "core_themes"})
KEYWORDS_LIST_FIELDS = frozenset({"power_system", "core_themes"})
_VOCAB_SCANNED_FIELDS = frozenset({"factions", "geography", "races", "power_system", "core_themes"})

_LIST_LABELS: dict[str, str] = {
    "factions": "势力",
    "geography": "地理",
    "races": "种族",
    "power_system": "力量体系",
    "core_themes": "核心主题",
}

_SCALAR_LABELS: dict[str, str] = {
    "background": "世界背景",
    "tone": "基调",
}


def world_bible_complete(bible: dict[str, Any]) -> bool:
    return not validate_world_bible(bible)


def _load_doc_with_version() -> tuple[dict[str, Any], int]:
    from repositories import get_world_repo

    result = get_world_repo().get_with_version()
    if result is None:
        return {}, 0
    doc, version = result
    return dict(doc), version


def _load_doc() -> dict[str, Any]:
    doc, _version = _load_doc_with_version()
    return doc


def _save_doc(doc: dict[str, Any], expected_version: int) -> tuple[bool, str]:
    from repositories import get_world_repo

    try:
        new_version = get_world_repo().save_if_version_matches(doc, expected_version)
    except OSError as exc:
        return False, f"写盘失败：{exc}"
    if new_version is None:
        return False, "世界观在你读取之后已被修改，写入已取消。请重新读取最新数据后再改。"
    return True, ""


def _invalidate_vocab_if_needed(field: str) -> None:
    if field not in _VOCAB_SCANNED_FIELDS:
        return
    from engine.memory_recall.entity_index import invalidate_entity_vocab_cache

    invalidate_entity_vocab_cache()


def _scalar_nonempty(doc: dict[str, Any], field: str) -> bool:
    val = doc.get(field)
    return isinstance(val, str) and bool(val.strip())


def _list_items(doc: dict[str, Any], field: str) -> list[dict[str, Any]]:
    items = doc.get(field)
    if not isinstance(items, list):
        return []
    return [it for it in items if isinstance(it, dict)]


def _find_entry_index(items: list[dict[str, Any]], name: str) -> int | None:
    key = name.strip()
    for i, it in enumerate(items):
        if str(it.get("name", "")).strip() == key:
            return i
    return None


def _validate_named_item(field: str, item: dict[str, Any]) -> str | None:
    name = str(item.get("name", "")).strip()
    desc = str(item.get("desc", "")).strip()
    if not name or not desc:
        return f"「{_LIST_LABELS[field]}」条目须同时提供非空 name 与 desc。"
    if field in KEYWORDS_LIST_FIELDS:
        kws = item.get("keywords")
        if kws is not None and not isinstance(kws, list):
            return "keywords 须为字符串列表或省略。"
    return None


def set_scalar_field(field: str, value: str) -> tuple[bool, str, dict[str, Any], int]:
    if field not in WORLD_SCALAR_FIELDS:
        return False, f"未知标量字段「{field}」。", {}, 0
    text = value.strip()
    if not text:
        return False, f"{_SCALAR_LABELS[field]} 不能为空。", {}, 0
    doc, version = _load_doc_with_version()
    if _scalar_nonempty(doc, field):
        return False, f"{_SCALAR_LABELS[field]} 已有内容，请用 refine_world_{field} 修改。", {}, 0
    doc[field] = text
    return True, "", doc, version


def refine_scalar_field(field: str, value: str) -> tuple[bool, str, dict[str, Any], int]:
    if field not in WORLD_SCALAR_FIELDS:
        return False, f"未知标量字段「{field}」。", {}, 0
    text = value.strip()
    if not text:
        return False, f"{_SCALAR_LABELS[field]} 不能为空。", {}, 0
    doc, version = _load_doc_with_version()
    if not _scalar_nonempty(doc, field):
        return False, f"{_SCALAR_LABELS[field]} 尚未构建，请先用 set_world_{field}。", {}, 0
    doc[field] = text
    return True, "", doc, version


def add_list_entry(field: str, item: dict[str, Any]) -> tuple[bool, str, dict[str, Any], int]:
    if field not in WORLD_LIST_FIELDS:
        return False, f"未知列表字段「{field}」。", {}, 0
    err = _validate_named_item(field, item)
    if err:
        return False, err, {}, 0
    name = str(item["name"]).strip()
    doc, version = _load_doc_with_version()
    items = _list_items(doc, field)
    if _find_entry_index(items, name) is not None:
        return False, f"「{_LIST_LABELS[field]}」中已存在「{name}」，请用 edit 修改或换名新增。", {}, 0
    entry: dict[str, Any] = {"name": name, "desc": str(item["desc"]).strip()}
    if field in KEYWORDS_LIST_FIELDS:
        kws = item.get("keywords") or []
        entry["keywords"] = [str(k).strip() for k in kws if str(k).strip()]
    items.append(entry)
    doc[field] = items
    return True, "", doc, version


def edit_list_entry(
    field: str,
    name: str,
    *,
    desc: str,
    keywords: list[str] | None = None,
) -> tuple[bool, str, dict[str, Any], int]:
    if field not in WORLD_LIST_FIELDS:
        return False, f"未知列表字段「{field}」。", {}, 0
    desc_text = desc.strip()
    if not desc_text:
        return False, "desc 不能为空。", {}, 0
    doc, version = _load_doc_with_version()
    items = _list_items(doc, field)
    idx = _find_entry_index(items, name)
    if idx is None:
        return False, f"「{_LIST_LABELS[field]}」中未找到「{name.strip()}」。", {}, 0
    items[idx]["desc"] = desc_text
    if field in KEYWORDS_LIST_FIELDS and keywords is not None:
        items[idx]["keywords"] = [str(k).strip() for k in keywords if str(k).strip()]
    doc[field] = items
    return True, "", doc, version


def remove_list_entry(field: str, name: str) -> tuple[bool, str, dict[str, Any], int]:
    if field not in WORLD_LIST_FIELDS:
        return False, f"未知列表字段「{field}」。", {}, 0
    doc, version = _load_doc_with_version()
    items = _list_items(doc, field)
    idx = _find_entry_index(items, name)
    if idx is None:
        return False, f"「{_LIST_LABELS[field]}」中未找到「{name.strip()}」。", {}, 0
    items.pop(idx)
    doc[field] = items
    return True, "", doc, version


def render_list_field(field: str) -> str:
    if field not in WORLD_LIST_FIELDS:
        return f"未知列表字段「{field}」。"
    doc = _load_doc()
    items = _list_items(doc, field)
    label = _LIST_LABELS[field]
    if not items:
        return f"{label}：尚未添加任何条目。"
    lines = [f"{label}（共 {len(items)} 条）："]
    for it in items:
        name = str(it.get("name", "")).strip()
        desc = str(it.get("desc", "")).strip()
        line = f"  - {name}：{desc}" if desc else f"  - {name}"
        if field in KEYWORDS_LIST_FIELDS:
            kws = it.get("keywords") or []
            if kws:
                line += f"（keywords: {'、'.join(str(k) for k in kws)}）"
        lines.append(line)
    return "\n".join(lines)


def persist_world_doc(
    doc: dict[str, Any], *, changed_field: str, expected_version: int,
) -> tuple[bool, str]:
    ok, err = _save_doc(doc, expected_version)
    if not ok:
        return False, err
    _invalidate_vocab_if_needed(changed_field)
    return True, ""
