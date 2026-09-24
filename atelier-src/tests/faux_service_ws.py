"""Un vrai serveur HTTP + WebSocket, dans un fil à lui, pour les tests de relais.

Il tient le rôle d'un service amont (code-server, le service navigateur) :
répond en HTTP sur les chemins qu'on lui donne, accepte les WebSockets,
renvoie ce qu'il reçoit, et note ce qu'il a vu — en-têtes, chemin, code de
fermeture reçu. Pas de double : un vrai serveur `websockets`, sur un vrai port.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.http11 import Request, Response


@dataclass
class Vu:
    requetes: list[tuple[str, dict[str, str]]] = field(default_factory=list)
    connexions: list[ServerConnection] = field(default_factory=list)
    fermetures: list[int | None] = field(default_factory=list)
    ferme: threading.Event = field(default_factory=threading.Event)


class FauxService:
    """`with FauxService(routes) as s:` — `s.port`, `s.vu`, `s.fermer_cote_amont(code)`."""

    def __init__(
        self,
        routes: dict[str, Callable[[dict[str, str]], tuple[int, str, bytes]]] | None = None,
        *,
        sous_protocoles: tuple[str, ...] = ("binary",),
    ) -> None:
        self.routes = routes or {}
        self.sous_protocoles = sous_protocoles
        self.vu = Vu()
        self.port = 0
        self._boucle: asyncio.AbstractEventLoop | None = None
        self._arret: asyncio.Event | None = None
        self._pret = threading.Event()
        self._fil = threading.Thread(target=self._tourner, daemon=True)

    # --- cycle de vie ---------------------------------------------------

    def __enter__(self) -> "FauxService":
        self._fil.start()
        assert self._pret.wait(5), "faux service non démarré"
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._boucle and self._arret:
            self._boucle.call_soon_threadsafe(self._arret.set)
        self._fil.join(5)

    def _tourner(self) -> None:
        asyncio.run(self._principal())

    async def _principal(self) -> None:
        self._boucle = asyncio.get_running_loop()
        self._arret = asyncio.Event()
        async with serve(
            self._ws,
            "127.0.0.1",
            0,
            process_request=self._http,
            subprotocols=list(self.sous_protocoles) or None,
            compression=None,
        ) as serveur:
            self.port = next(iter(serveur.sockets)).getsockname()[1]
            self._pret.set()
            await self._arret.wait()

    # --- HTTP -----------------------------------------------------------

    def _http(self, connexion: ServerConnection, requete: Request) -> Response | None:
        entetes = {k.lower(): v for k, v in requete.headers.raw_items()}
        self.vu.requetes.append((requete.path, entetes))
        if "upgrade" in entetes.get("connection", "").lower():
            return None
        chemin = requete.path.split("?", 1)[0]
        route = self.routes.get(chemin)
        if route is None:
            return connexion.respond(404, "absent\n")
        statut, type_contenu, corps = route(entetes)
        return Response(
            statut,
            "OK" if statut == 200 else "Erreur",
            Headers([("Content-Type", type_contenu), ("Content-Length", str(len(corps)))]),
            corps,
        )

    # --- WebSocket ------------------------------------------------------

    async def _ws(self, ws: ServerConnection) -> None:
        self.vu.connexions.append(ws)
        try:
            async for message in ws:
                await ws.send(message)
        except Exception:  # noqa: BLE001 — fermeture brutale, notée ci-dessous
            pass
        finally:
            self.vu.fermetures.append(ws.close_code)
            self.vu.ferme.set()

    def fermer_cote_amont(self, code: int, raison: str = "") -> None:
        ws = self.vu.connexions[-1]
        assert self._boucle is not None
        asyncio.run_coroutine_threadsafe(ws.close(code, raison), self._boucle).result(5)
