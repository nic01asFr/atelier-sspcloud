"""Proxy HTTP/WebSocket Atelier → code-server (réseau cluster, auth backend)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

import httpx
import websockets
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from starlette.responses import Response, StreamingResponse

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.vscode_bridge import load_vscode_password, save_vscode_password

log = logging.getLogger("atelier.vscode_proxy")

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


def is_internal_request(request: Request) -> bool:
    """Requêtes depuis le cluster (pods, loopback)."""
    if not request.client:
        return False
    host = request.client.host
    if host in {"127.0.0.1", "::1"}:
        return True
    if host.startswith("10.") or host.startswith("192.168.") or host.startswith("172."):
        return True
    return False


def resolve_vscode_password(settings: AtelierSettings) -> str | None:
    """PVC → env ATELIER_VSCODE_PASSWORD."""
    pw = load_vscode_password(settings)
    if pw:
        return pw
    env = (settings.vscode_password or "").strip()
    if env:
        save_vscode_password(settings, env)
        return env
    return None


class VscodeUpstream:
    """Client HTTP vers code-server — auth Atelier au proxy, upstream sans login si possible."""

    def __init__(
        self,
        internal_url: str,
        password: str = "",
        *,
        auth_mode: str = "atelier",
    ) -> None:
        self.base = internal_url.rstrip("/")
        self.password = password
        self.auth_mode = auth_mode  # atelier | password
        self._client: httpx.AsyncClient | None = None
        self._ready = False
        self._auth_none = False

    def _client_or_new(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(120.0))
        return self._client

    def reset(self, password: str = "") -> None:
        self.password = password
        self._ready = False
        self._auth_none = False
        if self._client is not None:
            asyncio.create_task(self._client.aclose())
            self._client = None

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _probe_auth_none(self) -> bool:
        client = self._client_or_new()
        try:
            resp = await client.get(f"{self.base}/", follow_redirects=False)
        except httpx.HTTPError as exc:
            log.warning("vscode upstream probe error: %s", exc)
            return False
        loc = (resp.headers.get("location") or "").lower()
        if resp.status_code == 200 and "login" not in loc:
            self._auth_none = True
            self._ready = True
            return True
        if resp.status_code in {301, 302, 303, 307, 308} and "login" not in loc:
            self._auth_none = True
            self._ready = True
            return True
        return False

    async def _login_with_password(self) -> bool:
        if not self.password:
            return False
        client = self._client_or_new()
        try:
            resp = await client.post(
                f"{self.base}/login",
                data={"password": self.password, "base": ".", "href": ""},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            log.warning("vscode upstream login error: %s", exc)
            return False
        if client.cookies:
            self._ready = True
            return True
        log.warning("vscode upstream login failed status=%s", resp.status_code)
        return False

    async def ensure_ready(self) -> bool:
        if self._ready:
            return True
        if self.auth_mode == "atelier" and await self._probe_auth_none():
            return True
        if self.password and await self._login_with_password():
            return True
        if self.auth_mode != "atelier" and await self._probe_auth_none():
            return True
        return False

    async def login(self) -> bool:
        return await self.ensure_ready()

    def cookie_header(self) -> str:
        if self._auth_none:
            return ""
        client = self._client_or_new()
        return "; ".join(f"{k}={v}" for k, v in client.cookies.items())

    async def proxy_http(self, request: Request, path: str) -> Response:
        if not await self.ensure_ready():
            raise HTTPException(
                503,
                "code-server requiert encore un login — configurer auth: none sur le pod VS Code "
                "(accès uniquement via Atelier)",
            )
        upstream_path = path or ""
        url = f"{self.base}/{upstream_path}" if upstream_path else f"{self.base}/"
        if request.url.query:
            url = f"{url}?{request.url.query}"
        headers = {
            k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP
        }
        body = await request.body()
        cookies = None if self._auth_none else self._client_or_new().cookies
        # Le client ne peut pas être refermé avant que la réponse ait été
        # lue : elle est diffusée en flux, et fermer le client coupe la
        # connexion au milieu. Les gros fichiers de VS Code arrivaient donc
        # tronqués — workbench.js s'arrêtait à 34 Ko, en plein code, et la
        # page restait blanche.
        client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(120.0),
            cookies=cookies,
        )
        try:
            req = client.build_request(request.method, url, headers=headers, content=body)
            resp = await client.send(req, stream=True)
        except httpx.HTTPError as exc:
            await client.aclose()
            raise HTTPException(502, f"upstream code-server: {exc}") from exc

        out_headers = {
            k: v
            for k, v in resp.headers.items()
            if k.lower() not in HOP_BY_HOP and k.lower() != "set-cookie"
        }

        async def stream() -> Any:
            # Octets bruts : on retransmet l'en-tête `content-encoding` du
            # serveur, donc le corps doit rester tel qu'il l'a envoyé.
            # `aiter_bytes` décompresse, ce qui donnait au navigateur un
            # contenu clair annoncé comme compressé.
            try:
                async for chunk in resp.aiter_raw():
                    yield chunk
            finally:
                await resp.aclose()
                await client.aclose()

        return StreamingResponse(
            stream(),
            status_code=resp.status_code,
            headers=out_headers,
            media_type=resp.headers.get("content-type"),
        )


async def _relay_websocket(client: WebSocket, remote: Any) -> None:
    async def to_remote() -> None:
        try:
            while True:
                msg = await client.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    await remote.send(msg["bytes"])
                elif msg.get("text") is not None:
                    await remote.send(msg["text"])
        except WebSocketDisconnect:
            pass

    async def to_client() -> None:
        try:
            while True:
                data = await remote.recv()
                if isinstance(data, bytes):
                    await client.send_bytes(data)
                else:
                    await client.send_text(data)
        except websockets.ConnectionClosed:
            pass

    await asyncio.gather(to_remote(), to_client())


def register_vscode_proxy(
    app: FastAPI,
    settings: AtelierSettings,
    auth_dep: Callable[..., Any],
) -> None:
    """Monte /vscode (proxy) — auth Atelier, login code-server côté backend."""
    prefix = "/vscode"

    @app.api_route(
        f"{prefix}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    @app.api_route(
        f"{prefix}/{{path:path}}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def vscode_http_proxy(
        request: Request,
        path: str = "",
        _owner: str = Depends(auth_dep),
    ) -> Response:
        upstream: VscodeUpstream = app.state.vscode_upstream
        return await upstream.proxy_http(request, path)

    @app.websocket(f"{prefix}")
    @app.websocket(f"{prefix}/{{path:path}}")
    async def vscode_ws_proxy(websocket: WebSocket, path: str = "") -> None:
        token = websocket.cookies.get("atelier_owner") or websocket.query_params.get("token")
        auth = app.state.auth
        try:
            auth.check_token(token)
        except HTTPException:
            await websocket.close(code=4401)
            return

        upstream: VscodeUpstream = app.state.vscode_upstream
        if not await upstream.login():
            await websocket.close(code=1013)
            return

        await websocket.accept()
        ws_base = upstream.base.replace("https://", "wss://").replace("http://", "ws://")
        ws_path = f"/{path}" if path else "/"
        ws_url = f"{ws_base}{ws_path}"
        if websocket.query_params:
            ws_url = f"{ws_url}?{websocket.query_params}"
        extra: list[tuple[str, str]] = []
        cookie = upstream.cookie_header()
        if cookie:
            extra.append(("Cookie", cookie))

        try:
            async with websockets.connect(ws_url, additional_headers=extra, max_size=None) as remote:
                await _relay_websocket(websocket, remote)
        except (OSError, websockets.WebSocketException) as exc:
            log.warning("vscode ws proxy: %s", exc)
            await websocket.close(code=1011)
