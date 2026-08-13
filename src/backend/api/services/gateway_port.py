"""GatewayPort：MessageHub 依赖的交互网关抽象。

同进程 inproc 用 Gateway（IO 内核）；engine 角色用 GatewayRemoteClient 经持久 WS
把出站事件推给独立 Gateway 进程。选择由 CHRONOS_ROLE 决定，缺省 combined（今天行为）。
"""
from __future__ import annotations

import os
from enum import StrEnum
from typing import Protocol, runtime_checkable


class GatewayRole(StrEnum):
    COMBINED = "combined"
    ENGINE = "engine"
    GATEWAY = "gateway"


def current_role() -> GatewayRole:
    """当前进程角色；未设 CHRONOS_ROLE → combined（单进程，与今天一致）。"""
    raw = os.environ.get("CHRONOS_ROLE", "").strip().lower()
    try:
        return GatewayRole(raw) if raw else GatewayRole.COMBINED
    except ValueError:
        return GatewayRole.COMBINED


@runtime_checkable
class GatewayPort(Protocol):
    async def broadcast(self, event: dict) -> None: ...
    def clear_buffer(self) -> None: ...
    async def add_client(self, ws: object, since_seq: int = 0) -> None: ...
    def remove_client(self, ws: object) -> None: ...
    def set_focus(self, novel_id: str) -> None: ...
    def get_focus(self) -> str | None: ...
    async def start(self) -> None: ...
    async def close(self) -> None: ...


def parse_since_seq(raw: str | None) -> int:
    """Parse the `/ws?since_seq=` query param a reconnecting client sends back -- the highest
    buffered event `_seq` it already applied. Missing/malformed values fall back to 0, which
    replays the full buffer (same as a first-time connect)."""
    try:
        return max(0, int(raw)) if raw else 0
    except ValueError:
        return 0


def make_gateway() -> GatewayPort:
    """按角色装配网关端口：engine → 远程客户端；其余 → inproc Gateway。"""
    if current_role() is GatewayRole.ENGINE:
        from api.services.gateway_remote import GatewayRemoteClient

        ws_url = os.environ.get("CHRONOS_GATEWAY_WS")
        if not ws_url:
            raise RuntimeError("engine 角色缺少 CHRONOS_GATEWAY_WS（引擎无法连 Gateway）")
        remote: GatewayPort = GatewayRemoteClient(ws_url)
        return remote
    from api.services.gateway import Gateway

    return Gateway()
