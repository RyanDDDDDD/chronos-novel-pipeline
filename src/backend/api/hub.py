"""MessageHub: WebSocket API Gateway

Single-process architecture: Hub manages background tasks (archive/cast/world/plot/author_loop) in the same asyncio event loop.
The front end communicates with the Hub through WebSocket, and the task progress is pushed through broadcast.

See routes.py for the routing layer; see services/ for application services."""
from __future__ import annotations

import asyncio
import traceback
from contextlib import asynccontextmanager

from engine.memory_recall.entity_index import restore_persisted_automata
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from utils.config import cors_allow_origins
from utils.paths import active_novel_id

from api.routes import register_routes
from api.services.gateway_port import current_role
from api.services.heartbeat_watchdog import register_heartbeat_watchdog
from api.services.message_hub import MessageHub
from api.services.novel_memory_scavenger import register_novel_memory_scavenger
from api.services.novels import ensure_initialized as ensure_novels_initialized
from api.services.pipeline_profiles import ensure_initialized
from api.services.scheduler import SCHEDULER, EventScheduler
from api.services.trash_purge import run_trash_purge

ensure_initialized()  #First start idempotent migration: old single pipeline → config/pipelines/default/
ensure_novels_initialized()  #First start to ensure that the novel file is ready (before init_repositories reads lore/plot)

HUB = MessageHub()


def register_shutdown_hooks(scheduler: EventScheduler, hub: MessageHub) -> None:
    """
Register the hub's shutdown release as the scheduler's on_stop hook (the two resources are independent, whether the reverse order is not affected)."""
    scheduler.on_stop("hub", hub.shutdown)  #Cancel file task + clear buffer
    scheduler.on_stop("setup_chat_conn", hub.reset_all_setup_chat)  #Off every novel's setup-chat aiosqlite connection
    scheduler.on_stop("story_sandbox_conn", hub.reset_all_story_sandbox)  # close every novel's story-sandbox aiosqlite connection

    async def _shutdown_image_uploads() -> None:
        from engine.setup_chat.image_upload_async import (
            cancel_all_image_uploads,
            shutdown_image_process_pool,
        )

        await cancel_all_image_uploads()
        await shutdown_image_process_pool()

    scheduler.on_stop("image_upload_pool", _shutdown_image_uploads)


def register_startup_warmup(scheduler: EventScheduler, hub: MessageHub) -> None:
    """Register all startup once-jobs on the scheduler (warm-up, trash purge, etc.).

    Pre-warm per-novel lazy resources for whichever novel is active at startup so a user's
    first visit doesn't pay the full cold-build cost (spec 2026-07-16-startup-agent-warmup).
    Fire-and-forget via the scheduler -- never awaited here, so /api/health's availability is
    unaffected regardless of how long these jobs take."""
    scheduler.schedule_once(
        "warm_setup_chat_agent", 0.0,
        lambda: hub._ensure_setup_chat_agent(active_novel_id()),
    )
    scheduler.schedule_once("warm_story_sandbox_checkpointer", 0.0, hub._ensure_story_sandbox_checkpointer)
    scheduler.schedule_once("restore_entity_index", 0.0, restore_persisted_automata)
    scheduler.schedule_once("trash_purge", 0.0, run_trash_purge, dedup=True)

    async def _startup_service_pings() -> None:
        from utils.config import get_config

        from api.services.service_ping_status import run_startup_pings

        await run_startup_pings(get_config())

    scheduler.schedule_once("service_ping_startup", 0.0, _startup_service_pings)

    async def _warm_novita_model_catalog() -> None:
        from domain.model_catalog import load_custom_models
        from domain.novita_model_catalog import refresh_novita_model_catalog

        entry = next(
            (m for m in load_custom_models() if m.get("provider") == "image_gen" and m.get("api_key")),
            None,
        )
        if entry is None:
            return  # 还没配过生图 key，没什么可拉的
        await refresh_novita_model_catalog(entry["api_key"])

    scheduler.schedule_once("warm_novita_model_catalog", 0.0, _warm_novita_model_catalog)


def _log_loop_exception(loop: asyncio.AbstractEventLoop, context: dict) -> None:  # noqa: ARG001
    """Route asyncio's own event-loop-level exceptions (uncaught task errors, transport
    callback failures) through loguru so they land in server.log -- by default these skip
    our logging setup entirely (stdlib `logging` straight to stderr) and are lost once the
    process exits. Windows' ProactorEventLoop is especially noisy about ConnectionResetError
    from _call_connection_lost when a peer socket was already torn down on the other end --
    confirmed (2026-08-03) as routine dev_console health-probe reconnect churn, not an app
    bug or anything that ever interrupts an in-flight generation stream. Our server.log sink
    is itself configured at DEBUG (see main.py), so merely lowering the level here doesn't
    keep it out of the file -- silently dropped instead, since there's no activity signal
    worth surfacing from a background liveness probe the user never initiated.

    RecursionError bypasses loguru's diagnose-format path and dumps a raw stdlib traceback
    instead: the 2026-08-12 field case showed only asyncio Handle._run frames after beautify
    formatting (see docs/superpowers/specs/2026-08-13-scheduler-watchdog-timeout-design.md),
    so we want the unadorned frames next time."""
    exc = context.get("exception")
    message = context.get("message", "")
    if isinstance(exc, ConnectionResetError):
        return
    if isinstance(exc, RecursionError):
        raw = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        logger.error(
            "[asyncio] unhandled loop exception (RecursionError, raw traceback dump):\n{}\n{}",
            message,
            raw,
        )
        return
    logger.opt(exception=exc).error("[asyncio] unhandled loop exception: {}", message or context)


@asynccontextmanager
async def _lifespan(app: FastAPI):  # noqa: ARG001
    from engine.execution.agent_plugin_loader import get_plugin_loader
    from repositories import init_repositories

    asyncio.get_running_loop().set_exception_handler(_log_loop_exception)

    #Independent file-IO-bound sync calls (repo scan vs. hook package scan) -- run them off-loop
    #and concurrently so startup latency doesn't stack when novel text / plugin count grows.
    await asyncio.gather(
        asyncio.to_thread(init_repositories),
        asyncio.to_thread(get_plugin_loader),  #Process-level agent hook loader, built once at startup to avoid reloading each request.
    )
    #Chapters in progress will no longer fill the buffer when starting (which will lead to cross-client pollution and multi-chapter serialization); instead, it will be filled when the front end opens a chapter.
    #Pull playback on demand via GET /api/author-loop/journal (see routes).
    register_shutdown_hooks(SCHEDULER, HUB)
    await HUB._gateway.start()  #engine 角色起出站 WS 重连;inproc 为 no-op
    SCHEDULER.start()
    register_startup_warmup(SCHEDULER, HUB)
    register_heartbeat_watchdog(SCHEDULER)
    register_novel_memory_scavenger(SCHEDULER, HUB)
    yield
    await SCHEDULER.stop()  #Replace naked await HUB.shutdown(); HUB.shutdown is already included in the hook
    await HUB._gateway.close()  #停出站 WS;inproc no-op


app = FastAPI(title="Chronos Engine WebUI", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_routes(app, role=current_role())

__all__ = ["app", "HUB"]
