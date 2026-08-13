"""Frontend liveness watchdog: the Tauri shell pings /api/heartbeat every 5s while its
process is alive (release sidecar and, since the dev-startup-self-heal revision, `tauri
dev` debug builds too); if this backend stops hearing from it for HEARTBEAT_TIMEOUT_S,
the frontend is assumed dead (crashed, force-killed -- anything that skipped the normal
ExitRequested -> POST /api/shutdown path) and this process shuts itself down the same
way an explicit /api/shutdown call would. Pure HTTP, no OS process-tree APIs -- identical
on Windows and Linux (spec 2026-07-16-frontend-heartbeat-watchdog-design.md, D4 revised)."""
from __future__ import annotations

import time

from loguru import logger

from api.services.scheduler import EventScheduler

HEARTBEAT_TIMEOUT_S = 20.0
WATCHDOG_CHECK_INTERVAL_S = 5.0

_last_heartbeat: float | None = None


def record_heartbeat() -> None:
    global _last_heartbeat
    _last_heartbeat = time.monotonic()


def trigger_graceful_shutdown(reason: str) -> None:
    """Reused by both POST /api/shutdown and the watchdog timeout branch below --
    one shutdown entry point, two triggers (explicit request vs. frontend silence).
    Logs `reason` before raising so server.log always records which of the two
    fired -- previously only the watchdog branch logged, so an explicit
    /api/shutdown call (Tauri ExitRequested) was indistinguishable in the log
    from the watchdog reaping a genuinely silent frontend."""
    import signal

    logger.warning("[graceful-shutdown] triggering SIGTERM: {}", reason)
    signal.raise_signal(signal.SIGTERM)


async def _check_heartbeat() -> None:
    if _last_heartbeat is None:
        return
    idle_s = time.monotonic() - _last_heartbeat
    if idle_s > HEARTBEAT_TIMEOUT_S:
        trigger_graceful_shutdown(
            f"no heartbeat for {idle_s:.1f}s (timeout {HEARTBEAT_TIMEOUT_S}s) -- frontend assumed dead"
        )


def register_heartbeat_watchdog(scheduler: EventScheduler) -> None:
    """Call once at startup (_lifespan, alongside register_shutdown_hooks/register_startup_warmup).

    Always registers, regardless of how this process was launched. Stays dormant until the
    first real /api/heartbeat POST lands (record_heartbeat) -- _check_heartbeat's own
    `if _last_heartbeat is None: return` guard is what keeps it inert until then, so this
    deliberately does NOT seed _last_heartbeat here.

    D4 revision: the original design seeded _last_heartbeat to "now" at registration time,
    treating that as a free grace period -- valid only when the sidecar and its heartbeat
    sender start together (release: Tauri spawns both in the same breath). Dev mode breaks
    that assumption: the backend is started first by the sequenced launcher, and `tauri dev`'s
    cargo build can take well over HEARTBEAT_TIMEOUT_S before its heartbeat_loop sends anything
    -- seeding at registration would false-positive-kill a backend that's still waiting on a
    slow compile. Waiting for the real first heartbeat removes that failure mode in both modes."""
    scheduler.register_periodic("heartbeat_watchdog", WATCHDOG_CHECK_INTERVAL_S, _check_heartbeat)
