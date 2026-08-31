from fastapi.testclient import TestClient


def app_under_test():
    from api.hub import app
    return app


def test_register_endpoint_returns_service_response(monkeypatch):
    async def _fake_register(cfg, email, password):
        assert email == "a@b.com"
        return {"user_sub": "sub-1", "email_verification_required": True}

    monkeypatch.setattr("utils.config.get_config", lambda: {})
    monkeypatch.setattr("api.services.cloud_auth.register", _fake_register)
    client = TestClient(app_under_test())

    r = client.post("/api/auth/register", json={"email": "a@b.com", "password": "pw"})

    assert r.status_code == 200
    assert r.json() == {"user_sub": "sub-1", "email_verification_required": True}


def test_login_endpoint_maps_cloud_auth_error_to_400(monkeypatch):
    from api.services.cloud_auth import CloudAuthError

    async def _fake_login(cfg, email, password):
        raise CloudAuthError("INVALID_CREDENTIALS", "bad creds")

    monkeypatch.setattr("utils.config.get_config", lambda: {})
    monkeypatch.setattr("api.services.cloud_auth.login", _fake_login)
    client = TestClient(app_under_test())

    r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "wrong"})

    assert r.status_code == 400
    assert r.json() == {"ok": False, "error_code": "INVALID_CREDENTIALS"}


def test_login_endpoint_broadcasts_login_succeeded(monkeypatch):
    broadcasts = []

    async def _fake_login(cfg, email, password):
        return None

    async def _fake_broadcast(self, event):
        broadcasts.append(event)

    monkeypatch.setattr("utils.config.get_config", lambda: {})
    monkeypatch.setattr("api.services.cloud_auth.login", _fake_login)
    monkeypatch.setattr("api.services.message_hub.MessageHub.broadcast", _fake_broadcast)
    client = TestClient(app_under_test())

    r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "pw"})

    assert r.status_code == 200
    assert any(e.get("type") == "cloud_auth_login_succeeded" for e in broadcasts)


def test_status_endpoint_reports_logged_in_state(monkeypatch):
    monkeypatch.setattr("api.services.cloud_auth.is_logged_in", lambda: True)
    client = TestClient(app_under_test())

    r = client.get("/api/auth/status")

    assert r.status_code == 200
    assert r.json() == {"logged_in": True}


def test_oauth_start_endpoint_returns_immediately_and_runs_in_background(monkeypatch):
    """The REST call must not block on the browser round-trip -- it kicks off a background
    task and returns right away; completion is signaled later via the WS broadcast (see the
    login test above), not via this response."""
    started = []

    async def _fake_start_google_login(cfg):
        started.append(True)

    monkeypatch.setattr("utils.config.get_config", lambda: {})
    monkeypatch.setattr("api.services.cloud_auth.start_google_login", _fake_start_google_login)
    client = TestClient(app_under_test())

    r = client.post("/api/auth/oauth/start", json={"provider": "google"})

    assert r.status_code == 200
    assert r.json() == {"status": "waiting_for_browser"}


def test_oauth_start_broadcasts_unknown_background_failure(monkeypatch):
    import asyncio

    scheduled = []
    broadcasts = []

    async def _fake_start_google_login(cfg):
        raise RuntimeError("unexpected failure")

    async def _fake_broadcast(self, event):
        broadcasts.append(event)

    def _capture_task(coro):
        scheduled.append(coro)
        return None

    monkeypatch.setattr("utils.config.get_config", lambda: {})
    monkeypatch.setattr("api.services.cloud_auth.start_google_login", _fake_start_google_login)
    monkeypatch.setattr("api.routes.asyncio.create_task", _capture_task)
    monkeypatch.setattr("api.services.message_hub.MessageHub.broadcast", _fake_broadcast)
    client = TestClient(app_under_test())

    r = client.post("/api/auth/oauth/start", json={"provider": "google"})
    asyncio.run(scheduled[0])

    assert r.status_code == 200
    assert broadcasts == [{"type": "cloud_auth_login_failed", "error_code": "OAUTH_FAILED"}]
