"""Extracts + persists a character's visual tag cache, then chains into portrait
generation. Kept as its own scheduled job (not inlined into add_character) so it
shares the debounced SCHEDULER dedup mechanism the rest of this module family uses --
but always chains forward into schedule_character_portrait_generation on completion
rather than being fired in parallel with it, so there is no ordering race between the
two jobs."""
from __future__ import annotations

from utils.paths import use_novel


def schedule_extract_visual_tags(name: str) -> None:
    from api.services.scheduler import SCHEDULER
    from utils.paths import active_novel_id

    novel_id = active_novel_id()
    SCHEDULER.schedule_once(
        f"character-visual-tags:{novel_id}:{name}", 0.0,
        lambda: _run_extract_visual_tags(novel_id, name), dedup=True,
    )


async def _run_extract_visual_tags(novel_id: str, name: str) -> None:
    from media.portrait.visual_tags import extract_and_persist_visual_tags
    from repositories import get_lore_repo

    from engine.setup_chat.character_portrait_generation import (
        schedule_character_portrait_generation,
    )
    from engine.setup_chat.tools import _name_key

    with use_novel(novel_id):
        roster = get_lore_repo().list_raw()
        char = next((c for c in roster if isinstance(c, dict) and _name_key(c) == name), None)
    if char is None:
        return  # 提取排队期间角色被删了，静默结束（跟 _run_portrait_generation 现有策略一致）

    await extract_and_persist_visual_tags(novel_id, name, char)
    schedule_character_portrait_generation(name)
