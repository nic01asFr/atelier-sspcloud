"""Bureau du navigateur derrière la porte de l'Atelier — comme `/vscode`.

Le bureau (page noVNC, fichiers noVNC, WebSocket VNC) est servi par le
service navigateur lui-même, derrière son jeton (`docs/ATELIER-SPEC.md` du
fork, lot L4). L'Atelier n'en est que le mandataire : il vérifie sa propre
session (et l'`Origin` pour le WebSocket), puis relaie en posant le jeton du
service, que le navigateur de la personne ne voit jamais.

Choix : noVNC servi par le service plutôt que recopié ici. Il est déjà dans
son image, à la version qui va avec son websockify ; l'Atelier n'a ainsi ni
code tiers à tenir, ni mot de passe VNC à connaître — le service le tire au
sort à chaque démarrage et ne le remet qu'à sa page `/view`, servie avec le
jeton.

| Atelier                 | service         |
|-------------------------|-----------------|
| GET /chrome/view        | GET /view       |
| GET /chrome/novnc/…     | GET /novnc/…    |
| WS  /chrome/vnc         | WS  /vnc        |
| GET /chrome/health      | GET /health     |
"""

from __future__ import annotations

import logging
import posixpath
from typing import Any, Callable
from urllib.parse import unquote

import httpx
from fastapi import Depends, FastAPI, HTTPException, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.responses import Response

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.navigateur import (
    chrome_http_origin,
    entetes_service,
    navigateur_configure,
)
from mcp_gateway.atelier.relais_ws import refus_websocket, relayer

log = logging.getLogger("atelier.chrome_proxy")

_DELAI = httpx.Timeout(5.0)

PAGE_INDISPONIBLE = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bureau Chrome — indisponible</title>
  <style>
    html, body { margin: 0; height: 100%; background: #1a1a2e; color: #e8e8f0; font-family: system-ui, sans-serif; }
    main { display: flex; align-items: center; justify-content: center; height: 100%; padding: 2rem; text-align: center; }
  </style>
</head>
<body><main><p>Le bureau du navigateur n'est pas disponible : {raison}</p></main></body>
</html>
"""

# Les en-têtes de réponse du service qu'on laisse passer vers le navigateur.
_ENTETES_RENDUS = {"content-type", "cache-control", "etag", "last-modified"}


async def etat_du_navigateur(settings: AtelierSettings) -> dict[str, Any]:
    """Ce que l'Atelier sait du navigateur, sans jamais lever.

    `bureau` n'est vrai que si le service le dit lui-même : c'est ce qui
    décide si l'interface montre le lien « Bureau ».
    """
    if not navigateur_configure(settings):
        return {
            "configure": False,
            "joignable": False,
            "bureau": False,
            "raison": "navigateur non configuré (URL ou jeton absents)",
        }
    origine = chrome_http_origin(settings)
    try:
        async with httpx.AsyncClient(timeout=_DELAI) as client:
            r = await client.get(f"{origine}/health", headers=entetes_service(settings))
    except httpx.HTTPError as exc:
        return {
            "configure": True,
            "joignable": False,
            "bureau": False,
            "raison": f"service injoignable ({type(exc).__name__})",
        }
    try:
        corps = r.json()
    except ValueError:
        corps = None
    if r.status_code != 200 or not isinstance(corps, dict):
        return {
            "configure": True,
            "joignable": False,
            "bureau": False,
            "raison": f"réponse inattendue du service (HTTP {r.status_code})",
        }
    # Un service sans jeton valide, ou d'avant le contrat, ne rend que
    # {"status": "ok"} : joignable, mais on ne sait rien de son bureau.
    etat: dict[str, Any] = {
        "configure": True,
        "joignable": corps.get("status") == "ok",
        "bureau": corps.get("bureau") is True,
    }
    for cle in ("conversations", "maxConversations"):
        if isinstance(corps.get(cle), int):
            etat[cle] = corps[cle]
    if not etat["bureau"]:
        etat["raison"] = "le service n'annonce pas de bureau disponible"
    return etat


def _chemin_novnc_sur(chemin: str) -> str | None:
    """Le chemin relatif demandé sous /novnc, s'il reste dedans."""
    brut = unquote(chemin or "").replace("\\", "/")
    normal = posixpath.normpath("/" + brut)
    if normal in {"/", "."} or ".." in normal.split("/"):
        return None
    return normal.lstrip("/")


def register_chrome_proxy(
    app: FastAPI,
    settings: AtelierSettings,
    auth_dep: Callable[..., Any],
) -> None:
    """Monte `/chrome/health`, `/chrome/view`, `/chrome/novnc/…` et `/chrome/vnc`."""

    async def _relayer_get(chemin: str) -> Response:
        if not navigateur_configure(settings):
            raise HTTPException(503, "navigateur non configuré")
        url = f"{chrome_http_origin(settings)}/{chemin}"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
                r = await client.get(url, headers=entetes_service(settings))
        except httpx.HTTPError as exc:
            raise HTTPException(503, f"navigateur injoignable ({type(exc).__name__})") from exc
        entetes = {k: v for k, v in r.headers.items() if k.lower() in _ENTETES_RENDUS}
        return Response(content=r.content, status_code=r.status_code, headers=entetes)

    @app.get("/chrome/health")
    async def chrome_health(_owner: str = Depends(auth_dep)) -> JSONResponse:
        return JSONResponse(await etat_du_navigateur(settings))

    @app.get("/chrome/view")
    async def chrome_view(_owner: str = Depends(auth_dep)) -> Response:
        etat = await etat_du_navigateur(settings)
        if not etat["bureau"]:
            return HTMLResponse(
                PAGE_INDISPONIBLE.replace("{raison}", str(etat.get("raison") or "inconnu")),
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        reponse = await _relayer_get("view")
        reponse.headers["Cache-Control"] = "no-store"
        return reponse

    @app.get("/chrome/novnc/{chemin:path}")
    async def chrome_novnc(chemin: str, _owner: str = Depends(auth_dep)) -> Response:
        sur = _chemin_novnc_sur(chemin)
        if sur is None:
            raise HTTPException(404)
        return await _relayer_get(f"novnc/{sur}")

    @app.websocket("/chrome/vnc")
    async def chrome_vnc(websocket: WebSocket) -> None:
        refus = refus_websocket(websocket)
        if refus is not None:
            await websocket.close(code=refus)
            return
        if not navigateur_configure(settings):
            await websocket.close(code=1013)
            return
        origine = chrome_http_origin(settings)
        ws_url = origine.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/vnc"
        # Rien de la requête du client ne remonte : ni sa query string, ni
        # ses cookies. Seul le jeton du service, posé ici.
        entetes = list(entetes_service(settings).items())
        await relayer(websocket, ws_url, entetes=entetes, journal="chrome vnc")
