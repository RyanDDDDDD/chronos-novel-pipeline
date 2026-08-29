"""Background sandbox scene-image generation: read a round's memory-archive entry + the
present characters' cached appearance tags -> one scene-prompt LLM call -> NovelAI V4.5
generate with one Precise Reference per present character that has a portrait -> store +
WS broadcast.

Serialized behind media.portrait.gate.IMAGE_GEN_GATE (same NovelAI account limit as portrait
generation). Manual-trigger only (POST /api/story-sandbox/scene-image)."""
from __future__ import annotations

import asyncio

from loguru import logger
from utils.paths import use_novel

from media.portrait.gate import IMAGE_GEN_GATE
from media.portrait.provider_factory import build_image_provider
from media.scene.prompt_builder import build_scene_positive
from media.scene.scene_prompt import build_scene_prompt
from media.scene.store import store_sandbox_scene_image

_MAX_REFERENCES = 6


def schedule_sandbox_scene_image(chapter: int, branch_id: str, round_id: str) -> None:
    from api.services.scheduler import SCHEDULER
    from utils.paths import active_novel_id

    novel_id = active_novel_id()
    SCHEDULER.schedule_once(
        f"sandbox-scene:{novel_id}:{chapter}:{branch_id}:{round_id}", 0.0,
        lambda: generate_sandbox_scene_image(novel_id, chapter, branch_id, round_id),
        dedup=True,
        on_timeout=lambda: _on_timeout(novel_id, chapter, branch_id, round_id),
    )


async def _on_timeout(novel_id: str, chapter: int, branch_id: str, round_id: str) -> None:
    from api.routes import _hub_instance

    await _hub_instance().broadcast({
        "type": "sandbox_scene_image_done", "novel_id": novel_id, "chapter": chapter,
        "branch_id": branch_id, "round_id": round_id,
        "error": "场景生图超时（排队过久或生成过慢），请稍后重试",
    })


def _resolve_scene_image_entry() -> dict | None:
    """The image_gen entry to use for sandbox scene generation. Resolution order:
    1. the entry bound to the sandbox 'scene_image' node (sandbox_llm_params.scene_image);
    2. failing that, the sole image_gen entry if exactly one exists (parity with
       character_portrait's _resolve_image_gen_entry -- so a single-model setup works with
       no extra binding step).
    Either way the entry must be a NovelAI one -- scene gen needs V4.5 Precise Reference,
    which no other provider implements. Returns None when nothing usable is configured."""
    from domain.model_catalog import load_custom_models
    from engine.modes.author_loop_skill_prefs import load_dialogue_prefs

    node = load_dialogue_prefs().get("sandbox_llm_params", {}).get("scene_image", {})
    model_ref = node.get("model_ref") if isinstance(node, dict) else None
    image_gen_entries = [m for m in load_custom_models() if m.get("provider") == "image_gen"]

    if model_ref:
        entry = next((m for m in image_gen_entries if m.get("id") == model_ref), None)
    elif len(image_gen_entries) == 1:
        entry = image_gen_entries[0]
    else:
        entry = None

    if entry is None or entry.get("service") != "novelai":
        return None
    return entry


async def _load_sandbox_turn(
    novel_id: str, chapter: int, branch_id: str, round_id: str,
) -> dict | None:
    """Peek the story_sandbox LangGraph checkpoint and return the turn dict whose id matches
    round_id, or None (round deleted / branch reset / opening turn not yet folded)."""
    from engine.story_sandbox.graph import (
        _compile_noop_graph,
        _thread_id,
        ensure_checkpointer,
    )

    checkpointer = await ensure_checkpointer(novel_id)
    config = {"configurable": {"thread_id": _thread_id(novel_id, chapter, branch_id)}}
    state = await _compile_noop_graph(checkpointer).aget_state(config)
    turns = ((state.values or {}).get("turns") or []) if state else []
    return next(
        (t for t in turns if isinstance(t, dict) and t.get("id") == round_id), None
    )


def _lore_by_name() -> dict[str, dict]:
    from engine.setup_chat.tools import _name_key
    from repositories import get_lore_repo

    return {
        _name_key(c): c for c in get_lore_repo().list_raw() if isinstance(c, dict)
    }


def _character_visual_tags(names: list[str]) -> dict[str, str]:
    by_name = _lore_by_name()
    out: dict[str, str] = {}
    for n in names:
        tags = (by_name.get(n) or {}).get("portrait_visual_tags")
        if isinstance(tags, str) and tags.strip():
            out[n] = tags.strip()
    return out


def _character_portrait_bytes(names: list[str]) -> dict[str, bytes]:
    from utils.paths import portrait_path

    by_name = _lore_by_name()
    out: dict[str, bytes] = {}
    for n in names:
        rel = (by_name.get(n) or {}).get("portrait_path")
        if isinstance(rel, str) and rel:
            try:
                with open(portrait_path(rel), "rb") as f:
                    out[n] = f.read()
            except OSError:
                pass
    return out


def _memory_entry(turn: dict) -> dict:
    from engine.memory_recall.event_log import round_event_log_entries

    entries = round_event_log_entries(turn)
    if entries:
        e = entries[-1]
        return {
            "summary": e.get("summary") or "",
            "time": e.get("time") or "",
            "location": e.get("location") or "",
            "characters": list(e.get("characters") or []),
        }
    present = list((turn.get("character_states") or {}).keys())
    fallback = str(turn.get("rolling_summary_after") or turn.get("prose") or "")[:300]
    return {"summary": fallback, "time": "", "location": "", "characters": present}


async def generate_sandbox_scene_image(
    novel_id: str, chapter: int, branch_id: str, round_id: str,
) -> None:
    from api.routes import _hub_instance

    hub = _hub_instance()
    base_event = {
        "novel_id": novel_id, "chapter": chapter, "branch_id": branch_id, "round_id": round_id,
    }
    await hub.broadcast({"type": "sandbox_scene_image_started", **base_event})

    try:
        with use_novel(novel_id):
            turn = await _load_sandbox_turn(novel_id, chapter, branch_id, round_id)
            if turn is None:
                await hub.broadcast({"type": "sandbox_scene_image_done", **base_event,
                                     "error": "找不到该轮对话，可能已被删除或重置"})
                return

            entry = _resolve_scene_image_entry()
            if entry is None:
                await hub.broadcast({"type": "sandbox_scene_image_done", **base_event,
                                     "error": "未配置场景生图模型（需 NovelAI V4.5）：先在"
                                              "「服务」页加一个 NovelAI 生图模型，再到"
                                              "「流水线 → 故事沙盒」画布点「场景生图」节点绑定"})
                return

            mem = _memory_entry(turn)
            names = mem["characters"] or list((turn.get("character_states") or {}).keys())
            mem["characters"] = names
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
            filename = store_sandbox_scene_image(chapter, branch_id, round_id, image_bytes)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 -- terminal; broadcast so the UI can retry
        logger.warning(
            "[sandbox-scene] {}:{}:{} failed: {}", chapter, branch_id, round_id, exc,
        )
        await hub.broadcast({"type": "sandbox_scene_image_done", **base_event, "error": str(exc)})
        return

    await hub.broadcast({"type": "sandbox_scene_image_done", **base_event, "filename": filename})
