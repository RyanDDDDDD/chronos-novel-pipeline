"""scripts/migrate_world_power_system_core_themes.py

One-off migration: converts legacy world_bible power_system (free-text str) and core_themes
(list[str]) into the named-list shape (list[{name,desc}]) needed by entity_index.py/recall.py's
recall wiring. Skips novels already in the new shape. Prints old-vs-new for every migrated novel
before writing so results can be checked after the fact; a single novel's LLM failure is skipped,
not fatal to the whole run. See
docs/superpowers/specs/2026-07-24-sandbox-lore-recall-and-composer-recognition-design.md.

Usage: uv run python scripts/migrate_world_power_system_core_themes.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

CallLLM = Callable[[str, str], Awaitable[str]]

_PROMPT_TEMPLATE = """把下面这份世界观里的「力量体系」和「核心主题」拆解成具名条目列表。

## 力量体系原文
{power_system}

## 核心主题原有列表
{core_themes}

## 要求
- power_system 拆成 [{{"name": "...", "desc": "..."}}, ...]，每条是一个独立的力量/机制概念
  （如境界等级、力量设定这类专有机制各自成一条，desc 写清楚运作规则/代价/限制）。
- core_themes 保留原有主题词作为 name，desc 写该主题在本书具体如何呈现。
- 只输出一个 JSON 对象：{{"power_system": [...], "core_themes": [...]}}，不要输出其它文字。
"""


def _build_call_llm() -> CallLLM:
    from langchain_core.messages import HumanMessage, SystemMessage
    from llm.factory import get_cloud_llm

    llm = get_cloud_llm()

    async def call_llm(system: str, user: str) -> str:
        resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        return content.strip()

    return call_llm


def _is_legacy(bible: dict[str, Any]) -> bool:
    power_system = bible.get("power_system")
    core_themes = bible.get("core_themes") or []
    return isinstance(power_system, str) or any(isinstance(t, str) for t in core_themes)


async def _migrate_one(nid: str, call_llm: CallLLM) -> dict[str, Any] | None:
    import repositories
    from engine.execution.embed_json import parse_embed_json
    from utils.paths import use_novel

    with use_novel(nid):
        repositories.reset_repositories()
        bible = repositories.get_world_repo().get() or {}
        if not _is_legacy(bible):
            return None
        prompt = _PROMPT_TEMPLATE.format(
            power_system=bible.get("power_system") or "（空）",
            core_themes=json.dumps(bible.get("core_themes") or [], ensure_ascii=False),
        )
        raw = await call_llm("你是世界观设定拆解助手。", prompt)
        objs = parse_embed_json(raw)
        if not objs:
            raise ValueError(f"LLM 输出无法解析出 JSON：{raw[:200]!r}")
        parsed = objs[0]
        new_power_system = parsed.get("power_system")
        new_core_themes = parsed.get("core_themes")
        if not isinstance(new_power_system, list) or not new_power_system:
            raise ValueError("LLM 未返回有效的 power_system 列表")
        if not isinstance(new_core_themes, list) or not new_core_themes:
            raise ValueError("LLM 未返回有效的 core_themes 列表")
        result = {
            "old_power_system": bible.get("power_system"),
            "old_core_themes": bible.get("core_themes"),
            "new_power_system": new_power_system,
            "new_core_themes": new_core_themes,
        }
        bible["power_system"] = new_power_system
        bible["core_themes"] = new_core_themes
        repositories.get_world_repo().save(bible)
        return result


async def migrate_all(call_llm: CallLLM | None = None) -> dict[str, Any]:
    from api.services.novels import list_novels
    from loguru import logger

    if call_llm is None:
        call_llm = _build_call_llm()

    migrated: dict[str, dict] = {}
    failed: list[str] = []
    for novel in list_novels():
        nid = novel["id"]
        try:
            result = await _migrate_one(nid, call_llm)
        except Exception as exc:  # noqa: BLE001 - isolate one novel's failure from the rest of the batch
            logger.warning("[migrate_world] {} 迁移失败，跳过：{}", nid, exc)
            failed.append(nid)
            continue
        if result is not None:
            migrated[nid] = result
    return {"migrated": migrated, "failed": failed}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    result = asyncio.run(migrate_all())
    migrated = result["migrated"]
    failed = result["failed"]
    if not migrated and not failed:
        print("没有找到需要迁移的旧格式小说。")
        return
    for nid, diff in migrated.items():
        print(f"\n=== {nid} ===")
        print(f"旧 power_system：{diff['old_power_system']}")
        print(f"新 power_system：{json.dumps(diff['new_power_system'], ensure_ascii=False, indent=2)}")
        print(f"旧 core_themes：{diff['old_core_themes']}")
        print(f"新 core_themes：{json.dumps(diff['new_core_themes'], ensure_ascii=False, indent=2)}")
    if migrated:
        print(f"\n已迁移 {len(migrated)} 部小说。")
    if failed:
        print(f"迁移失败 {len(failed)} 部小说：{', '.join(failed)}（已跳过，详见上方日志）")


if __name__ == "__main__":
    main()
