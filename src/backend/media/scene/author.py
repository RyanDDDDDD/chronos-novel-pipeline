"""Background main-writer per-stage scene-image generation: read a finalized stage's
event_log entry (or its author_loop_state present-characters) from the chapter journal +
each present character's cached appearance tags -> one scene-prompt LLM call -> NovelAI V4.5
generate with one Precise Reference per present character that has a portrait -> store +
WS broadcast.

Serialized behind media.portrait.gate.IMAGE_GEN_GATE (same NovelAI account limit as portrait
and sandbox scene generation). Manual-trigger only (POST /api/author-loop/scene-image)."""
from __future__ import annotations

import asyncio

from loguru import logger
from utils.paths import use_novel

from media.portrait.gate import IMAGE_GEN_GATE
from media.portrait.provider_factory import build_image_provider
from media.scene._shared import (
    _MAX_REFERENCES,
    _character_portrait_bytes,
    _character_visual_tags,
    _resolve_scene_image_entry,
)
from media.scene.author_store import store_author_stage_scene_image
from media.scene.prompt_builder import build_scene_positive
from media.scene.scene_prompt import build_scene_prompt

_CONFIG_KEY = "llm_params"
_NO_MODEL_MSG = (
    "未配置场景生图模型（需 NovelAI V4.5）：先在「服务」页加一个 NovelAI 生图模型，"
    "再到「流水线 → 对话」画布点「场景生图」节点绑定"
)


def schedule_author_stage_scene_image(chapter: int, stage_index: int) -> None:
    from api.services.scheduler import SCHEDULER
    from utils.paths import active_novel_id

    novel_id = active_novel_id()
    SCHEDULER.schedule_once(
        f"author-scene:{novel_id}:{chapter}:{stage_index}", 0.0,
        lambda: generate_author_stage_scene_image(novel_id, chapter, stage_index),
        dedup=True,
        on_timeout=lambda: _on_timeout(novel_id, chapter, stage_index),
    )


async def _on_timeout(novel_id: str, chapter: int, stage_index: int) -> None:
    from api.routes import _hub_instance

    await _hub_instance().broadcast({
        "type": "author_scene_image_done", "novel_id": novel_id, "chapter": chapter,
        "index": stage_index,
        "error": "场景生图超时（排队过久或生成过慢），请稍后重试",
    })


def _stage_memory_entry(chapter: int, stage_index: int) -> dict | None:
    """Pull the scene anchor for one finalized stage from the chapter journal: prefer the last
    author_loop_event_log entry for this stage (summary/time/location/characters); fall back to
    the author_loop_state present-characters when the stage finalized with no extracted events.
    None -> stage not finalized / chapter reset / no present characters."""
    from engine.author_loop.journal import load_events
    from utils.paths import author_loop_journal_path

    events = load_events(author_loop_journal_path(chapter))
    el = [e for e in events
          if e.get("type") == "author_loop_event_log" and e.get("index") == stage_index]
    st = [e for e in events
          if e.get("type") == "author_loop_state" and e.get("index") == stage_index]
    if not el and not st:
        return None

    entries = (el[-1].get("entries") or []) if el else []
    if entries:
        e = entries[-1]
        names = [str(n) for n in (e.get("characters") or [])]
        mem = {
            "summary": e.get("summary") or "", "time": e.get("time") or "",
            "location": e.get("location") or "", "characters": names,
        }
    else:
        rows = (st[-1].get("characters") or []) if st else []
        names = [str(r.get("name")) for r in rows if isinstance(r, dict) and r.get("name")]
        mem = {"summary": "", "time": "", "location": "", "characters": names}

    return mem if names else None


async def generate_author_stage_scene_image(
    novel_id: str, chapter: int, stage_index: int,
) -> None:
    from api.routes import _hub_instance

    hub = _hub_instance()
    base_event = {"novel_id": novel_id, "chapter": chapter, "index": stage_index}
    await hub.broadcast({"type": "author_scene_image_started", **base_event})

    try:
        with use_novel(novel_id):
            mem = _stage_memory_entry(chapter, stage_index)
            if mem is None:
                await hub.broadcast({"type": "author_scene_image_done", **base_event,
                                     "error": "找不到该 stage 的定稿记录，可能已重置"})
                return

            entry = _resolve_scene_image_entry(_CONFIG_KEY)
            if entry is None:
                await hub.broadcast({"type": "author_scene_image_done", **base_event,
                                     "error": _NO_MODEL_MSG})
                return

            names = mem["characters"]
            visual_tags = _character_visual_tags(names)
            portrait_bytes = _character_portrait_bytes(names)

            scene = await build_scene_prompt(memory_entry=mem, character_visual_tags=visual_tags)
            positive, negative = build_scene_positive(scene.base)
            char_captions = [
                {"char_caption": c["caption"], "centers": [{"x": 0.5, "y": 0.5}]}
                for c in scene.characters
            ]
            refs = [portrait_bytes[n] for n in names if n in portrait_bytes][:_MAX_REFERENCES]

            provider = build_image_provider(entry)
            image_bytes = await IMAGE_GEN_GATE.run(
                lambda: provider.generate(
                    positive, negative_prompt=negative, char_captions=char_captions,
                    character_references=refs or None,
                )
            )
            filename = store_author_stage_scene_image(chapter, stage_index, image_bytes)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 -- terminal; broadcast so the UI can retry
        logger.warning("[author-scene] {}:{} failed: {}", chapter, stage_index, exc)
        await hub.broadcast({"type": "author_scene_image_done", **base_event, "error": str(exc)})
        return

    await hub.broadcast({"type": "author_scene_image_done", **base_event, "filename": filename})
