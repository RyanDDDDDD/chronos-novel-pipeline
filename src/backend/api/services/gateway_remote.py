"""引擎侧出站网关客户端：经持久 WS 把出站事件推给独立 Gateway 进程。

出站（含高频 token）走一条常连 WS，断线指数退避重连；未连上时 broadcast 丢弃
（token 允许丢，里程碑事件靠引擎侧 journal 兜底、客户端重连读 journal/history 恢复）。
纯出站单向：客户端不再回传消息，无入站分发。
"""
from __future__ import annotations

import asyncio
import json

from loguru import logger

_MAX_BACKOFF_S = 30.0


class GatewayRemoteClient:
    def __init__(self, ws_url: str) -> None:
        self._url = ws_url
        self._conn: object | None = None  # 活跃 websockets 连接；None=未连上
        self._task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._stopped = False

    async def start(self) -> None:
        """起后台重连任务（幂等：已起则不重复）。"""
        if self._task is None:
            self._stopped = False
            self._task = asyncio.create_task(self._reconnect_loop())

    async def close(self) -> None:
        """停重连任务并关闭连接。"""
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        conn = self._conn
        self._conn = None
        if conn is not None:
            try:
                await conn.close()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 — 关连接失败不致命
                pass

    async def _reconnect_loop(self) -> None:
        from websockets.asyncio.client import connect

        backoff = 1.0
        while not self._stopped:
            try:
                async with connect(self._url) as conn:
                    self._conn = conn
                    backoff = 1.0
                    logger.info("[gateway-client] 已连上 Gateway {}", self._url)
                    await conn.wait_closed()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — 连接失败退避重试，不致命
                logger.warning("[gateway-client] 连接失败,{}s 后重试: {}", backoff, exc)
            finally:
                self._conn = None
            if self._stopped:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _MAX_BACKOFF_S)

    async def broadcast(self, event: dict) -> None:
        """连上则推出站信封；未连上静默丢弃（不抛、不阻塞写作）。"""
        conn = self._conn
        if conn is None:
            return
        try:
            await conn.send(  # type: ignore[attr-defined]
                json.dumps({"op": "broadcast", "event": event}, ensure_ascii=False)
            )
        except Exception as exc:  # noqa: BLE001 — 单帧发送失败不致命,重连由 loop 负责
            logger.debug("[gateway-client] broadcast 发送失败: {}", exc)

    def clear_buffer(self) -> None:
        if self._conn is None:
            return
        asyncio.create_task(self._send_op({"op": "clear_buffer"}))

    async def _send_op(self, payload: dict) -> None:
        conn = self._conn
        if conn is None:
            return
        try:
            await conn.send(json.dumps(payload, ensure_ascii=False))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.debug("[gateway-client] 控制帧发送失败: {}", exc)

    async def add_client(self, ws: object, since_seq: int = 0) -> None:
        """引擎不直接持客户端 WS,no-op。"""

    def remove_client(self, ws: object) -> None:
        """引擎不直接持客户端 WS,no-op。"""

    def set_focus(self, novel_id: str) -> None:
        """No-op: this process (engine role) doesn't hold browser connections -- focus state
        lives in the Gateway process's Gateway instance, reached via a REST call to that
        process, not through this remote relay."""

    def get_focus(self) -> str | None:
        return None
