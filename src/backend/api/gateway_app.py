"""Gateway 进程：面向多平台客户端的唯一公网边缘。

职责:直出 Web SPA 静态 + 终结客户端 /ws(fan-out+replay) + 反代 /api 到引擎
+ 收引擎连入的 /internal/engine 出站事件。不导入 MessageHub(引擎编排全在引擎进程)。
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from loguru import logger

from api.routes import register_static
from api.services.gateway import Gateway
from api.services.gateway_port import parse_since_seq

_GATEWAY = Gateway()
_HOP_BY_HOP = {
    "connection", "keep-alive", "transfer-encoding", "te", "trailer",
    "upgrade", "proxy-authorization", "proxy-authenticate", "host",
    "content-length",
}


def engine_url() -> str:
    """引擎内网地址(反代 + 入站 POST 目标)。"""
    return os.environ.get("CHRONOS_ENGINE_URL", "http://127.0.0.1:8776")


@asynccontextmanager
async def _lifespan(app: FastAPI):  # noqa: ARG001
    app.state.http = httpx.AsyncClient(base_url=engine_url(), timeout=None)
    yield
    await app.state.http.aclose()


app = FastAPI(title="Chronos Gateway", lifespan=_lifespan)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    """客户端 WS:回放 buffer + fan-out(纯 server→client);仅靠 receive 感知断连。"""
    await ws.accept()
    since_seq = parse_since_seq(ws.query_params.get("since_seq"))
    await _GATEWAY.add_client(ws, since_seq)
    try:
        while True:
            await ws.receive_json()  #客户端无入站语义,丢弃内容;断连时抛出触发清理
    except WebSocketDisconnect:
        _GATEWAY.remove_client(ws)
    except Exception:  # noqa: BLE001 — 断连即清理
        _GATEWAY.remove_client(ws)


@app.websocket("/internal/engine")
async def engine_endpoint(ws: WebSocket) -> None:
    """引擎连入的出站通道:收 {"op":...} → 本地 Gateway 处理。"""
    await ws.accept()
    logger.info("[gw] 引擎已连入 /internal/engine")
    try:
        while True:
            msg = await ws.receive_json()
            op = msg.get("op")
            if op == "broadcast":
                await _GATEWAY.broadcast(msg.get("event", {}))
            elif op == "clear_buffer":
                _GATEWAY.clear_buffer()
    except WebSocketDisconnect:
        logger.info("[gw] 引擎断开 /internal/engine")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[gw] /internal/engine 异常: {}", exc)


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_api(path: str, request: Request) -> Response:
    """反代 /api/* 到引擎:透传 method/query/headers/body,回传响应。"""
    client: httpx.AsyncClient = app.state.http
    url = httpx.URL(path="/api/" + path, query=request.url.query.encode("utf-8"))
    headers = [(k, v) for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP]
    body = await request.body()
    try:
        resp = await client.request(request.method, url, headers=headers, content=body)
    except httpx.HTTPError as exc:
        logger.warning("[gw] 反代引擎失败 {} {}: {}", request.method, path, exc)
        return Response(
            content=b'{"ok":false,"error":"engine unreachable"}',
            status_code=502, media_type="application/json",
        )
    out_headers = {k: v for k, v in resp.headers.items() if k.lower() not in _HOP_BY_HOP}
    return Response(content=resp.content, status_code=resp.status_code, headers=out_headers)


register_static(app)  #静态 SPA catch-all 必须最后注册(在 /api、/ws 之后)

__all__ = ["app", "engine_url"]
