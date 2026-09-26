"""Le navigateur des agents, côté Atelier : son état et son écran en direct.

- `/chrome/health` : l'état local du navigateur (lanceur prêt, Chrome
  ouverts, plafonds). Le navigateur tourne en stdio dans le processus de
  chaque agent : il n'y a plus de service à joindre, ni de bureau noVNC à
  relayer. `bureau` reste dans la réponse, toujours faux, pour les interfaces
  qui le lisaient.
- `/v1/ecran/{conversation}` : ce que l'interface sait de l'écran de cette
  conversation (disponible, adresse, titre, main, actions en attente) ; ni
  port, ni chemin, ni processus.
- `/v1/ecran/{conversation}/ouvrir` : le passage vers l'hôte des
  applications, avec un code de portée `conversation:<id>` (voir
  `apps.passage`) ; c'est l'adresse que le panneau met dans son cadre.
- `POST /v1/ecran/{conversation}/main` : prendre ou rendre la main, comme le
  bouton de l'écran.

Les routes règlent aussi le registre des écrans (`apps.ecrans`) : quelles
conversations existent, sous quels autres noms leur navigateur a pu être
publié, si un tour travaille, et comment relancer l'agent quand la personne
rend la main.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from mcp_gateway.atelier.auth import ENTETE_INTERFACE, bearer_from_header
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.navigateur import etat_local
from mcp_gateway.atelier.vscode_bridge import COOKIE_NAME

log = logging.getLogger("atelier.navigateur")

ENTETES_PASSAGE = {"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"}


class CorpsMain(BaseModel):
    prendre: bool


def regler_les_ecrans(app: FastAPI) -> None:
    """Relie le registre des écrans aux conversations de l'Atelier."""
    service = getattr(app.state, "apps", None)
    store = getattr(app.state, "store", None)
    if service is None or store is None:
        return
    ecrans = service.ecrans

    def fiche(conversation: str) -> Any:
        try:
            return store.get(conversation)
        except Exception:  # noqa: BLE001 — un identifiant illisible n'est pas une conversation
            return None

    def connue(conversation: str) -> bool:
        return fiche(conversation) is not None

    def alias(conversation: str) -> list[str]:
        # Reprise dans VS Code ou au terminal : le lanceur n'y voit que
        # l'identifiant du CLI.
        rec = fiche(conversation)
        autre = getattr(rec, "claude_session_id", "") if rec is not None else ""
        return [autre] if autre and autre != conversation else []

    def tour_en_cours(conversation: str) -> bool:
        harness = getattr(app.state, "harness", None)
        verifier = getattr(harness, "tour_en_cours", None)
        try:
            return bool(verifier(conversation)) if verifier else False
        except Exception:  # noqa: BLE001
            return False

    def relancer(conversation: str, message: str) -> bool:
        """Un message à l'agent, dans un fil, visible en direct dans le fil de la conversation."""
        if fiche(conversation) is None:
            return False
        diffusion = getattr(app.state, "diffusion", None)

        def publier(ev: Any) -> None:
            if diffusion is not None:
                diffusion.publier(conversation, ev)

        def travail() -> None:
            try:
                store.send(conversation, message, on_event=publier, peut_attendre=diffusion is not None)
            except Exception:  # noqa: BLE001 — le fil de la conversation dira l'erreur
                log.exception("relance de %s après la reprise de main", conversation)

        threading.Thread(target=travail, name=f"reprise-{conversation}", daemon=True).start()
        return True

    ecrans.connue = connue
    ecrans.alias = alias
    ecrans.tour_en_cours = tour_en_cours
    ecrans.relancer = relancer


def register_navigateur_routes(
    app: FastAPI,
    settings: AtelierSettings,
    auth_dep: Callable[..., Any],
) -> None:
    """Monte `/chrome/health` et `/v1/ecran/…`, et règle le registre des écrans."""

    @app.get("/chrome/health")
    async def chrome_health(_owner: str = Depends(auth_dep)) -> JSONResponse:
        # La vérification lance le lanceur (sans rien ouvrir) : hors de la
        # boucle, pour ne pas la bloquer.
        return JSONResponse(await run_in_threadpool(etat_local, settings))

    regler_les_ecrans(app)

    def owner_api(request: Request) -> str:
        """Clé au porteur, ou session de l'interface (même règle que `require_owner`)."""
        return app.state.auth.check_api(
            bearer_from_header(request.headers.get("authorization")),
            request.cookies.get(COOKIE_NAME),
            request.headers.get(ENTETE_INTERFACE) == "1",
        )

    def service_et_conversation(conversation: str) -> Any:
        from mcp_gateway.atelier.apps.passage import conversation_valide

        service = getattr(app.state, "apps", None)
        if service is None:
            raise HTTPException(503, "écran indisponible")
        if not conversation_valide(conversation) or not service.ecrans.connue(conversation):
            raise HTTPException(404, "conversation inconnue")
        return service

    @app.get("/v1/ecran/{conversation}")
    async def ecran_etat(conversation: str, _owner: str = Depends(owner_api)) -> dict[str, Any]:
        service = service_et_conversation(conversation)
        return await run_in_threadpool(service.ecrans.etat, conversation)

    @app.get("/v1/ecran/{conversation}/ouvrir", response_model=None)
    async def ecran_ouvrir(conversation: str, request: Request, _owner: str = Depends(auth_dep)):
        """L'écran dans le panneau : un code de la portée de cette seule conversation."""
        from mcp_gateway.atelier.apps.passage import portee_conversation

        service = service_et_conversation(conversation)
        if not service.expose:
            raise HTTPException(
                409, "l'écran ne s'ouvre que sur l'hôte des applications (ATELIER_APPS_PUBLIC_URL vide)"
            )
        sid = request.cookies.get(COOKIE_NAME)
        if not sid or not app.state.auth.session_valide(sid):
            raise HTTPException(400, "l'écran s'ouvre depuis le navigateur, session de l'Atelier ouverte")
        code = service.passage.emettre_code(sid, portee_conversation(conversation), f"/_ecran/{conversation}/")
        return RedirectResponse(
            f"{service.origine}/_atelier/entree?code={quote(code, safe='')}", 302, headers=ENTETES_PASSAGE
        )

    @app.post("/v1/ecran/{conversation}/main")
    async def ecran_main(conversation: str, corps: CorpsMain, _owner: str = Depends(owner_api)) -> dict[str, Any]:
        from mcp_gateway.atelier.ecran import EcranIndisponible

        service = service_et_conversation(conversation)
        geste = service.ecrans.prendre_la_main if corps.prendre else service.ecrans.rendre_la_main
        try:
            return await run_in_threadpool(geste, conversation)
        except EcranIndisponible as exc:
            raise HTTPException(409, str(exc)) from None
