"""cloud_auth: token storage (OS keyring) + AuthService HTTP calls. See chronos-cloud-services'
CONTRACT.md for the wire shapes this mirrors."""
import httpx
import pytest


def _fake_async_client(handler):
    class _FakeAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            return handler(url, json)

        async def aclose(self):
            pass

    return _FakeAsyncClient


class _FakeResp:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.headers = {"content-type": "application/json"}
        self.text = str(body)

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def _in_memory_keyring(monkeypatch):
    """Replaces the OS keyring with a plain dict so tests never touch real Windows Credential
    Manager / macOS Keychain, and are hermetic across machines/CI."""
    store: dict[tuple[str, str], str] = {}

    def _get(service, key):
        return store.get((service, key))

    def _set(service, key, value):
        store[(service, key)] = value

    def _delete(service, key):
        import keyring.errors
        if (service, key) not in store:
            raise keyring.errors.PasswordDeleteError("not found")
        del store[(service, key)]

    monkeypatch.setattr("api.services.cloud_auth.keyring.get_password", _get)
    monkeypatch.setattr("api.services.cloud_auth.keyring.set_password", _set)
    monkeypatch.setattr("api.services.cloud_auth.keyring.delete_password", _delete)
    return store


def _cfg():
    return {"api": {"cloud_auth_base_url": "https://auth.example.com"}}


@pytest.mark.asyncio
async def test_login_stores_tokens_in_keyring(monkeypatch):
    from api.services import cloud_auth

    def handler(url, json):
        assert url == "https://auth.example.com/v1/auth/login"
        assert json == {"email": "a@b.com", "password": "pw"}
        return _FakeResp(200, {"access_token": "acc", "refresh_token": "ref", "id_token": "id", "expires_in": 3600})

    monkeypatch.setattr(httpx, "AsyncClient", _fake_async_client(handler))

    await cloud_auth.login(_cfg(), "a@b.com", "pw")

    assert cloud_auth.get_access_token() == "acc"
    assert cloud_auth.get_refresh_token() == "ref"
    assert cloud_auth.is_logged_in() is True


@pytest.mark.asyncio
async def test_login_raises_cloud_auth_error_on_invalid_credentials(monkeypatch):
    from api.services import cloud_auth

    def handler(url, json):
        return _FakeResp(401, {"error_code": "INVALID_CREDENTIALS", "message": "bad creds"})

    monkeypatch.setattr(httpx, "AsyncClient", _fake_async_client(handler))

    with pytest.raises(cloud_auth.CloudAuthError) as exc_info:
        await cloud_auth.login(_cfg(), "a@b.com", "wrong")

    assert exc_info.value.error_code == "INVALID_CREDENTIALS"
    assert cloud_auth.is_logged_in() is False


@pytest.mark.asyncio
async def test_login_raises_not_configured_when_base_url_missing(monkeypatch):
    from api.services import cloud_auth

    with pytest.raises(cloud_auth.CloudAuthError) as exc_info:
        await cloud_auth.login({"api": {}}, "a@b.com", "pw")

    assert exc_info.value.error_code == "NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_refresh_clears_tokens_on_invalid_refresh_token(monkeypatch):
    from api.services import cloud_auth

    cloud_auth._store_tokens("old-acc", "old-ref", "old-id")

    def handler(url, json):
        return _FakeResp(401, {"error_code": "REFRESH_TOKEN_INVALID", "message": "expired"})

    monkeypatch.setattr(httpx, "AsyncClient", _fake_async_client(handler))

    with pytest.raises(cloud_auth.CloudAuthError):
        await cloud_auth.refresh(_cfg())

    assert cloud_auth.is_logged_in() is False


@pytest.mark.asyncio
async def test_refresh_keeps_tokens_on_network_error(monkeypatch):
    from api.services import cloud_auth

    cloud_auth._store_tokens("acc", "ref", "id")
    monkeypatch.setattr(
        cloud_auth,
        "_post",
        _raise_network_error,
    )

    with pytest.raises(cloud_auth.CloudAuthError) as exc_info:
        await cloud_auth.refresh(_cfg())

    assert exc_info.value.error_code == "NETWORK_ERROR"
    assert cloud_auth.is_logged_in() is True


async def _raise_network_error(*args, **kwargs):
    from api.services.cloud_auth import CloudAuthError

    raise CloudAuthError("NETWORK_ERROR", "offline")


@pytest.mark.asyncio
async def test_refresh_dedupes_concurrent_calls(monkeypatch):
    import asyncio

    from api.services import cloud_auth

    cloud_auth._store_tokens("acc", "ref", "id")
    refresh_calls = 0

    async def fake_post(cfg, path, json):
        nonlocal refresh_calls
        assert path == "/v1/auth/refresh"
        refresh_calls += 1
        await asyncio.sleep(0)
        return {"access_token": "new-acc", "id_token": "new-id"}

    monkeypatch.setattr(cloud_auth, "_post", fake_post)

    await asyncio.gather(cloud_auth.refresh(_cfg()), cloud_auth.refresh(_cfg()))

    assert refresh_calls == 1
    assert cloud_auth.get_access_token() == "new-acc"


