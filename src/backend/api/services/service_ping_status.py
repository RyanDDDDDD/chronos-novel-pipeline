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


async def _run_free_search_ping(cfg: dict) -> None:
    from api.services.service_ping import ping_search_free

    _set_entry("search", "checking", None)
    result = await ping_search_free(cfg)
    if result is None:
        _set_entry("search", "disabled", "当前检索服务商无免费连通性检测接口，如需验证请手动测试")
    else:
        _apply_ping_result("search", result)


async def run_startup_pings(cfg: dict) -> None:
    """Both LLM and search always -- search via the free check (see
    ping_search_free), so startup never spends real quota on its own. No
    opt-in gate needed now that the automatic path can't cost anything."""
    await run_ping_llm(cfg)
    await _run_free_search_ping(cfg)


async def run_config_save_pings(cfg: dict) -> None:
    """Always re-check LLM; search re-checked via the free path only (see
    run_startup_pings) -- config saves happen often enough during normal use
    that spending real search quota on every save isn't acceptable."""
    await run_ping_llm(cfg)
    await _run_free_search_ping(cfg)
