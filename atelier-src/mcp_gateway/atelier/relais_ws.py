"""Relais WebSocket de l'Atelier vers un service amont, et sa garde.

Partagé par `/vscode` et `/chrome/vnc`, et par tout futur mandataire
d'application. Deux choses s'y décident, une fois pour toutes.

La garde. `sspcloud.fr` n'est pas dans la Public Suffix List : tout pod
`*.user.lab.sspcloud.fr` est donc « même site » que l'Atelier, et le cookie
`SameSite=Lax` part avec les WebSockets qu'une de ses pages ouvre vers nous.
Le cookie ne prouve donc pas que la page est la nôtre ; l'`Origin`, si. Un
WebSocket authentifié par cookie exige une `Origin` exactement égale à
l'adresse publique de l'Atelier. Sans `Origin`, seul un client qui présente
la clé en `Authorization` passe : ce n'est pas un navigateur.

Le relais. L'amont est joint d'abord, avec les sous-protocoles demandés par
le client ; le client n'est accepté qu'ensuite, avec celui que l'amont a
retenu. Quand un sens se termine, l'autre est annulé et les deux côtés sont
fermés, avec le code de fermeture de celui qui a raccroché. Avant, les deux
sens étaient attendus ensemble : un côté fermé laissait l'autre ouvert, et la
connexion amont survivait au client.

Un seul relais pour tous : ce qui distingue les appelants passe en
paramètres, et chaque défaut est le comportement qu'avaient `/vscode` et
`/chrome/vnc` avant la fusion. L'hôte des applications (`apps/serveur.py`)
y ajoute un plafond par message, un ping réglé, un amont en socket Unix et
le compteur de connexions de son superviseur.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Sequence
from typing import Any

import websockets
from fastapi import HTTPException, WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState
from websockets.asyncio.client import connect, unix_connect

from mcp_gateway.atelier.auth import bearer_from_header
from mcp_gateway.atelier.vscode_bridge import COOKIE_NAME

log = logging.getLogger("atelier.relais_ws")

# Codes de fermeture propres à l'Atelier, avant toute connexion amont.
FERME_NON_AUTHENTIFIE = 4401
FERME_ORIGINE_REFUSEE = 4403
# Service amont injoignable.
FERME_AMONT_INJOIGNABLE = 1011

# Codes qu'une trame de fermeture n'a pas le droit de porter.
_CODES_RESERVES = {1005, 1006, 1015}

# Ceux de `websockets` : un ping amont toutes les 20 s, 20 s pour sa réponse,
# 10 s pour la poignée de main.
PING_S_DEFAUT = 20.0
OUVERTURE_S = 10.0


def _normaliser_origine(origine: str) -> str:
    return origine.strip().rstrip("/").lower()


def origine_publique(websocket: WebSocket) -> str:
    """L'origine sous laquelle les pages de l'Atelier sont servies.

    Le réglage explicite (`ATELIER_PUBLIC_URL`, rangé dans `app.state.host_url`)
    d'abord ; sinon l'hôte par lequel on a été joint, et le schéma que le
    proxy a vu. Comparer l'`Origin` à l'hôte joint suffit contre une page
    tierce : elle ne choisit pas l'`Origin` que son navigateur envoie.
    """
    configure = (getattr(websocket.app.state, "host_url", "") or "").strip()
    if configure:
        return _normaliser_origine(configure)
    entetes = websocket.headers
    hote = (entetes.get("x-forwarded-host") or entetes.get("host") or "").split(",")[0].strip()
    schema = (entetes.get("x-forwarded-proto") or "").split(",")[0].strip()
    if not schema:
        schema = "https" if websocket.url.scheme == "wss" else "http"
    return _normaliser_origine(f"{schema}://{hote}")


def refus_websocket(websocket: WebSocket) -> int | None:
    """Le code de fermeture à rendre, ou None si le WebSocket peut passer.

    Ne connecte rien : à appeler avant tout contact avec l'amont.
    """
    bearer = bearer_from_header(websocket.headers.get("authorization"))
    origine = websocket.headers.get("origin")
    if origine is None:
        # Pas d'Origin : pas un navigateur, ou un navigateur qu'on ne sait
        # pas situer. Le cookie seul ne suffit pas.
        if not bearer:
            return FERME_ORIGINE_REFUSEE
    elif _normaliser_origine(origine) != origine_publique(websocket):
        return FERME_ORIGINE_REFUSEE
    auth = websocket.app.state.auth
    try:
        auth.check_navigation(bearer, websocket.cookies.get(COOKIE_NAME))
    except HTTPException:
        return FERME_NON_AUTHENTIFIE
    return None


def sous_protocoles_demandes(websocket: WebSocket) -> list[str]:
    brut = websocket.headers.get("sec-websocket-protocol") or ""
    return [p.strip() for p in brut.split(",") if p.strip()]


def _code_recu(exc: websockets.ConnectionClosed) -> int | None:
    """Le code de la fermeture : celui que l'amont a envoyé, sinon le nôtre.

    Quand c'est notre côté qui coupe l'amont — message au-delà du plafond
    (1009), ping resté sans réponse (1011) — il n'y a rien de reçu, et le
    client doit apprendre pourquoi plutôt qu'un 1000 muet.
    """
    if exc.rcvd is not None:
        return exc.rcvd.code
    return exc.sent.code if exc.sent is not None else None


def _raison_recue(exc: websockets.ConnectionClosed) -> str:
    if exc.rcvd is not None:
        return exc.rcvd.reason
    return exc.sent.reason if exc.sent is not None else ""


def _code_transmissible(code: int | None) -> int:
    if code is None or code in _CODES_RESERVES:
        return 1000
    if code < 1000 or code >= 5000:
        return 1011
    return code


async def relayer(
    client: WebSocket,
    url_amont: str,
    *,
    entetes: Sequence[tuple[str, str]] = (),
    journal: str = "ws",
    taille_max: int | None = None,
    ping_s: float | None = PING_S_DEFAUT,
    unix_socket: str | None = None,
    connexion: contextlib.AbstractContextManager[Any] | None = None,
) -> None:
    """Joint l'amont, accepte le client, relaie jusqu'à ce qu'un côté raccroche.

    Le client ne doit pas encore être accepté. Si l'amont est injoignable,
    le client est refusé (1011) sans avoir été accepté.

    - `taille_max` : plafond d'un message venu de l'amont, en octets ; au-delà,
      l'amont est coupé en 1009 et le client l'apprend. None : pas de plafond.
      (Dans l'autre sens, c'est le serveur ASGI qui borne.)
    - `ping_s` : intervalle des pings amont, et délai de leur réponse ; un
      amont muet au-delà est coupé en 1011. None : pas de ping.
    - `unix_socket` : joindre l'amont par ce socket Unix ; `url_amont` ne
      fournit alors que le chemin, la requête et l'en-tête `Host`.
    - `connexion` : tenu ouvert de la première tentative vers l'amont à la
      fermeture des deux côtés — le compteur de connexions d'un superviseur,
      qui n'arrête pas un service tant qu'un client lui parle.
    """
    with connexion if connexion is not None else contextlib.nullcontext():
        await _relayer(
            client,
            url_amont,
            entetes=entetes,
            journal=journal,
            taille_max=taille_max,
            ping_s=ping_s,
            unix_socket=unix_socket,
        )


async def _relayer(
    client: WebSocket,
    url_amont: str,
    *,
    entetes: Sequence[tuple[str, str]],
    journal: str,
    taille_max: int | None,
    ping_s: float | None,
    unix_socket: str | None,
) -> None:
    demandes = sous_protocoles_demandes(client)
    options: dict[str, Any] = dict(
        additional_headers=list(entetes),
        subprotocols=[websockets.Subprotocol(p) for p in demandes] or None,
        max_size=taille_max,
        ping_interval=ping_s,
        ping_timeout=ping_s,
        compression=None,
        open_timeout=OUVERTURE_S,
    )
    try:
        if unix_socket:
            amont = await unix_connect(unix_socket, url_amont, **options)
        else:
            amont = await connect(url_amont, **options)
    except (OSError, websockets.WebSocketException, asyncio.TimeoutError) as exc:
        log.warning("%s : amont injoignable (%s)", journal, exc)
        await client.close(code=FERME_AMONT_INJOIGNABLE)
        return

    try:
        await client.accept(subprotocol=amont.subprotocol)
    except Exception:  # noqa: BLE001 — client parti entre-temps
        await amont.close()
        return

    # Qui a raccroché, et avec quel code : c'est ce qu'on rend à l'autre.
    fin: dict[str, Any] = {}

    async def vers_amont() -> None:
        try:
            while True:
                msg = await client.receive()
                if msg["type"] == "websocket.disconnect":
                    fin.setdefault("cote", "client")
                    fin.setdefault("code", msg.get("code"))
                    fin.setdefault("raison", msg.get("reason") or "")
                    return
                if msg.get("bytes") is not None:
                    await amont.send(msg["bytes"])
                elif msg.get("text") is not None:
                    await amont.send(msg["text"])
        except WebSocketDisconnect as exc:
            fin.setdefault("cote", "client")
            fin.setdefault("code", exc.code)
        except websockets.ConnectionClosed as exc:
            fin.setdefault("cote", "amont")
            fin.setdefault("code", _code_recu(exc))
            fin.setdefault("raison", _raison_recue(exc))

    async def vers_client() -> None:
        try:
            async for data in amont:
                if isinstance(data, bytes):
                    await client.send_bytes(data)
                else:
                    await client.send_text(data)
            fin.setdefault("cote", "amont")
            fin.setdefault("code", amont.close_code)
            fin.setdefault("raison", amont.close_reason or "")
        except websockets.ConnectionClosed as exc:
            fin.setdefault("cote", "amont")
            fin.setdefault("code", _code_recu(exc))
            fin.setdefault("raison", _raison_recue(exc))
        except (WebSocketDisconnect, RuntimeError):
            fin.setdefault("cote", "client")

    taches = [
        asyncio.create_task(vers_amont(), name=f"{journal}-vers-amont"),
        asyncio.create_task(vers_client(), name=f"{journal}-vers-client"),
    ]
    try:
        _, restantes = await asyncio.wait(taches, return_when=asyncio.FIRST_COMPLETED)
        for t in restantes:
            t.cancel()
        await asyncio.gather(*restantes, return_exceptions=True)
    finally:
        code = _code_transmissible(fin.get("code"))
        raison = str(fin.get("raison") or "")[:120]
        try:
            await amont.close(code=code, reason=raison)
        except Exception:  # noqa: BLE001 — déjà fermé
            pass
        if client.application_state == WebSocketState.CONNECTED:
            try:
                await client.close(code=code, reason=raison)
            except Exception:  # noqa: BLE001 — déjà fermé
                pass