@pytest.mark.asyncio
async def test_logout_clears_local_tokens_even_if_server_call_fails(monkeypatch):
    from api.services import cloud_auth

    cloud_auth._store_tokens("acc", "ref", "id")

    def handler(url, json):
        return _FakeResp(500, {"error_code": "INTERNAL_ERROR", "message": "boom"})

    monkeypatch.setattr(httpx, "AsyncClient", _fake_async_client(handler))

    await cloud_auth.logout(_cfg())

    assert cloud_auth.is_logged_in() is False


@pytest.mark.asyncio
async def test_start_google_login_stores_tokens_on_successful_callback(monkeypatch):
    from api.services import cloud_auth

    calls = []

    def handler(url, json):
        calls.append((url, json))
        if url.endswith("/v1/auth/oauth/start"):
            return _FakeResp(200, {
                "authorize_url": "https://cognito.example.com/oauth2/authorize?...",
                "code_verifier": "server-verifier",
                "state": "server-state",
            })
        assert url.endswith("/v1/auth/oauth/callback")
        assert json == {
            "provider": "google",
            "code": "the-code",
            "code_verifier": "server-verifier",
            "redirect_uri": "http://localhost:53214/callback",
        }
        return _FakeResp(200, {"access_token": "acc", "refresh_token": "ref", "id_token": "id", "expires_in": 3600})

    monkeypatch.setattr(httpx, "AsyncClient", _fake_async_client(handler))
    monkeypatch.setattr("api.services.cloud_auth.webbrowser.open", lambda url: None)

    class _FakeCallbackServer:
        async def wait_for_callback(self, timeout):
            return {"code": "the-code", "state": "server-state"}

    monkeypatch.setattr("api.services.cloud_auth._CallbackServer", lambda: _FakeCallbackServer())

    await cloud_auth.start_google_login(_cfg())

    assert cloud_auth.get_access_token() == "acc"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_start_google_login_rejects_state_mismatch(monkeypatch):
    from api.services import cloud_auth

    def handler(url, json):
        assert url.endswith("/v1/auth/oauth/start")
        return _FakeResp(200, {
            "authorize_url": "https://cognito.example.com/oauth2/authorize?...",
            "code_verifier": "server-verifier",
            "state": "server-state",
        })

    monkeypatch.setattr(httpx, "AsyncClient", _fake_async_client(handler))
    monkeypatch.setattr("api.services.cloud_auth.webbrowser.open", lambda url: None)

    class _FakeCallbackServer:
        async def wait_for_callback(self, timeout):
            return {"code": "the-code", "state": "attacker-supplied-state"}

    monkeypatch.setattr("api.services.cloud_auth._CallbackServer", lambda: _FakeCallbackServer())

    with pytest.raises(cloud_auth.CloudAuthError) as exc_info:
        await cloud_auth.start_google_login(_cfg())

    assert exc_info.value.error_code == "OAUTH_STATE_MISMATCH"
    assert cloud_auth.is_logged_in() is False


@pytest.mark.asyncio
async def test_start_google_login_raises_on_callback_timeout(monkeypatch):
    from api.services import cloud_auth

    def handler(url, json):
        return _FakeResp(200, {"authorize_url": "https://x", "code_verifier": "v", "state": "s"})

    monkeypatch.setattr(httpx, "AsyncClient", _fake_async_client(handler))
    monkeypatch.setattr("api.services.cloud_auth.webbrowser.open", lambda url: None)

    class _FakeCallbackServer:
        async def wait_for_callback(self, timeout):
            raise TimeoutError("no callback received")

    monkeypatch.setattr("api.services.cloud_auth._CallbackServer", lambda: _FakeCallbackServer())

    with pytest.raises(cloud_auth.CloudAuthError) as exc_info:
        await cloud_auth.start_google_login(_cfg())

    assert exc_info.value.error_code == "OAUTH_TIMEOUT"


@pytest.mark.asyncio
async def test_start_google_login_maps_port_busy(monkeypatch):
    from api.services import cloud_auth

    def handler(url, json):
        return _FakeResp(200, {"authorize_url": "https://x", "code_verifier": "v", "state": "s"})

    monkeypatch.setattr(httpx, "AsyncClient", _fake_async_client(handler))
    monkeypatch.setattr("api.services.cloud_auth.webbrowser.open", lambda url: None)

    def raise_port_busy():
        raise OSError("address already in use")

    monkeypatch.setattr("api.services.cloud_auth._CallbackServer", raise_port_busy)

    with pytest.raises(cloud_auth.CloudAuthError) as exc_info:
        await cloud_auth.start_google_login(_cfg())

    assert exc_info.value.error_code == "OAUTH_CALLBACK_PORT_BUSY"
