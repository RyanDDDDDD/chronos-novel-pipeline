"""In-process service connectivity status for the novel-rail indicators.

The backend owns when pings run (startup + config save + explicit POST) and
persists the last result for the process lifetime; the frontend only reads
GET /api/health/service-status."""
from __future__ import annotations

from typing import Literal, TypedDict

PingStatus = Literal["unknown", "checking", "ok", "error", "disabled"]


class PingEntry(TypedDict):
    status: PingStatus
    error: str | None


class ServicePingStatus(TypedDict):
    llm: PingEntry
    search: PingEntry


_state: ServicePingStatus = {
    "llm": {"status": "unknown", "error": None},
    "search": {"status": "unknown", "error": None},
}


def get_service_status() -> ServicePingStatus:
    llm = _state["llm"]
    search = _state["search"]
    return {
        "llm": {"status": llm["status"], "error": llm["error"]},
        "search": {"status": search["status"], "error": search["error"]},
    }


def _set_entry(target: Literal["llm", "search"], status: PingStatus, error: str | None = None) -> None:
    _state[target] = {"status": status, "error": error}


def _apply_ping_result(target: Literal["llm", "search"], result: dict) -> dict:
    if result.get("ok"):
        _set_entry(target, "ok", None)
    else:
        _set_entry(target, "error", result.get("error"))
    return result


async def run_ping_llm(cfg: dict) -> dict:
    from api.services.service_ping import ping_llm

    _set_entry("llm", "checking", None)
    return _apply_ping_result("llm", await ping_llm(cfg))


async def run_ping_search(cfg: dict) -> dict:
    from api.services.service_ping import ping_search

    _set_entry("search", "checking", None)
    return _apply_ping_result("search", await ping_search(cfg))


async def run_startup_pings(cfg: dict) -> None:
    """LLM always; search only when api.search_ping_enabled (startup gate)."""
    await run_ping_llm(cfg)
    api_cfg = cfg.get("api") or {}
    if api_cfg.get("search_ping_enabled"):
        await run_ping_search(cfg)
    else:
        _set_entry("search", "disabled", None)


async def run_config_save_pings(cfg: dict) -> None:
    """Always re-check both providers after a config save (manual ping)."""
    await run_ping_llm(cfg)
    await run_ping_search(cfg)
