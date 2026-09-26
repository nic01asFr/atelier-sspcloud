"""Un faux Chrome, côté DevTools : de quoi éprouver l'écran sans navigateur.

Il écoute sur 127.0.0.1, au chemin `/devtools/browser/<id>` comme Chrome, et
tient des pages (`Target.*`). Une page suivie en screencast
(`Page.startScreencast`) envoie une image, puis la suivante seulement après
l'acquittement de la précédente, comme Chrome. Les images disent de quelle
page elles viennent (`JPEG:<cible>:<n>`). Tout ce qu'il reçoit est noté
(`recus`), pour que le test dise ce que Chrome a vu.
"""

from __future__ import annotations

import asyncio
import base64
import json
import threading
import time
from typing import Any

import websockets
from websockets.asyncio.server import serve

CHEMIN = "/devtools/browser/0f1e2d3c-faux-4b5a"
LARGEUR, HAUTEUR = 1280, 720


class FauxChrome:
    def __init__(self, pages: dict[str, str] | None = None, *, delai_image: float = 0.02) -> None:
        self.pages: dict[str, dict[str, str]] = {
            ident: {"url": url, "titre": f"Titre {ident}"} for ident, url in (pages or {"T1": "about:blank"}).items()
        }
        self.delai_image = delai_image
        self.recus: list[dict[str, Any]] = []
        self.connexions = 0
        self.ouvertes = 0
        self.boucle = asyncio.new_event_loop()
        self._pret = threading.Event()
        self._clients: set[Any] = set()
        self._diffusions: dict[str, dict[str, Any]] = {}  # session -> {cible, n, actif}
        self.fil = threading.Thread(target=self._tourner, daemon=True)
        self.fil.start()
        assert self._pret.wait(10), "le faux Chrome n'a pas démarré"

    # -- vie du serveur --

    def _tourner(self) -> None:
        asyncio.set_event_loop(self.boucle)

        async def principal() -> None:
            async with serve(self._client, "127.0.0.1", 0, max_size=None) as serveur:
                self.port = serveur.sockets[0].getsockname()[1]
                self._arret = asyncio.Event()
                self._pret.set()
                await self._arret.wait()

        self.boucle.run_until_complete(principal())

    def fermer(self) -> None:
        self.boucle.call_soon_threadsafe(self._arret.set)
        self.fil.join(10)

    def _depuis_le_fil(self, fonction: Any, *args: Any) -> None:
        asyncio.run_coroutine_threadsafe(fonction(*args), self.boucle).result(10)

    # -- ce que le test peut faire --

    def naviguer(self, cible: str, url: str, titre: str = "") -> None:
        """La page change d'adresse (un lien cliqué, par exemple)."""
        self.pages[cible] = {"url": url, "titre": titre or self.pages[cible]["titre"]}
        self._depuis_le_fil(self._annoncer, "Target.targetInfoChanged", cible)

    def ouvrir(self, cible: str, url: str) -> None:
        self.pages[cible] = {"url": url, "titre": f"Titre {cible}"}
        self._depuis_le_fil(self._annoncer, "Target.targetCreated", cible)

    def methodes(self, nom: str) -> list[dict[str, Any]]:
        return [r for r in list(self.recus) if r.get("method") == nom]

    def attendre(self, condition: Any, delai: float = 10.0) -> None:
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            if condition():
                return
            time.sleep(0.02)
        raise AssertionError("condition jamais remplie ; reçus : " + json.dumps([r.get("method") for r in self.recus][-30:]))

    # -- le protocole --

    def _info(self, cible: str) -> dict[str, Any]:
        page = self.pages[cible]
        return {"targetId": cible, "type": "page", "url": page["url"], "title": page["titre"], "attached": False}

    async def _annoncer(self, methode: str, cible: str) -> None:
        for ws in list(self._clients):
            await ws.send(json.dumps({"method": methode, "params": {"targetInfo": self._info(cible)}}))

    async def _image(self, ws: Any, session: str) -> None:
        diffusion = self._diffusions.get(session)
        if not diffusion or not diffusion["actif"]:
            return
        diffusion["n"] += 1
        donnees = f"JPEG:{diffusion['cible']}:{diffusion['n']}".encode()
        await ws.send(json.dumps({
            "method": "Page.screencastFrame",
            "sessionId": session,
            "params": {
                "data": base64.b64encode(donnees).decode(),
                "sessionId": diffusion["n"],
                "metadata": {"deviceWidth": LARGEUR, "deviceHeight": HAUTEUR, "pageScaleFactor": 1, "offsetTop": 0},
            },
        }))

    async def _client(self, ws: Any) -> None:
        if ws.request.path != CHEMIN:
            await ws.close(4404)
            return
        self.connexions += 1
        self.ouvertes += 1
        self._clients.add(ws)
        try:
            async for brut in ws:
                message = json.loads(brut)
                self.recus.append(message)
                await self._repondre(ws, message)
        except websockets.ConnectionClosed:
            pass
        finally:
            self._clients.discard(ws)
            self.ouvertes -= 1
            for diffusion in self._diffusions.values():
                if diffusion["ws"] is ws:
                    diffusion["actif"] = False

    async def _repondre(self, ws: Any, message: dict[str, Any]) -> None:
        methode = message.get("method")
        params = message.get("params") or {}
        session = message.get("sessionId")
        resultat: dict[str, Any] = {}
        apres = None
        if methode == "Target.getTargets":
            resultat = {"targetInfos": [self._info(c) for c in self.pages]}
        elif methode == "Target.getTargetInfo":
            if params.get("targetId") not in self.pages:
                await ws.send(json.dumps({"id": message["id"], "error": {"code": -32000, "message": "No target"}}))
                return
            resultat = {"targetInfo": self._info(params["targetId"])}
        elif methode == "Target.attachToTarget":
            cible = params.get("targetId")
            if cible not in self.pages:
                await ws.send(json.dumps({"id": message["id"], "error": {"code": -32000, "message": "No target"}}))
                return
            session = f"S-{cible}-{len(self._diffusions) + 1}"
            self._diffusions[session] = {"cible": cible, "n": 0, "actif": False, "ws": ws}
            resultat = {"sessionId": session}
        elif methode == "Page.startScreencast" and session in self._diffusions:
            self._diffusions[session]["actif"] = True
            apres = session
        elif methode == "Page.screencastFrameAck" and session in self._diffusions:
            await asyncio.sleep(self.delai_image)
            apres = session
        elif methode == "Page.stopScreencast" and session in self._diffusions:
            self._diffusions[session]["actif"] = False
        elif methode == "Target.detachFromTarget":
            diffusion = self._diffusions.get(params.get("sessionId"))
            if diffusion:
                diffusion["actif"] = False
        await ws.send(json.dumps({"id": message["id"], "result": resultat}))
        if apres:
            await self._image(ws, apres)
