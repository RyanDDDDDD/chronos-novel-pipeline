import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient


def _module(monkeypatch):
    monkeypatch.setenv("CHRONOS_ENGINE_URL", "http://127.0.0.1:8776")
    import importlib

    import api.gateway_app as ga

    return importlib.reload(ga)


def test_engine_ws_broadcast_fans_out_to_client(monkeypatch):
    ga = _module(monkeypatch)
    with TestClient(ga.app) as client:
        with client.websocket_connect("/ws") as browser:
            with client.websocket_connect("/internal/engine") as engine:
                engine.send_json(
                    {"op": "broadcast", "event": {"type": "author_loop_state", "chapter": 1}}
                )
                msg = browser.receive_json()
    assert msg == {"type": "author_loop_state", "chapter": 1, "_seq": 1}


def test_engine_ws_clear_buffer_route_ok(monkeypatch):
    ga = _module(monkeypatch)
    with TestClient(ga.app) as client:
        with client.websocket_connect("/internal/engine") as engine:
            engine.send_json({"op": "broadcast", "event": {"type": "x"}})
            engine.send_json({"op": "clear_buffer"})
    # buffer 语义由 Gateway 单测覆盖;此处只验路由不抛


def test_routes_registered(monkeypatch):
    ga = _module(monkeypatch)
    paths = {getattr(r, "path", "") for r in ga.app.routes}
    assert "/api/{path:path}" in paths
    assert "/ws" in paths
    assert "/internal/engine" in paths


def test_engine_url_default(monkeypatch):
    monkeypatch.delenv("CHRONOS_ENGINE_URL", raising=False)
    import importlib

    import api.gateway_app as ga
    importlib.reload(ga)
    assert ga.engine_url() == "http://127.0.0.1:8776"
