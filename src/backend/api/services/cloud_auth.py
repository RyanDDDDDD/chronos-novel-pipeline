"""Client for chronos-cloud-services' AuthService (/v1/auth/*) plus local secure token
storage (OS keyring). See chronos-cloud-services' CONTRACT.md for the wire contract this
mirrors -- this module is the only place in chronos that knows Cognito/PKCE/that contract
exist; callers (routes.py, domain/search_provider.py) only see this module's plain functions."""
from __future__ import annotations

import asyncio
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import httpx
import keyring
import keyring.errors

_KEYRING_SERVICE = "chronos-cloud-auth"
_ACCESS_TOKEN_KEY = "access_token"
_REFRESH_TOKEN_KEY = "refresh_token"
_ID_TOKEN_KEY = "id_token"

_CALLBACK_PORT = 53214
_CALLBACK_PATH = "/callback"
_CALLBACK_TIMEOUT_S = 300.0

# Deduplicate concurrent refreshes from hedged searches and web_search calls to avoid Cognito throttling.
_refresh_lock = asyncio.Lock()


class CloudAuthError(Exception):
    """Carries the cloud AuthService's error_code/message (or a local NOT_CONFIGURED/
    NETWORK_ERROR/OAUTH_* code for failures that never reach the server) -- callers map
    error_code to a Chinese user-facing message themselves (see CONTRACT.md's language-
    ownership split)."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _base_url(cfg: dict) -> str:
    api_cfg = cfg.get("api") or {}
    base_url = api_cfg.get("cloud_auth_base_url", "")
    if not base_url:
        raise CloudAuthError("NOT_CONFIGURED", "未配置云端登录服务地址，请在服务配置页填入 cloud_auth_base_url。")
    return cast(str, base_url).rstrip("/")


def get_access_token() -> str | None:
    return keyring.get_password(_KEYRING_SERVICE, _ACCESS_TOKEN_KEY)


def get_refresh_token() -> str | None:
    return keyring.get_password(_KEYRING_SERVICE, _REFRESH_TOKEN_KEY)


def is_logged_in() -> bool:
    return get_access_token() is not None


def _store_tokens(access_token: str, refresh_token: str | None, id_token: str) -> None:
    keyring.set_password(_KEYRING_SERVICE, _ACCESS_TOKEN_KEY, access_token)
    keyring.set_password(_KEYRING_SERVICE, _ID_TOKEN_KEY, id_token)
    if refresh_token is not None:
        keyring.set_password(_KEYRING_SERVICE, _REFRESH_TOKEN_KEY, refresh_token)


def clear_tokens() -> None:
    for key in (_ACCESS_TOKEN_KEY, _REFRESH_TOKEN_KEY, _ID_TOKEN_KEY):
        try:
            keyring.delete_password(_KEYRING_SERVICE, key)
        except keyring.errors.PasswordDeleteError:
            pass  # already absent -- clearing is idempotent


async def _post(cfg: dict, path: str, json: dict) -> dict:
    """POST to the cloud AuthService, translating its {error_code, message} envelope into
    CloudAuthError. No retry/hedging -- CONTRACT.md specifies /v1/auth/* is single-shot."""
    url = f"{_base_url(cfg)}{path}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=json)
    except httpx.TransportError as e:
        raise CloudAuthError("NETWORK_ERROR", f"无法连接云端登录服务：{e}") from e

    if resp.status_code >= 400:
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        raise CloudAuthError(body.get("error_code", "UNKNOWN_ERROR"), body.get("message", resp.text))
    return cast(dict[str, Any], resp.json())


async def register(cfg: dict, email: str, password: str) -> dict:
    return await _post(cfg, "/v1/auth/register", {"email": email, "password": password})


async def confirm(cfg: dict, email: str, confirmation_code: str) -> dict:
    return await _post(cfg, "/v1/auth/confirm", {"email": email, "confirmation_code": confirmation_code})


async def login(cfg: dict, email: str, password: str) -> None:
    body = await _post(cfg, "/v1/auth/login", {"email": email, "password": password})
    _store_tokens(body["access_token"], body.get("refresh_token"), body["id_token"])


async def refresh(cfg: dict) -> None:
    token_before = get_access_token()
    async with _refresh_lock:
        # Another coroutine may have refreshed while we waited for the lock.
        if get_access_token() != token_before:
            return
        refresh_token = get_refresh_token()
        if refresh_token is None:
            raise CloudAuthError("REFRESH_TOKEN_INVALID", "本地没有 refresh token，需要重新登录。")
        try:
            body = await _post(cfg, "/v1/auth/refresh", {"refresh_token": refresh_token})
        except CloudAuthError as e:
            # Keep valid local tokens during transient outages; only a definitively dead
            # refresh token should log the user out.
            if e.error_code == "REFRESH_TOKEN_INVALID":
                clear_tokens()
            raise
        _store_tokens(body["access_token"], None, body["id_token"])


async def logout(cfg: dict) -> None:
    refresh_token = get_refresh_token()
    if refresh_token is not None:
        try:
            await _post(cfg, "/v1/auth/logout", {"refresh_token": refresh_token})
        except CloudAuthError:
            pass  # best-effort server-side revoke; local tokens are cleared regardless
    clear_tokens()


class _CallbackServer:
    """Listens on the fixed OAuth redirect port (CONTRACT.md: Cognito's registered Callback
    URL is a single fixed http://localhost:53214/callback, no dynamic port choice) for exactly
    one request, then stops."""

    def __init__(self) -> None:
        self._result: dict[str, str] | None = None
        self._done = threading.Event()
        self._httpd = HTTPServer(("localhost", _CALLBACK_PORT), self._make_handler())

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib method name
                parsed = urlparse(self.path)
                if parsed.path != _CALLBACK_PATH:
                    self.send_response(404)
                    self.end_headers()
                    return
                outer._result = {k: v[0] for k, v in parse_qs(parsed.query).items()}
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write("<html><body>登录完成，可以关闭此页面。</body></html>".encode())
                outer._done.set()

            def log_message(self, format_str: str, *args: object) -> None:  # noqa: A002 - stdlib signature
                pass  # silence default stderr request logging for this one-shot local server

        return Handler

    async def wait_for_callback(self, timeout: float) -> dict[str, str]:
        loop = asyncio.get_running_loop()
        threading.Thread(target=self._httpd.handle_request, daemon=True).start()
        completed = await loop.run_in_executor(None, self._done.wait, timeout)
        self._httpd.server_close()
        if not completed or self._result is None:
            raise TimeoutError("等待浏览器登录回调超时，请重试。")
        return self._result


async def start_google_login(cfg: dict) -> None:
    """Opens the system browser for Google login and waits (in the caller's background task --
    see routes.py's /api/auth/oauth/start, which does not await this synchronously) for the
    Cognito redirect. AuthService generates code_verifier/state server-side and returns them
    (see chronos-cloud-services CONTRACT.md) -- chronos does NOT generate its own PKCE pair,
    it just relays AuthService's back to it at the callback step. The state comparison below
    IS the CSRF check (CONTRACT.md: AuthService is stateless and never validates state itself)."""
    start_body = await _post(cfg, "/v1/auth/oauth/start", {"provider": "google"})
    try:
        authorize_url = start_body["authorize_url"]
        server_verifier = start_body["code_verifier"]
        server_state = start_body["state"]
    except (KeyError, TypeError) as e:
        raise CloudAuthError("OAUTH_START_MALFORMED", "云端返回的登录参数不完整，请重试。") from e

    try:
        webbrowser.open(authorize_url)
    except Exception as e:  # noqa: BLE001 - webbrowser's exception type is platform-dependent
        raise CloudAuthError("OAUTH_BROWSER_FAILED", "无法打开系统浏览器，请检查默认浏览器设置。") from e
    try:
        server = _CallbackServer()
    except OSError as e:
        raise CloudAuthError(
            "OAUTH_CALLBACK_PORT_BUSY",
            f"本地回调端口 {_CALLBACK_PORT} 被占用，请关闭占用该端口的程序后重试。",
        ) from e
    try:
        params = await server.wait_for_callback(timeout=_CALLBACK_TIMEOUT_S)
    except TimeoutError as e:
        raise CloudAuthError("OAUTH_TIMEOUT", "等待浏览器登录回调超时，请重试。") from e

    if params.get("state") != server_state:
        raise CloudAuthError("OAUTH_STATE_MISMATCH", "登录回调的 state 不匹配，可能是过期或被篡改的请求，请重新登录。")
    code = params.get("code")
    if code is None:
        raise CloudAuthError("OAUTH_CODE_INVALID", f"登录回调缺少授权码：{params.get('error', '未知错误')}")

    body = await _post(cfg, "/v1/auth/oauth/callback", {
        "provider": "google",
        "code": code,
        "code_verifier": server_verifier,
        "redirect_uri": f"http://localhost:{_CALLBACK_PORT}{_CALLBACK_PATH}",
    })
    _store_tokens(body["access_token"], body.get("refresh_token"), body["id_token"])
