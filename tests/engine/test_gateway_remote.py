import json

import pytest
from api.services.gateway_remote import GatewayRemoteClient


class _FakeConn:
    def __init__(self):
        self.sent: list = []

    async def send(self, data):
        self.sent.append(json.loads(data))


@pytest.mark.asyncio
async def test_broadcast_when_connected_sends_envelope():
    c = GatewayRemoteClient("ws://x/internal/engine")
    conn = _FakeConn()
    c._conn = conn  # 注入活跃连接
    await c.broadcast({"type": "author_loop_token", "delta": "字"})
    assert conn.sent == [
        {"op": "broadcast", "event": {"type": "author_loop_token", "delta": "字"}}
    ]


@pytest.mark.asyncio
async def test_broadcast_when_disconnected_drops_silently():
    c = GatewayRemoteClient("ws://x/internal/engine")
    c._conn = None
    await c.broadcast({"type": "x"})  # 不抛


@pytest.mark.asyncio
async def test_clear_buffer_when_connected_schedules_send():
    c = GatewayRemoteClient("ws://x/internal/engine")
    conn = _FakeConn()
    c._conn = conn
    c.clear_buffer()
    # clear_buffer 用 create_task 异步发送，让出一拍等它跑完
    import asyncio

    await asyncio.sleep(0)
    assert conn.sent == [{"op": "clear_buffer"}]


@pytest.mark.asyncio
async def test_add_remove_client_are_noop():
    c = GatewayRemoteClient("ws://x/internal/engine")
    await c.add_client(object())
    c.remove_client(object())  # 不抛、不维护列表
