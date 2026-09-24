"""Proxy HTTP/WebSocket Atelier → code-server (réseau cluster, auth backend)."""

from __future__ import annotations

from collections.abc import Mapping
import logging
import posixpath
from typing import Any, Callable
from urllib.parse import unquote

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket
from starlette.responses import Response, StreamingResponse

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.relais_ws import refus_websocket, relayer
from mcp_gateway.atelier.vscode_bridge import (
    COOKIE_NAME,
    load_vscode_password,
    save_vscode_password,
)

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

# Les identifiants de notre propre porte, qui n'ont rien à faire en amont.
#
# Le navigateur joint à chaque appel de `/vscode` ce qu'il joint partout : la
# clé propriétaire en `Authorization`, et le cookie de session de l'Atelier.
# Ils partaient tels quels vers code-server, qui n'en a aucun usage — il
# tourne sous sa propre authentification, et le proxy s'y connecte avec sa
# session à lui, pas avec celle du client. Remettre la clé de sa porte à un
# logiciel qui ne l'a pas demandée n'est jamais utile.
#
# Rien ne casse en les retirant : les réponses amont sont déjà dépouillées de
# leur `set-cookie`, donc le navigateur ne détient aucun cookie de code-server
# à lui renvoyer.
NE_PAS_TRANSMETTRE = HOP_BY_HOP | {"authorization", "cookie"}


def entetes_amont(entetes: Mapping[str, str]) -> dict[str, str]:
    """Les en-têtes du client, dépouillés de ce qui ne doit pas remonter."""
    return {k: v for k, v in entetes.items() if k.lower() not in NE_PAS_TRANSMETTRE}


# Les routes par lesquelles code-server relaie n'importe quel port local du
# pod (`/proxy/<port>/`, `/absproxy/<port>/`). Passées par `/vscode`, elles
# donnaient, derrière la porte de l'Atelier, un accès à tout service en
# boucle locale — wikichat, le MCP du navigateur, un serveur d'agent. Ce
# n'était voulu par personne. code-server est en plus lancé avec
# `disable-proxy` (install/atelier-init.sh) ; ceci vaut pour une instance
# qui ne l'aurait pas.
_PREFIXES_INTERDITS = frozenset({"proxy", "absproxy"})


def chemin_de_proxy_interdit(chemin: str) -> bool:
    """Vrai si `chemin` (relatif à /vscode) mène aux routes proxy de code-server.

    Normalisé comme le ferait un serveur tolérant : décodage répété (`%2F`,
    `%252F`), barres inverses, barres doublées, segments `.` et `..`, casse.
    """
    brut = chemin or ""
    for _ in range(3):
        decode = unquote(brut)
        if decode == brut:
            break
        brut = decode
    brut = brut.replace("\\", "/")
    normal = posixpath.normpath("/" + brut).lstrip("/")
    premier = normal.split("/", 1)[0].strip().lower()
    return premier in _PREFIXES_INTERDITS


def _chemin_brut_apres_prefixe(scope: Mapping[str, Any], prefixe: str) -> str:
    """Le chemin tel que reçu, avant le décodage de Starlette."""
    brut = scope.get("raw_path") or b""
    texte = brut.decode("latin-1") if isinstance(brut, bytes) else str(brut)
    texte = texte.split("?", 1)[0]
    if texte.lower().startswith(prefixe):
        texte = texte[len(prefixe):]
    return texte


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
        """Repart sur un client neuf, appelable depuis n'importe où.

        La fermeture était confiée à `asyncio.create_task`, qui exige une
        boucle en cours. Appelée depuis une route synchrone — FastAPI les
        exécute dans un fil séparé — elle levait « no running event loop » et
        rendait 500. L'enregistrement du mot de passe échouait donc en silence,
        le script appelant terminant par `|| true`.

        On lâche le client sans l'attendre : httpx ferme ses connexions à la
        collecte, et la route qui appelle n'a pas à savoir si une boucle
        tourne.
        """
        self.password = password
        self._ready = False
        self._auth_none = False
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
        headers = entetes_amont(request.headers)
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
        if chemin_de_proxy_interdit(path) or chemin_de_proxy_interdit(
            _chemin_brut_apres_prefixe(request.scope, prefix)
        ):
            raise HTTPException(404)
        upstream: VscodeUpstream = app.state.vscode_upstream
        return await upstream.proxy_http(request, path)

    @app.websocket(f"{prefix}")
    @app.websocket(f"{prefix}/{{path:path}}")
    async def vscode_ws_proxy(websocket: WebSocket, path: str = "") -> None:
        if chemin_de_proxy_interdit(path) or chemin_de_proxy_interdit(
            _chemin_brut_apres_prefixe(websocket.scope, prefix)
        ):
            await websocket.close(code=4404)
            return
        # La clé au porteur, ou la session que le cookie désigne — et, pour
        # un cookie, une Origin qui est bien la nôtre (voir relais_ws).
        # Pas de clé dans l'adresse : une URL de WebSocket se journalise.
        refus = refus_websocket(websocket)
        if refus is not None:
            await websocket.close(code=refus)
            return

        upstream: VscodeUpstream = app.state.vscode_upstream
        if not await upstream.login():
            await websocket.close(code=1013)
            return

        ws_base = upstream.base.replace("https://", "wss://").replace("http://", "ws://")
        ws_path = f"/{path}" if path else "/"
        ws_url = f"{ws_base}{ws_path}"
        # code-server a besoin de sa requête (jeton de reconnexion, etc.).
        if websocket.query_params:
            ws_url = f"{ws_url}?{websocket.query_params}"
        extra: list[tuple[str, str]] = []
        cookie = upstream.cookie_header()
        if cookie:
            extra.append(("Cookie", cookie))
        await relayer(websocket, ws_url, entetes=extra, journal="vscode ws")
