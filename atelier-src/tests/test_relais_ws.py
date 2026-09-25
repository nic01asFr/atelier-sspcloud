"""`relais_ws.relayer` : les options de l'hôte des applications, sur le relais commun.

`/vscode` et l'hôte des applications passent par le même
relais. Ce que `/vscode` en attend (ordre, sous-protocoles,
fermetures) est couvert par test_garde_ws_vscode ;
ici, chaque option ajoutée pour les applications, et le défaut qui laisse
les deux autres comme avant.

Les amonts sont de vrais serveurs `websockets` (faux_service_ws).
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterator

import pytest
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

from mcp_gateway.atelier.relais_ws import relayer

from faux_service_ws import FauxService  # noqa: E402 — dossier des tests, sur sys.path


def _app(url: str, **options: Any) -> Starlette:
    """Une route `/ws` qui relaie vers `url` avec `options`, sans garde."""

    async def point(websocket: WebSocket) -> None:
        await relayer(websocket, url, journal="test", **options)

    return Starlette(routes=[WebSocketRoute("/ws", point)])


@pytest.fixture()
def amont() -> Iterator[FauxService]:
    with FauxService(sous_protocoles=()) as s:
        yield s


# --- plafond ------------------------------------------------------------------


class AmontBavard(FauxService):
    """Sur « gros », envoie 2 Mio : son propre plafond ne borne que ce qu'il reçoit."""

    async def _ws(self, ws: Any) -> None:
        self.vu.connexions.append(ws)
        try:
            async for message in ws:
                await ws.send(b"x" * (2 * 2**20) if message == "gros" else message)
        except Exception:  # noqa: BLE001
            pass
        finally:
            self.vu.fermetures.append(ws.close_code)
            self.vu.ferme.set()


def test_sans_plafond_un_gros_message_passe() -> None:
    """Le défaut de /vscode et /chrome : pas de plafond (celui de websockets est 1 Mio)."""
    with AmontBavard(sous_protocoles=()) as bavard:
        with TestClient(_app(f"ws://127.0.0.1:{bavard.port}/")) as c:
            with c.websocket_connect("/ws") as ws:
                ws.send_text("gros")
                assert len(ws.receive_bytes()) == 2 * 2**20


def test_plafond_depasse_coupe_en_1009(amont: FauxService) -> None:
    with TestClient(_app(f"ws://127.0.0.1:{amont.port}/", taille_max=1024)) as c:
        with c.websocket_connect("/ws") as ws:
            ws.send_bytes(b"x" * 512)
            assert ws.receive_bytes() == b"x" * 512
            ws.send_bytes(b"x" * 2048)  # renvoyé par l'amont : trop gros pour nous
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_bytes()
    assert exc.value.code == 1009
    assert amont.vu.ferme.wait(2.0)
    assert amont.vu.fermetures[-1] == 1009


# --- ping ---------------------------------------------------------------------


class AmontMuet(FauxService):
    """Accepte la WebSocket, puis ne lit plus rien pendant une seconde.

    Aucun pong ne revient entre-temps. Il se remet à lire ensuite, pour que la
    fermeture que le relais a envoyée trouve un écho sans attendre les 10 s
    de `close_timeout`.
    """

    async def _ws(self, ws: Any) -> None:
        self.vu.connexions.append(ws)
        ws.transport.pause_reading()
        await asyncio.sleep(1.0)
        ws.transport.resume_reading()
        with contextlib.suppress(Exception):
            async for message in ws:
                await ws.send(message)


def test_ping_sans_reponse_coupe_en_1011() -> None:
    with AmontMuet(sous_protocoles=()) as muet:
        with TestClient(_app(f"ws://127.0.0.1:{muet.port}/", ping_s=0.2)) as c:
            with c.websocket_connect("/ws") as ws:
                debut = time.monotonic()
                with pytest.raises(WebSocketDisconnect) as exc:
                    ws.receive_text()
                duree = time.monotonic() - debut
    assert exc.value.code == 1011
    assert duree < 5.0, "le ping de 0,2 s doit couper bien avant le défaut de 20 s"


def test_ping_desactive_laisse_passer() -> None:
    """`ping_s=None` : pas de ping, l'amont muet n'est pas coupé pour autant."""
    with AmontMuet(sous_protocoles=()) as muet:
        with TestClient(_app(f"ws://127.0.0.1:{muet.port}/", ping_s=None)) as c:
            with c.websocket_connect("/ws") as ws:
                # Au-delà de la seconde muette : un ping de 0,2 s l'aurait coupé.
                time.sleep(1.2)
                ws.send_text("toujours là")
                assert ws.receive_text() == "toujours là"


# --- socket Unix --------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="pas de socket Unix pour asyncio sous Windows")
def test_amont_par_socket_unix(tmp_path: Path) -> None:
    from websockets.asyncio.server import unix_serve

    chemin = tmp_path / "amont.sock"
    vus: list[str] = []
    pret = threading.Event()
    arret: dict[str, Any] = {}

    async def echo(ws: Any) -> None:
        vus.append(ws.request.path)
        async for message in ws:
            await ws.send(message)

    async def principal() -> None:
        arret["boucle"] = asyncio.get_running_loop()
        arret["evenement"] = asyncio.Event()
        async with unix_serve(echo, str(chemin)):
            pret.set()
            await arret["evenement"].wait()

    fil = threading.Thread(target=lambda: asyncio.run(principal()), daemon=True)
    fil.start()
    assert pret.wait(5)
    try:
        app = _app("ws://localhost/chemin?q=1", unix_socket=str(chemin))
        with TestClient(app) as c:
            with c.websocket_connect("/ws") as ws:
                ws.send_text("bonjour")
                assert ws.receive_text() == "bonjour"
        assert vus == ["/chemin?q=1"]
    finally:
        arret["boucle"].call_soon_threadsafe(arret["evenement"].set)
        fil.join(5)


# --- compteur de connexions ---------------------------------------------------


def test_connexion_tenue_pendant_le_relais(amont: FauxService) -> None:
    etat = {"ouvertes": 0, "vues": []}

    @contextlib.contextmanager
    def compteur() -> Iterator[None]:
        etat["ouvertes"] += 1
        try:
            yield
        finally:
            etat["ouvertes"] -= 1

    async def point(websocket: WebSocket) -> None:
        await relayer(websocket, f"ws://127.0.0.1:{amont.port}/", connexion=compteur())

    app = Starlette(routes=[WebSocketRoute("/ws", point)])
    with TestClient(app) as c:
        with c.websocket_connect("/ws") as ws:
            ws.send_text("x")
            assert ws.receive_text() == "x"
            etat["vues"].append(etat["ouvertes"])
        assert amont.vu.ferme.wait(2.0)
    assert etat["vues"] == [1]
    assert etat["ouvertes"] == 0


def test_connexion_rendue_si_amont_injoignable() -> None:
    etat = {"ouvertes": 0, "entrees": 0}

    @contextlib.contextmanager
    def compteur() -> Iterator[None]:
        etat["ouvertes"] += 1
        etat["entrees"] += 1
        try:
            yield
        finally:
            etat["ouvertes"] -= 1

    async def point(websocket: WebSocket) -> None:
        await relayer(websocket, "ws://127.0.0.1:1/", connexion=compteur())

    with TestClient(Starlette(routes=[WebSocketRoute("/ws", point)])) as c:
        with pytest.raises(WebSocketDisconnect) as exc:
            with c.websocket_connect("/ws"):
                pass
    assert exc.value.code == 1011
    assert etat == {"ouvertes": 0, "entrees": 1}
