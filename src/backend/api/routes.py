"""FastAPI / WebSocket routing layer."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated

from fastapi import FastAPI, File, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api.services.gateway_port import GatewayRole, parse_since_seq
from api.services.message_hub import MessageHub
from api.services.paths import dist_dir
from api.services.pipeline_catalog import list_chapters


def _hub_instance() -> MessageHub:
    """The hub singleton is parsed at runtime to facilitate testing and replacement of api.hub.HUB."""
    import api.hub as hub_mod

    return hub_mod.HUB


def register_rest(app: FastAPI) -> None:
    """Register REST（/api/*）routes into the app。"""

    @app.get("/api/pipelines/profiles")
    async def get_profiles() -> dict:
        from api.services.pipeline_profiles import list_profiles

        return {"profiles": list_profiles()}

    @app.post("/api/pipelines/profiles/active")
    async def set_active_profile(body: dict):
        from fastapi import Response

        from api.services.pipeline_profiles import set_active

        if _hub_instance().is_pipeline_busy():
            return Response(
                content=json.dumps({"ok": False, "error": "流水线运行中，无法切换"}, ensure_ascii=False),
                status_code=409, media_type="application/json",
            )
        try:
            set_active(str(body.get("id", "")))
        except ValueError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        return {"ok": True}

    @app.post("/api/pipelines/profiles")
    async def create_profile_endpoint(body: dict):
        from fastapi import Response

        from api.services.pipeline_profiles import create_profile

        if _hub_instance().is_pipeline_busy():
            return Response(
                content=json.dumps({"ok": False, "error": "流水线运行中，无法新建"}, ensure_ascii=False),
                status_code=409, media_type="application/json",
            )
        name = str(body.get("name", "")).strip()
        if not name:
            return Response(
                content=json.dumps({"ok": False, "error": "缺少名称"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        pid = create_profile(name, clone=bool(body.get("clone", True)))
        return {"ok": True, "id": pid}

    @app.patch("/api/pipelines/profiles/{pid}")
    async def rename_profile_endpoint(pid: str, body: dict):
        from fastapi import Response

        from api.services.pipeline_profiles import rename_profile

        if _hub_instance().is_pipeline_busy():
            return Response(
                content=json.dumps({"ok": False, "error": "流水线运行中，无法改名"}, ensure_ascii=False),
                status_code=409, media_type="application/json",
            )
        name = str(body.get("name", "")).strip()
        if not name:
            return Response(
                content=json.dumps({"ok": False, "error": "缺少名称"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        try:
            rename_profile(pid, name)
        except ValueError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        return {"ok": True}

    @app.delete("/api/pipelines/profiles/{pid}")
    async def delete_profile_endpoint(pid: str):
        from fastapi import Response

        from api.services.pipeline_profiles import delete_profile

        if _hub_instance().is_pipeline_busy():
            return Response(
                content=json.dumps({"ok": False, "error": "流水线运行中，无法删除"}, ensure_ascii=False),
                status_code=409, media_type="application/json",
            )
        try:
            delete_profile(pid)
        except ValueError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        return {"ok": True}

    @app.get("/api/author-loop/dialogue-config")
    async def get_author_loop_dialogue_config(novel_id: str | None = None) -> dict:
        from utils.paths import active_novel_id, use_novel

        from api.services.author_loop_dialogue_config import read_state

        nid = novel_id or active_novel_id()
        with use_novel(nid):
            return read_state()

    @app.put("/api/author-loop/dialogue-config")
    async def put_author_loop_dialogue_config(body: dict, novel_id: str | None = None) -> dict:
        from engine.modes.author_loop_skill_prefs import load_dialogue_prefs
        from utils.paths import active_novel_id, use_novel

        from api.services.author_loop_dialogue_config import write_config

        nid = novel_id or active_novel_id()
        with use_novel(nid):
            old_identity = load_dialogue_prefs().get("chat_identity", "")
            result = write_config(body)
            new_identity = load_dialogue_prefs().get("chat_identity", "")
        if new_identity != old_identity:
            #chat_identity is baked into the setup-chat agent singleton at build time (see
            #compose_system_prompt); without this, a saved override is invisible to an
            #already-open chat session until novel switch/clear-conversation happens to evict it.
            await _hub_instance().reset_setup_chat(nid)
        return result

    @app.get("/api/token-stats")
    async def get_token_stats() -> dict:
        from api.services.token_stats import aggregate_token_stats

        return aggregate_token_stats()

    @app.get("/api/health")
    async def health_endpoint() -> dict:
        """Sidecar readiness probe (Tauri shell polls this on startup)."""
        return {"ok": True}

    @app.post("/api/heartbeat")
    async def heartbeat_endpoint() -> dict:
        """Tauri shell pings this every 5s while the frontend process is alive
        (see heartbeat_watchdog.py); a stale heartbeat triggers the same shutdown
        path an explicit /api/shutdown call does."""
        from api.services.heartbeat_watchdog import record_heartbeat

        record_heartbeat()
        return {"ok": True}

    @app.post("/api/shutdown")
    async def shutdown_endpoint() -> dict:
        """Graceful shutdown trigger for the Tauri shell: reuses uvicorn's already-installed
        SIGTERM handler via the shared trigger_graceful_shutdown() (also used by the heartbeat
        watchdog's timeout branch), instead of reimplementing the _lifespan cleanup here."""
        from api.services.heartbeat_watchdog import trigger_graceful_shutdown

        trigger_graceful_shutdown("explicit POST /api/shutdown (Tauri ExitRequested)")
        return {"ok": True}

    #── Global service configuration (config/config.json)──────────────────────────────────────
    @app.get("/api/config")
    async def get_config_endpoint() -> dict:
        """Read the current effective configuration (the result of deep merging defaults and config.json)."""
        from utils.config import get_config
        return {"config": get_config()}

    @app.put("/api/config")
    async def put_config_endpoint(request: Request):
        """
Write to config/config.json and reload (for WebUI configuration page)."""
        from fastapi import Response
        from llm.factory import reset_cloud_llm_cache
        from utils.config import get_config, save_config

        def _first_image_gen_key(config: dict) -> str | None:
            from media.portrait.provider import DEFAULT_IMAGE_SERVICE, ImageService

            models = config.get("llm", {}).get("custom_models", [])
            entry = next(
                (
                    m for m in models
                    if isinstance(m, dict) and m.get("provider") == "image_gen" and m.get("api_key")
                    and ImageService(m.get("service") or DEFAULT_IMAGE_SERVICE) is ImageService.NOVITA
                ),
                None,
            )
            return entry["api_key"] if entry else None

        body = await request.json()
        raw = (body or {}).get("config") if isinstance(body, dict) else None
        if not isinstance(raw, dict):
            return Response(
                content=json.dumps({"ok": False, "error": "config 必须是 JSON 对象"}, ensure_ascii=False),
                status_code=400,
                media_type="application/json",
            )
        old_image_gen_key = _first_image_gen_key(get_config())  # 保存前的内存缓存值

        try:
            cfg = save_config(raw)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            return Response(
                content=json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False),
                status_code=400,
                media_type="application/json",
            )
        reset_cloud_llm_cache()
        #build_agent() bakes get_cloud_llm()'s result into the setup-chat agent singleton at
        #build time; without this, a saved model/key change is invisible to setup-chat until
        #something else (novel switch) happens to call reset_setup_chat() as a side effect.
        await _hub_instance().reset_setup_chat()
        from api.services.service_ping_status import run_config_save_pings

        await run_config_save_pings(cfg)

        new_image_gen_key = _first_image_gen_key(cfg)
        if new_image_gen_key and new_image_gen_key != old_image_gen_key:
            from domain.novita_model_catalog import refresh_novita_model_catalog

            from api.services.scheduler import SCHEDULER

            async def _refresh_novita_catalog() -> None:
                await refresh_novita_model_catalog(new_image_gen_key)

            SCHEDULER.schedule_once(
                "novita_model_catalog_refresh", 0.0, _refresh_novita_catalog, dedup=True,
            )
        return {"ok": True, "config": cfg}

    #── 服务连通性（小说栏信号图标：状态由后端持有，前端只读）────────────────────
    @app.get("/api/health/service-status")
    async def service_status_endpoint():
        from api.services.service_ping_status import ServicePingStatus, get_service_status

        status: ServicePingStatus = get_service_status()
        return status

    @app.post("/api/health/ping-llm")
    async def ping_llm_endpoint() -> dict:
        from utils.config import get_config

        from api.services.service_ping_status import run_ping_llm

        return await run_ping_llm(get_config())

    @app.post("/api/health/ping-search")
    async def ping_search_endpoint() -> dict:
        from utils.config import get_config

        from api.services.service_ping_status import run_ping_search

        return await run_ping_search(get_config())

    #── LLM 目录 / 本地模型实时列表 ─────────────────────────────────────────────
    @app.get("/api/llm/catalog")
    async def get_llm_catalog_endpoint() -> dict:
        from domain.model_catalog import load_custom_models, load_model_catalog

        custom_models = [
            {
                "id": m["id"], "label": m.get("label", ""),
                "provider": m.get("provider", "openai_compatible"),
                "base_url": m.get("base_url", ""), "model": m.get("model", ""),
            }
            for m in load_custom_models()
            if m.get("provider") != "image_gen"
        ]
        return {"cloud_models": load_model_catalog(), "custom_models": custom_models}

    @app.get("/api/image-gen/catalog")
    async def get_image_gen_catalog_endpoint() -> dict:
        from domain.model_catalog import load_custom_models

        custom_models = [
            {"id": m["id"], "label": m.get("label", ""), "model": m.get("model", "")}
            for m in load_custom_models()
            if m.get("provider") == "image_gen"
        ]
        return {"custom_models": custom_models}

    @app.get("/api/image-gen/novita-models")
    async def get_novita_models_endpoint() -> dict:
        from domain.novita_model_catalog import get_cached_base_models, get_cached_novita_models

        return {"models": get_cached_novita_models(), "base_models": get_cached_base_models()}

    @app.get("/api/image-gen/style-presets")
    async def get_style_presets_endpoint() -> dict:
        from media.portrait.style_presets import ART_STYLE_PRESETS

        return {
            "presets": [
                {"id": p.id, "label": p.label, "preview_url": p.preview_path}
                for p in ART_STYLE_PRESETS
            ]
        }

    @app.post("/api/image-gen/novita-models/refresh")
    async def post_novita_models_refresh_endpoint() -> dict:
        from domain.model_catalog import load_custom_models
        from media.portrait.provider import DEFAULT_IMAGE_SERVICE, ImageService

        entry = next(
            (
                m for m in load_custom_models()
                if m.get("provider") == "image_gen" and m.get("api_key")
                and ImageService(m.get("service") or DEFAULT_IMAGE_SERVICE) is ImageService.NOVITA
            ),
            None,
        )
        if entry is None:
            return {"scheduled": False, "error": "当前没有 Novita 生图条目（NovelAI 无需刷新目录）"}

        async def _refresh_and_notify() -> None:
            from domain.novita_model_catalog import refresh_novita_model_catalog

            await refresh_novita_model_catalog(entry["api_key"])
            await _hub_instance().broadcast({"type": "novita_model_catalog_refreshed"})

        from api.services.scheduler import SCHEDULER

        SCHEDULER.schedule_once("novita_model_catalog_refresh", 0.0, _refresh_and_notify, dedup=True)
        return {"scheduled": True}

    @app.get("/api/llm/local-models")
    async def get_local_models_endpoint(base_url: str = "") -> dict:
        from utils.config import get_config

        from api.services.openai_models_list import fetch_openai_compatible_models

        cfg = get_config().get("llm", {})
        cfg_url = cfg.get("local_base_url", "") if isinstance(cfg, dict) else ""
        resolved_base_url = base_url or (cfg_url if isinstance(cfg_url, str) else "")
        return await fetch_openai_compatible_models(
            resolved_base_url,
            connection_error_prefix="无法连接本地推理服务",
        )

    @app.post("/api/llm/compatible-models")
    async def post_compatible_models_endpoint(request: Request) -> dict:
        from api.services.openai_models_list import fetch_openai_compatible_models

        body = await request.json()
        if not isinstance(body, dict):
            body = {}
        raw_base = body.get("base_url")
        raw_key = body.get("api_key")
        base_url = raw_base if isinstance(raw_base, str) else ""
        api_key = raw_key if isinstance(raw_key, str) else ""
        return await fetch_openai_compatible_models(
            base_url,
            api_key=api_key,
            connection_error_prefix="无法拉取模型列表",
        )

    @app.get("/api/chapters")
    async def list_chapters_endpoint() -> dict:
        return {"chapters": list_chapters()}

    @app.get("/api/chapters/manuscripts")
    async def list_manuscripts_endpoint() -> dict:
        from api.services.pipeline_catalog import list_author_manuscripts

        return {"chapters": list_author_manuscripts()}

    @app.get("/api/chapters/{chapter}/manuscript")
    async def get_chapter_manuscript_endpoint(chapter: int):
        from fastapi import Response

        from api.services.pipeline_catalog import read_author_manuscript

        try:
            body = read_author_manuscript(chapter)
        except ValueError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=400,
                media_type="application/json",
            )
        except FileNotFoundError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=404,
                media_type="application/json",
            )
        return {"ok": True, **body}

    @app.post("/api/chapters/{chapter}/reset", response_model=None)
    async def reset_chapter(chapter: int):
        from domain.usage import clear_chapter_usage

        from api.services.pipeline_catalog import clear_chapter_disk

        try:
            await _hub_instance().stop_all_pipelines()
            clear_chapter_disk(chapter)
            clear_chapter_usage(chapter)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                status_code=500,
                content={"ok": False, "error": str(exc)},
            )
        return {"ok": True}


    @app.post("/api/author-loop/start")
    async def start_author_loop_endpoint(request: Request):
        """Start the main writer's paragraph-by-paragraph writing cycle: collect {chapter}, and the progress/paragraph-by-paragraph output will be broadcast via ws."""
        from fastapi import Response

        body = await request.json()
        raw_ch = body.get("chapter") if isinstance(body, dict) else None
        try:
            chapter = int(raw_ch) if raw_ch is not None else 0
        except (TypeError, ValueError):
            chapter = 0
        if chapter < 1:
            return Response(
                content=json.dumps({"ok": False, "error": "chapter 须 ≥ 1"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        if isinstance(body, dict) and body.get("fresh"):
            from engine.author_loop.build import clear_author_loop
            clear_author_loop(chapter)
        #The writing style is unified through the per-novel writing style setting (Header "Writing Style" button); it will only be overwritten if the request body is explicitly given.
        b = body if isinstance(body, dict) else {}
        prose_style = str(b.get("prose_style", ""))
        try:
            await _hub_instance().start_author_loop(
                chapter, prose_style=prose_style,
            )
        except RuntimeError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=409, media_type="application/json",
            )
        return {"ok": True, "status": "running", "chapter": chapter, "mode": "dialogue"}

    @app.get("/api/author-loop/status")
    async def author_loop_status_endpoint(novel_id: str | None = None):
        """
Main author status: Recoverable chapter list (chapters with checkpoint) + whether a chapter is actively running right now for this novel."""
        hub = _hub_instance()
        return {
            "resumable": hub.resumable_chapters(novel_id),
            "running_chapter": hub.running_author_loop_chapter(novel_id),
        }

    @app.get("/api/author-loop/journal")
    async def author_loop_journal_endpoint(chapter: int, novel_id: str | None = None):
        """Pull the journal playback event of a certain chapter on demand (scroll when the front end opens/restores the chapter). Contains the final state stopped at the end, or the live tail if this chapter is actively running for the given novel."""
        return {"chapter": chapter, "events": _hub_instance().journal_events(chapter, novel_id)}

    @app.post("/api/author-loop/resume")
    async def resume_author_loop_endpoint(request: Request):
        """
Resume running from breakpoint: restore the beat in the segment from the checkpoint and reuse the final skeleton."""
        from fastapi import Response

        body = await request.json()
        raw_ch = body.get("chapter") if isinstance(body, dict) else None
        try:
            chapter = int(raw_ch) if raw_ch is not None else 0
        except (TypeError, ValueError):
            chapter = 0
        if chapter < 1:
            return Response(
                content=json.dumps({"ok": False, "error": "chapter 须 ≥ 1"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        try:
            await _hub_instance().start_author_loop(chapter, resume=True)
        except RuntimeError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=409, media_type="application/json",
            )
        return {"ok": True, "status": "running", "chapter": chapter}

    @app.post("/api/author-loop/stop")
    async def stop_author_loop_endpoint():
        """Stop the main author writing in the middle: cancel the background task and broadcast author_loop_stopped."""
        await _hub_instance().stop_author_loop()
        return {"ok": True, "status": "stopped"}

    @app.post("/api/author-loop/save")
    async def save_author_loop_endpoint(request: Request):
        """
Assemble the main author's section-by-section output into a whole chapter. md. Place: Close {chapter} and return to the writing path."""
        from fastapi import Response

        body = await request.json()
        raw_ch = body.get("chapter") if isinstance(body, dict) else None
        try:
            chapter = int(raw_ch) if raw_ch is not None else 0
        except (TypeError, ValueError):
            chapter = 0
        if chapter < 1:
            return Response(
                content=json.dumps({"ok": False, "error": "chapter 须 ≥ 1"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        from engine.author_loop.build import save_author_loop_chapter

        try:
            path = save_author_loop_chapter(chapter)
        except ValueError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        return {"ok": True, "path": path}

    @app.get("/api/archives")
    async def archives_overview() -> dict:
        from engine.archive.archive_view import list_archive_overview

        return list_archive_overview()

    @app.get("/api/archives/{chapter}")
    async def archives_chapter(chapter: int) -> dict:
        from engine.archive.archive_view import render_chapter_archives

        return render_chapter_archives(chapter)

    @app.get("/api/setup/relationship-graph")
    async def read_relationship_graph() -> dict:
        from engine.setup.cast.relationship_graph import load_graph

        return {"graph": load_graph()}

    @app.get("/api/setup/world")
    async def read_world() -> dict:
        from repositories import get_world_repo

        return {"world_bible": get_world_repo().get()}

    @app.get("/api/setup/cast")
    async def read_cast() -> dict:
        from repositories import get_lore_repo

        return {"characters": get_lore_repo().list_raw()}

    @app.get("/api/setup/plot")
    async def read_plot() -> dict:
        from repositories import get_plot_repo

        return {"chapters": get_plot_repo().list_raw()}

    @app.get("/api/setup/skeleton/{chapter}")
    async def read_chapter_skeleton(chapter: int) -> dict:
        """某章逐 stage 的分拍底稿：粗大纲 description + 对话页扩写的 beats（若设计了台词已织入 text）+
        是否已扩写。供前端只读展示（骨架分拍扩写在对话页完成，写回 plot 各 stage 的 beats 字段）。"""
        from repositories import get_plot_repo

        chapters = get_plot_repo().list_raw()
        ch = next(
            (c for c in chapters if isinstance(c, dict) and c.get("chapter") == chapter), None
        )
        if ch is None:
            return {"chapter": chapter, "exists": False, "stages": []}
        stages = [
            {
                "stage_num": s.get("stage_num"),
                "title": s.get("title", ""),
                "description": s.get("description", ""),
                "location": s.get("location", ""),
                "beats": [b for b in (s.get("beats") or []) if isinstance(b, dict)],
                "expanded": bool(s.get("beats")),
            }
            for s in (ch.get("stages") or [])
        ]
        return {"chapter": chapter, "exists": True, "stages": stages}

    @app.patch("/api/setup/world")
    async def patch_world(body: dict):
        from engine.setup.world.manual_edit import patch_world_field

        field = str((body or {}).get("field", ""))
        value = (body or {}).get("value")
        ok, msg = patch_world_field(field, value)
        if not ok:
            return Response(
                content=json.dumps({"ok": False, "error": msg}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        from engine.setup_chat.world_background_review import schedule_world_quality_review

        schedule_world_quality_review()
        return {"ok": True, "message": msg}

    def _character_fields_from_body(body: dict) -> dict:
        from context.content_packs import custom_fields

        fields = {
            "given_name": str(body.get("given_name", "")),
            "role": str(body.get("role", "")),
            "gender": str(body.get("gender", "")),
            "causal_anchors": body.get("causal_anchors") or {},
            "physique": body.get("physique") or {},
            "clothing_color_palette": body.get("clothing_color_palette") or [],
            "clothing_materials": body.get("clothing_materials") or [],
            "clothing_signature_outfit": str(body.get("clothing_signature_outfit", "")),
            "clothing_accessories": body.get("clothing_accessories") or [],
            "sliders": body.get("sliders") or {},
            "personality": str(body.get("personality", "")),
            "race": str(body.get("race", "")),
            "identity_background": str(body.get("identity_background", "")),
            "hobbies": body.get("hobbies") or [],
            "verbal_tic": str(body.get("verbal_tic", "")),
        }
        #Content-pack-declared custom fields (e.g. an optional content pack's custom field) aren't named params on
        #add_character/edit_character -- they flow through **extra, so this route must forward
        #them by name too, or a pack that marks one required breaks manual cast editing entirely.
        for spec in custom_fields():
            fields[spec.name] = str(body.get(spec.name, ""))
        return fields

    def _portrait_tag_overrides(body: dict) -> dict:
        """Pull the two portrait tag fields out as explicit kwargs (key absent -> None ->
        _*_character_core leaves the stored value alone; "" -> explicit clear)."""
        out: dict = {}
        for key in ("portrait_visual_tags", "portrait_identity_tags"):
            raw = (body or {}).get(key)
            if raw is not None:
                out[key] = str(raw)
        return out

    @app.post("/api/setup/cast")
    async def post_cast_character(body: dict):
        from engine.setup_chat.tools import _add_character_core

        # Manual cast-page create: background review/timeline-derive still run, but must not
        # inject a system-notice turn into the chat transcript for a UI action outside chat.
        ok, msg, char = await _add_character_core(
            notify_chat=False,
            **_portrait_tag_overrides(body or {}),
            **_character_fields_from_body(body or {}),
        )
        if not ok:
            return Response(
                content=json.dumps({"ok": False, "error": msg}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        return {"ok": True, "message": msg, "character": char}

    @app.patch("/api/setup/cast/{name}")
    async def patch_cast_character(name: str, body: dict):
        from engine.setup_chat.tools import _edit_character_core

        # Key absent -> None -> _edit_character_core keeps the stored value; a present key
        # (even "" to clear it) is an explicit manual override. See _portrait_tag_overrides.
        # Manual cast-page edit: background review/timeline-derive still run, but must not
        # inject a system-notice turn into the chat transcript for a UI action outside chat.
        ok, msg, char = await _edit_character_core(
            name=name, notify_chat=False,
            **_portrait_tag_overrides(body or {}),
            **_character_fields_from_body(body or {}),
        )
        if not ok:
            status = 404 if "未找到" in msg else 400
            return Response(
                content=json.dumps({"ok": False, "error": msg}, ensure_ascii=False),
                status_code=status, media_type="application/json",
            )
        return {"ok": True, "message": msg, "character": char}

    @app.delete("/api/setup/cast/{name}")
    async def delete_cast_character(name: str):
        from engine.setup_chat.tools import _delete_character_core

        ok, msg, _detail = await _delete_character_core(name)
        if not ok:
            return Response(
                content=json.dumps({"ok": False, "error": msg}, ensure_ascii=False),
                status_code=404, media_type="application/json",
            )
        return {"ok": True, "message": msg}

    @app.patch("/api/setup/plot/{chapter}")
    async def patch_plot_chapter_meta(chapter: int, body: dict):
        from engine.setup.plot.manual_edit import patch_plot_chapter_title
        from engine.setup_chat.tools import _patch_chapter_core

        body = body or {}
        title = body.get("title")
        core_xp = body.get("core_xp")
        if title is not None:
            ok, msg = patch_plot_chapter_title(chapter, str(title))
            if not ok:
                return Response(
                    content=json.dumps({"ok": False, "error": msg}, ensure_ascii=False),
                    status_code=400, media_type="application/json",
                )
        if core_xp is not None:
            ok, msg = await _patch_chapter_core(chapter, [], core_xp=list(core_xp), run_review=False)
            if not ok:
                return Response(
                    content=json.dumps({"ok": False, "error": msg}, ensure_ascii=False),
                    status_code=400, media_type="application/json",
                )
        return {"ok": True}

    @app.patch("/api/setup/plot/{chapter}/skeleton")
    async def patch_plot_skeleton(chapter: int, body: dict):
        from engine.setup_chat.tools import _patch_chapter_core

        body = body or {}
        if body.get("op") == "remove":
            # Manual stage deletion from the plot setup page is disallowed: it fragments
            # narrative continuity. Deletion stays available to the setup_chat agent's
            # own patch_chapter tool, which acts on explicit in-conversation intent.
            return Response(
                content=json.dumps(
                    {"ok": False, "error": "剧情页面已禁用手动删除段落，如需调整请通过「对话」页面"},
                    ensure_ascii=False,
                ),
                status_code=400, media_type="application/json",
            )
        ok, msg = await _patch_chapter_core(chapter, [body], run_review=False)
        if not ok:
            return Response(
                content=json.dumps({"ok": False, "error": msg}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        return {"ok": True, "message": msg}

    @app.post("/api/setup-chat/message")
    async def setup_chat_message(request: Request):
        """
Receive a user message and run a setting dialog; the output is broadcast via ws."""
        from fastapi import Response

        body = await request.json()
        text = str((body or {}).get("text", "")).strip() if isinstance(body, dict) else ""
        attachment_ids = [
            x for x in ((body or {}).get("attachment_ids") or []) if isinstance(x, str)
        ] if isinstance(body, dict) else []
        if not text and not attachment_ids:
            return Response(
                content=json.dumps({"ok": False, "error": "text 不能为空"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        try:
            status = await _hub_instance().start_setup_chat_turn(text, attachment_ids)
        except RuntimeError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=409, media_type="application/json",
            )
        return {"ok": True, "status": status}

    @app.post("/api/setup-chat/regenerate")
    async def setup_chat_regenerate_endpoint(request: Request):
        """Retry the last failed setup-chat assistant reply for the given user text."""
        from fastapi import Response

        body = await request.json()
        text = str((body or {}).get("text", "")).strip() if isinstance(body, dict) else ""
        if not text:
            return Response(
                content=json.dumps({"ok": False, "error": "text 不能为空"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        try:
            status = await _hub_instance().regenerate_setup_chat_turn(text)
        except ValueError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        except RuntimeError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=409, media_type="application/json",
            )
        return {"ok": True, "status": status}

    @app.post("/api/setup-chat/stop")
    async def setup_chat_stop_endpoint():
        """User-initiated interrupt: cancel the in-flight turn and roll state back to before it."""
        await _hub_instance().stop_setup_chat_turn()
        return {"ok": True, "status": "stopped"}

    @app.get("/api/setup-chat/history")
    async def setup_chat_history_endpoint(novel_id: str | None = None) -> dict:
        """Explicit novel_id so hydrate during a novel switch isn't racing the backend's
        active-novel flip -- mirrors setup_chat_status_endpoint / story_sandbox_history."""
        asyncio.create_task(_hub_instance().check_setup_chat_recovery())
        return {
            "messages": await _hub_instance().setup_chat_history(novel_id),
            "live_round": _hub_instance().setup_chat_live_round(novel_id),
        }

    @app.get("/api/setup-chat/status")
    async def setup_chat_status_endpoint(novel_id: str | None = None) -> dict:
        """Explicit novel_id (not the hub's active-novel pointer) so a caller resyncing right
        after a novel switch isn't racing the backend's active-novel flip -- mirrors
        author_loop_status_endpoint."""
        hub = _hub_instance()
        return {
            "busy": hub.is_setup_chat_busy(novel_id),
            "novel_import": hub.novel_import_progress_snapshot(novel_id),
            "image_recognition_configured": hub.is_image_recognition_configured(),
        }

    @app.get("/api/setup-chat/mode")
    async def setup_chat_mode_get() -> dict:
        from engine.setup_chat.mode import is_auto_mode
        return {"auto": is_auto_mode()}

    @app.post("/api/setup-chat/mode")
    async def setup_chat_mode_set(request: Request) -> dict:
        from engine.setup_chat.mode import set_auto_mode

        body = await request.json()
        auto = bool((body or {}).get("auto", False)) if isinstance(body, dict) else False
        set_auto_mode(auto)
        #broadcast so other connected clients (multi-tab) stay in sync with this
        #process-global flag -- mirrors reset_setup_chat's silent-flip fix.
        await _hub_instance().broadcast({"type": "setup_chat_mode_changed", "auto": auto})
        return {"auto": auto}

    @app.post("/api/setup-chat/reset")
    async def setup_chat_reset_endpoint():
        """清空当前小说 setup-chat 的全部对话状态（短期+长期记忆+任务进度+消息回放表），重新开始。"""
        from fastapi import Response

        try:
            await _hub_instance().clear_setup_chat_conversation()
        except RuntimeError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=409, media_type="application/json",
            )
        return {"ok": True}

    @app.post("/api/story-sandbox/message")
    async def story_sandbox_message(request: Request):
        """接收导演一轮输入，跑一段沙盒续写；产出经 ws 广播。"""
        from fastapi import Response

        body = await request.json()
        chapter = int((body or {}).get("chapter", 0)) if isinstance(body, dict) else 0
        branch_id = str((body or {}).get("branch_id", "")).strip() if isinstance(body, dict) else ""
        if not branch_id:
            return Response(
                content=json.dumps({"ok": False, "error": "branch_id 不能为空"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        text = str((body or {}).get("text", "")).strip() if isinstance(body, dict) else ""
        submitted_directions_raw = (body or {}).get("submitted_directions") if isinstance(body, dict) else None
        submitted_directions = (
            [str(d) for d in submitted_directions_raw if isinstance(d, str)]
            if isinstance(submitted_directions_raw, list) else None
        )
        if chapter < 0:
            return Response(
                content=json.dumps({"ok": False, "error": "chapter 不合法"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        if not text:
            return Response(
                content=json.dumps({"ok": False, "error": "text 不能为空"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        try:
            await _hub_instance().start_story_sandbox_turn(chapter, text, submitted_directions, branch_id=branch_id)
        except RuntimeError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=409, media_type="application/json",
            )
        return {"ok": True, "status": "running"}

    @app.post("/api/story-sandbox/stop")
    async def story_sandbox_stop_endpoint(request: Request):
        """User-initiated interrupt: cancel the in-flight turn and roll state back to before it."""
        from fastapi import Response

        body = await request.json()
        chapter = int((body or {}).get("chapter", 0)) if isinstance(body, dict) else 0
        branch_id = str((body or {}).get("branch_id", "")).strip() if isinstance(body, dict) else ""
        if not branch_id:
            return Response(
                content=json.dumps({"ok": False, "error": "branch_id 不能为空"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        await _hub_instance().stop_story_sandbox_turn(chapter, branch_id=branch_id)
        return {"ok": True, "status": "stopped"}

    @app.get("/api/story-sandbox/history")
    async def story_sandbox_history_endpoint(
        chapter: int, branch_id: str, novel_id: str | None = None,
    ) -> dict:
        return await _hub_instance().story_sandbox_history(chapter, novel_id=novel_id, branch_id=branch_id)

    @app.get("/api/story-sandbox/cast-archives")
    async def story_sandbox_cast_archives_endpoint(
        chapter: int, names: str = "", novel_id: str | None = None,
    ) -> dict:
        from engine.story_sandbox.cast import resolve_active_cast_archives
        from utils.paths import active_novel_id

        name_list = [n for n in names.split(",") if n]
        nid = novel_id or active_novel_id()
        return {"characters": await resolve_active_cast_archives(chapter, name_list, nid)}

    @app.get("/api/story-sandbox/related-cast-archives")
    async def story_sandbox_related_cast_archives_endpoint(
        chapter: int, present: str = "", novel_id: str | None = None,
    ) -> dict:
        from engine.story_sandbox.cast import resolve_related_cast_archives
        from utils.paths import active_novel_id

        present_list = [n for n in present.split(",") if n]
        nid = novel_id or active_novel_id()
        return {"characters": await resolve_related_cast_archives(chapter, present_list, nid)}

    @app.get("/api/story-sandbox/memory-archive")
    async def story_sandbox_memory_archive_endpoint(
        chapter: int, branch_id: str | None = None,
    ) -> dict:
        from engine.memory_recall.event_log import list_memory_archive
        from repositories.entities import MemoryOrigin

        return {"entries": list_memory_archive(chapter, branch_id, origin=MemoryOrigin.SANDBOX)}


    @app.get("/api/story-sandbox/status")
    async def story_sandbox_status_endpoint() -> dict:
        return {"busy": _hub_instance().is_story_sandbox_busy()}

    @app.post("/api/story-sandbox/scene-image")
    async def story_sandbox_scene_image_endpoint(body: dict):
        from media.scene.generation import schedule_sandbox_scene_image

        b = body or {}
        schedule_sandbox_scene_image(
            int(b.get("chapter", 0)), str(b.get("branch_id", "")), str(b.get("round_id", "")),
        )
        return {"ok": True}

    @app.get("/api/story-sandbox/scene-images")
    async def story_sandbox_scene_images_endpoint(chapter: int, branch_id: str) -> dict:
        from media.scene.store import list_sandbox_scene_images

        images = {
            rid: f"/api/story-sandbox/scene-image/{chapter}/{branch_id}/{rid}/file?v={fn}"
            for rid, fn in list_sandbox_scene_images(chapter, branch_id).items()
        }
        return {"images": images}

    @app.get("/api/story-sandbox/scene-image/{chapter}/{branch_id}/{round_id}/file")
    async def story_sandbox_scene_image_file_endpoint(
        chapter: int, branch_id: str, round_id: str,
    ):
        from fastapi import Response
        from fastapi.responses import FileResponse
        from media.scene.store import sandbox_scene_image_filename
        from utils.paths import sandbox_scene_path

        fn = sandbox_scene_image_filename(chapter, branch_id, round_id)
        if not fn:
            return Response(status_code=404)
        return FileResponse(sandbox_scene_path(fn), media_type="image/png")

    @app.get("/api/story-sandbox/branches")
    async def story_sandbox_branches_endpoint(chapter: int, novel_id: str | None = None) -> dict:
        """Lists this chapter's (or free mode's, chapter=0) story lines. Lazily registers a
        default '故事线1' branch (id == LEGACY_BRANCH_ID) on first request if the registry has
        nothing for this chapter yet -- covers both a pre-existing old-format checkpoint thread
        (register_legacy_branch adopts it) and a brand-new novel/chapter with no conversation at
        all (register_legacy_branch just creates the registry record; LEGACY_BRANCH_ID is also
        the default branch_id every graph.py call falls back to, so the first turn naturally
        lands on this thread). Without this, a new novel's story-line dropdown starts empty.

        list_branches/register_legacy_branch (engine/story_sandbox/branches.py) take no
        novel_id parameter -- they resolve their JSON file path via ambient active_novel_id().
        Must run under use_novel(nid) so an explicit novel_id here is actually honored instead
        of silently falling through to whatever the backend's global active-novel pointer
        currently says (which can be a different novel than the one this request is for -- see
        docs/superpowers/specs/2026-08-02-multi-novel-concurrency-design.md's follow-up fix)."""
        from engine.story_sandbox import branches as sandbox_branches
        from utils.paths import active_novel_id, use_novel

        nid = novel_id or active_novel_id()
        with use_novel(nid):
            existing = sandbox_branches.list_branches(chapter)
            if not existing:
                sandbox_branches.register_legacy_branch(chapter)
                existing = sandbox_branches.list_branches(chapter)
        return {"branches": existing}

    @app.post("/api/story-sandbox/branches")
    async def story_sandbox_create_branch_endpoint(body: dict):
        from fastapi import Response

        chapter = int(body.get("chapter", 0))
        if chapter < 0:
            return Response(
                content=json.dumps({"ok": False, "error": "chapter 不合法"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        name = body.get("name")
        source_branch_id = body.get("source_branch_id")
        try:
            branch = await _hub_instance().create_story_sandbox_branch(
                chapter, str(name) if name else None,
                str(source_branch_id) if source_branch_id else None,
            )
        except RuntimeError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=409, media_type="application/json",
            )
        return {"ok": True, "branch": branch}

    @app.patch("/api/story-sandbox/branches/{branch_id}")
    async def story_sandbox_rename_branch_endpoint(branch_id: str, chapter: int, body: dict):
        from engine.story_sandbox import branches as sandbox_branches
        from fastapi import Response

        name = str(body.get("name", "")).strip()
        if not name:
            return Response(
                content=json.dumps({"ok": False, "error": "名称不能为空"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        try:
            branch = sandbox_branches.rename_branch(chapter, branch_id, name)
        except ValueError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=404, media_type="application/json",
            )
        return {"ok": True, "branch": branch}

    @app.delete("/api/story-sandbox/branches/{branch_id}")
    async def story_sandbox_delete_branch_endpoint(branch_id: str, chapter: int):
        from fastapi import Response

        try:
            next_branch = await _hub_instance().delete_story_sandbox_branch(chapter, branch_id)
        except RuntimeError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=409, media_type="application/json",
            )
        except ValueError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=404, media_type="application/json",
            )
        return {"ok": True, "branch": next_branch}

    @app.post("/api/story-sandbox/branches/{branch_id}/reset")
    async def story_sandbox_reset_branch_endpoint(branch_id: str, chapter: int):
        from fastapi import Response

        try:
            branch = await _hub_instance().reset_story_sandbox_branch(chapter, branch_id)
        except RuntimeError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=409, media_type="application/json",
            )
        except ValueError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=404, media_type="application/json",
            )
        return {"ok": True, "branch": branch}

    @app.post("/api/story-sandbox/suggestions/regenerate")
    async def story_sandbox_regenerate_suggestions_endpoint(request: Request):
        """重新生成最新一轮的剧情走向建议（不重写正文、不重新推演状态）。"""
        from fastapi import Response

        body = await request.json()
        chapter = int((body or {}).get("chapter", 0)) if isinstance(body, dict) else 0
        branch_id = str((body or {}).get("branch_id", "")).strip() if isinstance(body, dict) else ""
        if not branch_id:
            return Response(
                content=json.dumps({"ok": False, "error": "branch_id 不能为空"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        hint = str((body or {}).get("hint", "")) if isinstance(body, dict) else ""
        if chapter < 0:
            return Response(
                content=json.dumps({"ok": False, "error": "chapter 不合法"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        try:
            await _hub_instance().regenerate_story_sandbox_suggestions(chapter, hint=hint, branch_id=branch_id)
        except RuntimeError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=409, media_type="application/json",
            )
        return {"ok": True}

    @app.post("/api/story-sandbox/rewrite")
    async def story_sandbox_rewrite_endpoint(request: Request):
        """重写最新一轮沙盒正文：保留原导演指令，按反馈调整写法；产出经 ws 广播。"""
        from fastapi import Response

        body = await request.json()
        chapter = int((body or {}).get("chapter", 0)) if isinstance(body, dict) else 0
        branch_id = str((body or {}).get("branch_id", "")).strip() if isinstance(body, dict) else ""
        if not branch_id:
            return Response(
                content=json.dumps({"ok": False, "error": "branch_id 不能为空"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        feedback = str((body or {}).get("feedback", "")) if isinstance(body, dict) else ""
        if chapter < 0:
            return Response(
                content=json.dumps({"ok": False, "error": "chapter 不合法"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        try:
            await _hub_instance().start_story_sandbox_rewrite(chapter, feedback, branch_id=branch_id)
        except RuntimeError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=409, media_type="application/json",
            )
        return {"ok": True, "status": "running"}

    @app.post("/api/story-sandbox/retry-derive")
    async def story_sandbox_retry_derive_endpoint(request: Request):
        """重试最近一次因推演失败而终止的回合：正文若已生成则复用，只重跑推演；产出经 ws 广播。"""
        from fastapi import Response

        body = await request.json()
        chapter = int((body or {}).get("chapter", 0)) if isinstance(body, dict) else 0
        branch_id = str((body or {}).get("branch_id", "")).strip() if isinstance(body, dict) else ""
        if not branch_id:
            return Response(
                content=json.dumps({"ok": False, "error": "branch_id 不能为空"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        if chapter < 0:
            return Response(
                content=json.dumps({"ok": False, "error": "chapter 不合法"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        try:
            await _hub_instance().retry_story_sandbox_derive(chapter, branch_id=branch_id)
        except RuntimeError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=409, media_type="application/json",
            )
        return {"ok": True, "status": "running"}

    @app.post("/api/story-sandbox/profile-mutate/rewrite")
    async def story_sandbox_profile_mutate_rewrite_endpoint(request: Request):
        """定向重写最新一轮的档案/关系突变：不重新生成正文，仅按用户建议重新推演突变。"""
        from fastapi import Response

        body = await request.json()
        chapter = int((body or {}).get("chapter", 0)) if isinstance(body, dict) else 0
        branch_id = str((body or {}).get("branch_id", "")).strip() if isinstance(body, dict) else ""
        if not branch_id:
            return Response(
                content=json.dumps({"ok": False, "error": "branch_id 不能为空"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        feedback = str((body or {}).get("feedback", "")) if isinstance(body, dict) else ""
        if chapter < 0:
            return Response(
                content=json.dumps({"ok": False, "error": "chapter 不合法"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        try:
            await _hub_instance().rewrite_story_sandbox_profile_mutation(
                chapter, feedback, branch_id=branch_id,
            )
        except RuntimeError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=409, media_type="application/json",
            )
        return {"ok": True, "status": "running"}

    @app.post("/api/story-sandbox/rewrite-selection")
    async def story_sandbox_rewrite_selection_endpoint(request: Request):
        """局部重写沙盒正文里导演选中的一小段文字：只改措辞，不重新推演状态/剧情。"""
        from fastapi import Response

        body = await request.json()
        chapter = int((body or {}).get("chapter", 0)) if isinstance(body, dict) else 0
        branch_id = str((body or {}).get("branch_id", "")).strip() if isinstance(body, dict) else ""
        if not branch_id:
            return Response(
                content=json.dumps({"ok": False, "error": "branch_id 不能为空"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        original_text = str((body or {}).get("original_text", "")) if isinstance(body, dict) else ""
        anchor_offset = int((body or {}).get("anchor_offset", 0)) if isinstance(body, dict) else 0
        feedback = str((body or {}).get("feedback", "")) if isinstance(body, dict) else ""
        round_id = (body or {}).get("round_id") if isinstance(body, dict) else None
        round_id = str(round_id) if round_id else None
        if chapter < 0:
            return Response(
                content=json.dumps({"ok": False, "error": "chapter 不合法"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        if not original_text.strip():
            return Response(
                content=json.dumps({"ok": False, "error": "未选中任何文字"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        try:
            await _hub_instance().start_story_sandbox_selection_rewrite(
                chapter, original_text, anchor_offset, feedback, round_id=round_id, branch_id=branch_id,
            )
        except RuntimeError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=409, media_type="application/json",
            )
        return {"ok": True, "status": "running"}

    @app.post("/api/setup-chat/attachments")
    async def setup_chat_upload_attachment(
        file: Annotated[UploadFile, File()],
    ):
        from engine.setup_chat.attachments import (
            ALLOWED_EXTENSIONS,
            IMAGE_EXTENSIONS,
            store_attachment,
        )
        from engine.setup_chat.image_upload_async import (
            ImageUploadStatus,
            begin_image_upload,
            schedule_image_compression,
            stream_upload_to_temp,
        )
        from utils.paths import active_novel_id

        filename = file.filename or ""
        if not filename.lower().endswith(ALLOWED_EXTENSIONS):
            return Response(
                content=json.dumps({"ok": False, "error": "仅支持 .txt/.md/.png/.jpg/.jpeg/.webp 文件"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        if filename.lower().endswith(IMAGE_EXTENSIONS):
            novel_id = active_novel_id()
            attachment_id, temp_path = begin_image_upload(novel_id, filename)
            await stream_upload_to_temp(file, temp_path)
            schedule_image_compression(attachment_id)
            result: dict = {
                "ok": True,
                "attachment_id": attachment_id,
                "filename": filename,
                "status": ImageUploadStatus.PROCESSING,
            }
            return result

        raw = await file.read()
        attachment_id = store_attachment(filename, raw)
        result = {"ok": True, "attachment_id": attachment_id, "filename": filename, "status": ImageUploadStatus.READY}
        if filename.lower().endswith((".txt", ".md")):
            from utils.config import get_config

            threshold = get_config()["novel_import"]["warn_threshold_chars"]
            char_count = len(raw.decode("utf-8", errors="replace"))
            if char_count > threshold:
                result["warning"] = (
                    f"文件字数（约 {char_count}）超过提醒阈值（{threshold}），"
                    "处理会更耗时/耗费更多调用，仍会正常导入。"
                )
        return result

    @app.get("/api/setup-chat/attachments/{attachment_id}/status")
    async def setup_chat_attachment_status(attachment_id: str) -> dict:
        from engine.setup_chat.attachments import is_image_attachment_ready
        from engine.setup_chat.image_upload_async import (
            ImageUploadStatus,
            get_image_upload_error,
            get_image_upload_status,
        )
        from fastapi import HTTPException

        status = get_image_upload_status(attachment_id)
        if status is None:
            if is_image_attachment_ready(attachment_id):
                return {"ok": True, "status": ImageUploadStatus.READY}
            raise HTTPException(status_code=404, detail="附件不存在")
        body: dict = {"ok": True, "status": status}
        if status == ImageUploadStatus.ERROR:
            body["error"] = get_image_upload_error(attachment_id) or "图片处理失败"
        return body

    @app.delete("/api/setup-chat/attachments/{attachment_id}")
    async def setup_chat_delete_attachment(attachment_id: str) -> dict:
        from engine.setup_chat.attachments import delete_attachment

        delete_attachment(attachment_id)
        return {"ok": True}

    @app.get("/api/setup-chat/attachments/library")
    async def setup_chat_attachment_library() -> dict:
        from engine.setup_chat.attachment_persistence import list_persisted_attachments
        from utils.paths import active_novel_id

        items = list_persisted_attachments(active_novel_id())
        return {
            "ok": True,
            "attachments": [
                {
                    "attachment_id": m.attachment_id,
                    "filename": m.filename,
                    "kind": m.kind,
                    "size_bytes": m.size_bytes,
                    "uploaded_at": m.uploaded_at,
                    "has_description": m.has_description,
                }
                for m in items
            ],
        }

    @app.get("/api/setup-chat/attachments/{attachment_id}/parsed")
    async def setup_chat_attachment_parsed(attachment_id: str) -> dict:
        from engine.setup_chat.attachment_persistence import (
            find_persisted_attachment,
            load_attachment_parsed_content,
        )
        from fastapi import HTTPException
        from utils.paths import active_novel_id

        novel_id = active_novel_id()
        meta = find_persisted_attachment(novel_id, attachment_id)
        if meta is None:
            raise HTTPException(status_code=404, detail="附件不存在")
        content = load_attachment_parsed_content(novel_id, attachment_id)
        return {
            "ok": True,
            "attachment_id": meta.attachment_id,
            "filename": meta.filename,
            "kind": meta.kind,
            "content": content,
            "has_content": content is not None,
        }

    @app.get("/api/setup-chat/attachments/{attachment_id}/file")
    async def setup_chat_attachment_file(attachment_id: str):
        import mimetypes

        from engine.setup_chat.attachment_persistence import load_persisted_attachment_bytes
        from fastapi import HTTPException
        from fastapi.responses import Response
        from utils.paths import active_novel_id

        loaded = load_persisted_attachment_bytes(active_novel_id(), attachment_id)
        if loaded is None:
            raise HTTPException(status_code=404, detail="附件不存在")
        filename, raw = loaded
        media_type, _ = mimetypes.guess_type(filename)
        return Response(content=raw, media_type=media_type or "application/octet-stream")

    @app.post("/api/character-portrait/generate")
    async def generate_character_portrait_endpoint(request: Request):
        from engine.setup_chat.character_portrait_generation import (
            schedule_character_portrait_generation,
        )
        from fastapi import Response

        body = await request.json()
        name = str(body.get("character_name", "")) if isinstance(body, dict) else ""
        if not name:
            return Response(
                content=json.dumps({"ok": False, "error": "character_name 不能为空"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        schedule_character_portrait_generation(name)
        return {"ok": True, "status": "queued"}

    @app.get("/api/character-portrait/{name}/file")
    async def character_portrait_file_endpoint(name: str):
        from fastapi import HTTPException, Response
        from repositories import get_lore_repo
        from utils.paths import portrait_path

        roster = get_lore_repo().list_raw()
        char = next((c for c in roster if isinstance(c, dict) and c.get("name") == name), None)
        filename = char.get("portrait_path") if char else None
        if not filename:
            raise HTTPException(status_code=404, detail="立绘不存在")

        try:
            with open(portrait_path(filename), "rb") as f:
                raw = f.read()
        except OSError as exc:
            raise HTTPException(status_code=404, detail="立绘文件缺失") from exc

        return Response(content=raw, media_type="image/png")

    @app.get("/api/setup-chat/skills")
    async def setup_chat_skills_endpoint() -> dict:
        """skill 注册表全量索引（含 plot-extension，供前端 / 斜杠菜单）；只回展示字段。"""
        from engine.setup_chat import skills as skill_registry

        items = skill_registry.list_skill_index(skill_registry.setup_chat_skill_dirs())
        return {"skills": [
            {"name": it["name"], "description": it["description"],
             "kind": it["kind"], "source": it["source"]}
            for it in items
        ]}

    #──Novel files (multi-novel isolation)────────────────────────────────────────────
    @app.get("/api/novels")
    async def list_novels_endpoint() -> dict:
        from api.services.novels import list_novels
        return {"novels": list_novels()}

    @app.post("/api/novels")
    async def create_novel_endpoint(body: dict):
        from fastapi import Response

        from api.services.novels import create_novel
        name = str((body or {}).get("name", "")).strip()
        if not name:
            return Response(
                content=json.dumps({"ok": False, "error": "name 不能为空"}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        nid = create_novel(name, clone=bool((body or {}).get("clone", False)))
        return {"ok": True, "id": nid}

    @app.post("/api/novels/{nid}/copy")
    async def copy_novel_endpoint(nid: str, body: dict):
        from fastapi import Response

        from api.services.novels import copy_novel, list_novels

        src = next((n for n in list_novels() if n["id"] == nid), None)
        if src is None:
            return Response(
                content=json.dumps({"ok": False, "error": "小说不存在"}, ensure_ascii=False),
                status_code=404, media_type="application/json",
            )
        default_name = f"{src['name']} 副本"
        name = str((body or {}).get("name", default_name)).strip() or default_name
        try:
            new_id = copy_novel(nid, name)
        except ValueError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        return {"ok": True, "id": new_id}

    @app.post("/api/novels/active")
    async def set_active_novel_endpoint(body: dict):
        from fastapi import Response

        from api.services.novels import set_active
        nid = str((body or {}).get("id", ""))
        try:
            set_active(nid)
        except ValueError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        _hub_instance()._gateway.set_focus(nid)
        return {"ok": True}

    @app.get("/api/novels/status")
    async def novels_status_endpoint() -> dict:
        """Snapshot of which novels currently have a running background task, keyed by
        novel_id -- for the frontend's novel-list status dot to initialize from on mount
        (lifecycle WS events only carry future transitions, not "what's already running")."""
        from engine.setup_chat import skeleton_pipeline
        from engine.setup_chat.timeline_auto import is_cascade_active
        from engine.setup_chat.world_background_review import is_world_review_active

        from api.services.novels import list_novels

        hub = _hub_instance()
        return {
            n["id"]: {
                "author_loop": hub.is_pipeline_busy(n["id"]),
                "setup_chat": hub.is_setup_chat_busy(n["id"]),
                "story_sandbox": hub.is_story_sandbox_busy(n["id"]),
                "skeleton_review": skeleton_pipeline.any_review_active(n["id"]),
                "timeline_cascade": is_cascade_active(n["id"]),
                "world_review": is_world_review_active(n["id"]),
            }
            for n in list_novels()
        }

    @app.patch("/api/novels/{nid}")
    async def update_novel_endpoint(nid: str, body: dict):
        from fastapi import Response

        from api.services.novels import rename_novel, set_novel_pinned

        body = body or {}
        try:
            if "name" in body:
                name = str(body.get("name", "")).strip()
                if not name:
                    return Response(
                        content=json.dumps({"ok": False, "error": "name 不能为空"}, ensure_ascii=False),
                        status_code=400, media_type="application/json",
                    )
                rename_novel(nid, name)
            if "pinned" in body:
                set_novel_pinned(nid, bool(body.get("pinned")))
        except ValueError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        return {"ok": True}

    @app.delete("/api/novels/{nid}")
    async def delete_novel_endpoint(nid: str):
        from fastapi import Response

        from api.services.novels import delete_novel

        hub = _hub_instance()
        if (
            hub.is_setup_chat_busy(nid)
            or hub.is_pipeline_busy(nid)
            or hub.is_story_sandbox_busy(nid)
        ):
            return Response(
                content=json.dumps({"ok": False, "error": "有任务运行中，无法删除小说"}, ensure_ascii=False),
                status_code=409, media_type="application/json",
            )

        async def release_handles() -> None:
            from engine.memory_recall.entity_index import invalidate_entity_vocab_cache
            from repositories import drop_repositories

            drop_repositories(nid)
            invalidate_entity_vocab_cache(nid)
            # Both are now surgical per-novel operations (see Plan 2 / the story_sandbox
            # checkpointer follow-up fix) -- always run them for the novel being deleted,
            # regardless of whether it happens to be the currently focused one, so a
            # non-focused novel's setup-chat/sandbox connections aren't left open (and its
            # sqlite files left un-deletable) just because nothing else ever touched them.
            await hub.reset_setup_chat(nid)
            await hub.reset_story_sandbox(nid)

        try:
            delete_novel(nid, release_handles=release_handles)
        except ValueError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        return {"ok": True}

    @app.get("/api/prose-styles")
    async def list_prose_styles_endpoint() -> dict:
        from engine.execution.prose_style import list_prose_style_presets

        return {"styles": list_prose_style_presets()}

    @app.get("/api/prose-styles/{preset_id}")
    async def get_prose_style_content_endpoint(preset_id: str):
        from engine.execution.prose_style import load_preset_card

        content = load_preset_card(preset_id)
        if not content:
            return Response(
                content=json.dumps({"ok": False, "error": f"未知 preset: {preset_id}"}, ensure_ascii=False),
                status_code=404,
                media_type="application/json",
            )
        return {"id": preset_id, "content": content}

    @app.get("/api/author-loop/review-hooks/{name}")
    async def get_review_hook_card_endpoint(name: str):
        from engine.author_loop.review.review_loader import REVIEW_HOOKS, get_review_hook_card

        if name not in {h.name for h in REVIEW_HOOKS}:
            return Response(
                content=json.dumps({"ok": False, "error": f"未知 review hook: {name}"}, ensure_ascii=False),
                status_code=404,
                media_type="application/json",
            )
        return {"content": get_review_hook_card(name)}

    @app.get("/api/novels/{nid}/prose-style")
    async def get_prose_style_endpoint(nid: str) -> dict:
        from api.services.novels import get_prose_style

        return get_prose_style(nid)

    @app.put("/api/novels/{nid}/prose-style")
    async def set_prose_style_endpoint(nid: str, body: dict):
        from engine.execution.prose_style import list_prose_style_presets
        from fastapi import Response

        from api.services.novels import set_prose_style

        preset = str((body or {}).get("preset", "")).strip()
        custom_addendum = str((body or {}).get("custom_addendum", "") or "")
        valid_ids = {s["id"] for s in list_prose_style_presets()}
        if preset not in valid_ids:
            return Response(
                content=json.dumps(
                    {"ok": False, "error": f"未知 preset: {preset}"},
                    ensure_ascii=False,
                ),
                status_code=400,
                media_type="application/json",
            )
        try:
            set_prose_style(nid, preset, custom_addendum)
        except ValueError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=400,
                media_type="application/json",
            )
        return {"ok": True}

    @app.get("/api/novels/{nid}/source-franchise")
    async def get_source_franchise_endpoint(nid: str) -> dict:
        from api.services.novels import get_source_franchise

        return {"franchise": get_source_franchise(nid)}

    @app.put("/api/novels/{nid}/source-franchise")
    async def set_source_franchise_endpoint(nid: str, body: dict):
        from fastapi import Response

        from api.services.novels import set_source_franchise

        franchise = str((body or {}).get("franchise", ""))
        try:
            set_source_franchise(nid, franchise)
        except ValueError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=404,
                media_type="application/json",
            )
        # A franchise change shifts which identity tag (if any) the extractor should lead
        # with, so every cast member's prompt cache needs recomputing.
        from engine.setup_chat.character_visual_tags import schedule_extract_visual_tags_all

        schedule_extract_visual_tags_all()
        return {"ok": True, "franchise": franchise.strip()}

    @app.get("/api/state-derive-fields")
    async def list_state_derive_fields_endpoint() -> dict:
        from context.content_packs import state_derive_fields_api

        return {"fields": state_derive_fields_api()}

    @app.get("/api/custom-fields")
    async def list_custom_fields_endpoint() -> dict:
        from context.content_packs import custom_fields_api

        return {"fields": custom_fields_api()}

    @app.get("/api/novels/{nid}/sandbox-dialogue-turn-count")
    async def get_sandbox_dialogue_turn_count_endpoint(nid: str) -> dict:
        from api.services.novels import get_sandbox_dialogue_turn_count

        return {"turn_count": get_sandbox_dialogue_turn_count(nid)}

    @app.put("/api/novels/{nid}/sandbox-dialogue-turn-count")
    async def set_sandbox_dialogue_turn_count_endpoint(nid: str, body: dict):
        from fastapi import Response

        from api.services.novels import set_sandbox_dialogue_turn_count

        raw = (body or {}).get("turn_count")
        if raw is not None and (
            not isinstance(raw, int) or isinstance(raw, bool) or not (1 <= raw <= 20)
        ):
            return Response(
                content=json.dumps(
                    {"ok": False, "error": "轮数须为 1–20 的整数，或留空恢复自动"}, ensure_ascii=False,
                ),
                status_code=400,
                media_type="application/json",
            )
        try:
            set_sandbox_dialogue_turn_count(nid, raw)
        except ValueError as e:
            return Response(
                content=json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                status_code=400,
                media_type="application/json",
            )
        return {"ok": True}


    @app.post("/api/auth/register")
    async def cloud_auth_register(body: dict):
        from utils.config import get_config

        from api.services import cloud_auth

        try:
            return await cloud_auth.register(get_config(), body.get("email", ""), body.get("password", ""))
        except cloud_auth.CloudAuthError as e:
            return Response(
                content=json.dumps({"ok": False, "error_code": e.error_code}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )

    @app.post("/api/auth/confirm")
    async def cloud_auth_confirm(body: dict):
        from utils.config import get_config

        from api.services import cloud_auth

        try:
            await cloud_auth.confirm(get_config(), body.get("email", ""), body.get("confirmation_code", ""))
            return {"ok": True}
        except cloud_auth.CloudAuthError as e:
            return Response(
                content=json.dumps({"ok": False, "error_code": e.error_code}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )

    @app.post("/api/auth/login")
    async def cloud_auth_login(body: dict):
        from utils.config import get_config

        from api.services import cloud_auth

        try:
            await cloud_auth.login(get_config(), body.get("email", ""), body.get("password", ""))
        except cloud_auth.CloudAuthError as e:
            return Response(
                content=json.dumps({"ok": False, "error_code": e.error_code}, ensure_ascii=False),
                status_code=400, media_type="application/json",
            )
        await _hub_instance().broadcast({"type": "cloud_auth_login_succeeded"})
        return {"ok": True}

    @app.post("/api/auth/oauth/start")
    async def cloud_auth_oauth_start(body: dict):
        from utils.config import get_config

        from api.services import cloud_auth

        async def _run_and_broadcast() -> None:
            try:
                await cloud_auth.start_google_login(get_config())
            except cloud_auth.CloudAuthError as e:
                await _hub_instance().broadcast({"type": "cloud_auth_login_failed", "error_code": e.error_code})
            except Exception:  # noqa: BLE001 - background failures must surface to the user
                logging.getLogger(__name__).exception("google login background task crashed")
                await _hub_instance().broadcast({"type": "cloud_auth_login_failed", "error_code": "OAUTH_FAILED"})
            else:
                await _hub_instance().broadcast({"type": "cloud_auth_login_succeeded"})

        asyncio.create_task(_run_and_broadcast())
        return {"status": "waiting_for_browser"}

    @app.post("/api/auth/logout")
    async def cloud_auth_logout(body: dict):
        from utils.config import get_config

        from api.services import cloud_auth

        await cloud_auth.logout(get_config())
        await _hub_instance().broadcast({"type": "cloud_auth_logged_out"})
        return {"ok": True}

    @app.get("/api/auth/status")
    async def cloud_auth_status():
        from api.services import cloud_auth

        return {"logged_in": cloud_auth.is_logged_in()}


def register_ws(app: FastAPI) -> None:
    """客户端 WebSocket 端点（combined 用；engine 角色不注册——浏览器只连 Gateway）。

    纯 server→client 单向广播：客户端不再回传消息，仅靠 receive 感知断连后清理。"""

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        hub = _hub_instance()
        await ws.accept()
        since_seq = parse_since_seq(ws.query_params.get("since_seq"))
        await hub.add_client(ws, since_seq)
        try:
            while True:
                await ws.receive_json()  #仅用于感知断连；客户端无入站语义,丢弃内容
        except WebSocketDisconnect:
            hub.remove_client(ws)
        except Exception:  # noqa: BLE001 — 断连即清理,避免连接泄漏
            hub.remove_client(ws)


def register_static(app: FastAPI) -> None:
    """静态 SPA 服务（Web 边缘用：combined 进程 或 gateway 进程复用）。"""
    dist = dist_dir()
    if not dist.exists():
        return
    app.mount("/assets", StaticFiles(directory=str(dist / "assets")), name="assets")

    @app.get("/favicon.svg")
    async def favicon() -> FileResponse:
        return FileResponse(str(dist / "favicon.svg"))

    @app.get("/icons.svg")
    async def icons() -> FileResponse:
        return FileResponse(str(dist / "icons.svg"))

    @app.get("/")
    async def serve_index() -> FileResponse:
        return FileResponse(str(dist / "index.html"))

    @app.get("/{path:path}")
    async def serve_spa(path: str) -> FileResponse:
        file_path = dist / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(dist / "index.html"))


def register_routes(app: FastAPI, *, role: GatewayRole = GatewayRole.COMBINED) -> None:
    """按角色注册路由：combined=rest+ws+static（今天）；engine=仅 rest。"""
    register_rest(app)
    if role is GatewayRole.COMBINED:
        register_ws(app)
        register_static(app)
