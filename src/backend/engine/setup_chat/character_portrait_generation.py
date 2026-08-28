"""Background portrait generation -- reads the cached portrait_visual_tags on the
character record (populated by character_visual_tags.py, chained from
add_character/edit_character) and assembles the final prompt. Falls back to computing
the cache inline when it's missing (manual regeneration on a character that predates
this cache, or an edit that changed appearance fields before the extraction job ran)
-- see media.portrait.visual_tags.extract_and_persist_visual_tags."""
from __future__ import annotations

from media.portrait.prompt_builder import build_portrait_prompt
from media.portrait.provider_factory import build_image_provider
from media.portrait.service import store_portrait
from utils.paths import use_novel


def _resolve_image_gen_entry(novel_id: str) -> dict | None:
    from domain.model_catalog import load_custom_models

    from engine.modes.author_loop_skill_prefs import load_dialogue_prefs

    with use_novel(novel_id):
        node_params = load_dialogue_prefs()["import_llm_params"].get("character_portrait", {})
    model_ref = node_params.get("model_ref") if isinstance(node_params, dict) else None

    image_gen_entries = [m for m in load_custom_models() if m.get("provider") == "image_gen"]
    if model_ref:
        return next((m for m in image_gen_entries if m.get("id") == model_ref), None)
    return image_gen_entries[0] if len(image_gen_entries) == 1 else None


def schedule_character_portrait_generation(name: str) -> None:
    from api.services.scheduler import SCHEDULER
    from utils.paths import active_novel_id

    novel_id = active_novel_id()
    SCHEDULER.schedule_once(
        f"character-portrait:{novel_id}:{name}", 0.0,
        lambda: _run_portrait_generation(novel_id, name), dedup=True,
    )


async def _run_portrait_generation(novel_id: str, name: str) -> None:
    from repositories import get_lore_repo

    from engine.setup_chat.tools import _name_key

    with use_novel(novel_id):
        roster = get_lore_repo().list_raw()
        char = next((c for c in roster if isinstance(c, dict) and _name_key(c) == name), None)
        if char is None:
            return  # 生成排队期间角色被删了，静默结束

        from api.routes import _hub_instance

        await _hub_instance().broadcast(
            {"type": "portrait_generation_started", "novel_id": novel_id, "character": name}
        )
        entry = _resolve_image_gen_entry(novel_id)
        if entry is None:
            await _hub_instance().broadcast(
                {"type": "portrait_generation_done", "novel_id": novel_id, "character": name,
                 "error": "未配置生图模型，请到「流水线→对话」页为「立绘生成」节点选择模型"}
            )
            return
        try:
            tags = char.get("portrait_visual_tags")
            if not isinstance(tags, str) or not tags:
                from media.portrait.visual_tags import extract_and_persist_visual_tags

                tags = await extract_and_persist_visual_tags(novel_id, name, char)

            prompt, negative_prompt = build_portrait_prompt(tags, entry.get("base_model"))
            provider = build_image_provider(entry)

            from media.portrait.gate import IMAGE_GEN_GATE

            image_bytes = await IMAGE_GEN_GATE.run(
                lambda: provider.generate(prompt, negative_prompt=negative_prompt)
            )

            relative = store_portrait(name, image_bytes)
        except Exception as exc:  # noqa: BLE001 -- terminal after gate exhausts retries;
            # broadcast so the user can still retry manually from the UI.
            await _hub_instance().broadcast(
                {"type": "portrait_generation_done", "novel_id": novel_id,
                 "character": name, "error": str(exc)}
            )
            return

    await _hub_instance().broadcast(
        {"type": "portrait_generation_done", "novel_id": novel_id,
         "character": name, "portrait_path": relative}
    )
