"""Les routes `/v1/apps` de l'Atelier : les artefacts des projets.

Lister, créer, démarrer, arrêter, lire le journal, ouvrir. Elles vivent sur
l'origine de l'Atelier et n'y servent aucun contenu d'artefact : « ouvrir »
ne rend qu'un renvoi vers l'hôte des applications, avec un code de passage
d'usage unique (voir `passage`) — ou, sans hôte des applications, vers
l'adresse de secours `/v1/artifacts/<projet>/<nom>/` d'un artefact autonome.

`auteur` et `forcer` servent aux clients hors navigateur (`atelier-app`) :
un agent n'agit pas sur l'artefact d'une autre conversation sans le dire.
L'interface agit pour le propriétaire, sans cette règle.

Les routes `/v1/bureaux` font de même pour les services du namespace que
déclarent les connecteurs (voir `bureaux`) : le catalogue (ni amont ni
jeton), et « ouvrir », qui émet un code de portée `connecteur:<nom>`.
L'écran du navigateur d'une conversation s'ouvre par `/v1/ecran/<id>/ouvrir`
(voir `navigateur_routes`), en portée `conversation:<id>`.
"""

from __future__ import annotations

import logging
from typing import Any, Callable
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from mcp_gateway.atelier.apps.manifeste import ManifesteInvalide
from mcp_gateway.atelier.apps.passage import (
    connecteur_de_portee,
    conversation_de_portee,
    destination_valide,
    portee_du_chemin,
)
from mcp_gateway.atelier.apps.service import ApplicationInconnue, AutreAuteur, ServiceApps
from mcp_gateway.atelier.apps.superviseur import ErreurApplication, PlafondAtteint

log = logging.getLogger("atelier.apps.routes")

ENTETES_PASSAGE = {"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"}


def _erreur(exc: Exception) -> HTTPException:
    if isinstance(exc, ApplicationInconnue):
        return HTTPException(404, str(exc))
    if isinstance(exc, ManifesteInvalide):
        return HTTPException(422, str(exc))
    if isinstance(exc, (PlafondAtteint, AutreAuteur, FileExistsError)):
        return HTTPException(409, str(exc))
    return HTTPException(400, str(exc))


ERREURS = (ApplicationInconnue, ManifesteInvalide, ErreurApplication, AutreAuteur, FileExistsError, ValueError)


def renvoi_par_code(service: ServiceApps, sid: str, portee: str, destination: str) -> RedirectResponse:
    """Le 302 vers l'entrée de l'hôte des applications, code en main."""
    code = service.passage.emettre_code(sid, portee, destination)
    return RedirectResponse(
        f"{service.origine}/_atelier/entree?code={quote(code, safe='')}",
        302,
        headers=ENTETES_PASSAGE,
    )


def enregistrer_routes_apps(
    router: APIRouter,
    service: ServiceApps,
    *,
    require_owner: Callable[..., Any],
    require_owner_nav: Callable[..., Any],
    session_de: Callable[[Request], str | None],
) -> None:
    """Pose les routes sur le routeur `/v1` de l'Atelier.

    `session_de` rend l'identifiant de la session owner portée par la requête,
    s'il est valide : le passage s'y rattache, et tombe avec elle.
    """

    def sid_ou_refus(request: Request) -> str:
        sid = session_de(request)
        if not sid:
            raise HTTPException(
                400, "ouvrir un artefact se fait depuis le navigateur, session de l'Atelier ouverte"
            )
        return sid

    def forcer_par_defaut(request: Request, forcer: bool | None) -> bool:
        # L'interface (session du navigateur) agit pour le propriétaire ; un
        # client à la clé qui dit un auteur se soumet à la règle de voisinage.
        if forcer is not None:
            return forcer
        return session_de(request) is not None

    @router.get("/apps/entree", response_model=None)
    def apps_entree(request: Request, suite: str = "", _owner: str = Depends(require_owner_nav)):
        """Retour de l'hôte des applications, sans session : on émet un code."""
        if not service.expose:
            raise HTTPException(409, "pas d'hôte des applications (ATELIER_APPS_PUBLIC_URL vide)")
        destination = suite  # déjà décodé par FastAPI
        portee = portee_du_chemin(destination.split("?", 1)[0])
        if portee is None or not destination_valide(destination, portee):
            return HTMLResponse("<p>Adresse d'artefact invalide.</p>", status_code=400, headers=ENTETES_PASSAGE)
        if connecteur_de_portee(portee) is not None and service.bureaux.vue_du_chemin(destination) is None:
            # Un code ne s'émet que pour une vue que le pool déclare.
            return HTMLResponse("<p>Service inconnu.</p>", status_code=404, headers=ENTETES_PASSAGE)
        conversation = conversation_de_portee(portee)
        if conversation is not None and not service.ecrans.connue(conversation):
            # L'écran d'une conversation que l'Atelier ne connaît pas ne s'ouvre pas.
            return HTMLResponse("<p>Conversation inconnue.</p>", status_code=404, headers=ENTETES_PASSAGE)
        return renvoi_par_code(service, sid_ou_refus(request), portee, destination)

    # ── Les services du namespace (bureaux, éditeurs) ─────────────────

    @router.get("/bureaux")
    def bureaux_liste(_owner: str = Depends(require_owner)) -> dict[str, Any]:
        """Ce que les connecteurs actifs montrent : de quoi remplir l'onglet « Bureaux »."""
        return {"expose": service.expose, **service.bureaux.fiches()}

    @router.get("/bureaux/{connecteur}/{vue}/ouvrir", response_model=None)
    def bureaux_ouvrir(connecteur: str, vue: str, request: Request, _owner: str = Depends(require_owner_nav)):
        """Ouvre la vue d'un service : un code de la portée de ce seul connecteur."""
        trouvee = service.bureaux.vue(connecteur, vue)
        if trouvee is None:
            raise HTTPException(404, "service inconnu")
        if not service.expose:
            raise HTTPException(409, "un service ne s'ouvre que sur l'hôte des applications (ATELIER_APPS_PUBLIC_URL vide)")
        return renvoi_par_code(service, sid_ou_refus(request), trouvee.portee, trouvee.adresse_accueil)

    @router.get("/apps")
    def apps_liste(slug: str | None = None, _owner: str = Depends(require_owner)) -> dict[str, Any]:
        try:
            fiches = service.lister(slug) if slug else service.lister_tout()
        except ApplicationInconnue as exc:
            raise _erreur(exc) from None
        return {"expose": service.expose, "origine": service.origine, "artefacts": fiches}

    @router.get("/apps/{slug}")
    def apps_du_projet(slug: str, _owner: str = Depends(require_owner)) -> dict[str, Any]:
        return apps_liste(slug)

    @router.post("/apps/{slug}/{nom}/creer")
    def apps_creer(
        slug: str,
        nom: str,
        mode: str = "autonome",
        auteur: str | None = None,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        try:
            return service.creer(slug, nom, mode, auteur)
        except ERREURS as exc:
            raise _erreur(exc) from None

    @router.post("/apps/{slug}/{nom}/demarrer")
    async def apps_demarrer(
        request: Request,
        slug: str,
        nom: str,
        attendre: bool = False,
        auteur: str | None = None,
        forcer: bool | None = None,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        try:
            return await service.demarrer(
                slug, nom, attendre=attendre, auteur=auteur, forcer=forcer_par_defaut(request, forcer)
            )
        except ERREURS as exc:
            raise _erreur(exc) from None

    @router.post("/apps/{slug}/{nom}/arreter")
    async def apps_arreter(
        request: Request,
        slug: str,
        nom: str,
        auteur: str | None = None,
        forcer: bool | None = None,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        try:
            return await service.arreter(slug, nom, auteur=auteur, forcer=forcer_par_defaut(request, forcer))
        except ERREURS as exc:
            raise _erreur(exc) from None

    @router.get("/apps/{slug}/{nom}/journal", response_class=PlainTextResponse)
    def apps_journal(
        slug: str, nom: str, lignes: int = 200, _owner: str = Depends(require_owner)
    ) -> PlainTextResponse:
        try:
            texte = service.journal(slug, nom, lignes)
        except ERREURS as exc:
            raise _erreur(exc) from None
        # Du texte, rien d'autre : un journal contient ce que l'application a
        # écrit, balises comprises. `nosniff` interdit d'y voir du HTML.
        return PlainTextResponse(
            texte, headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}
        )

    @router.get("/apps/{slug}/{nom}/ouvrir", response_model=None)
    async def apps_ouvrir(
        slug: str, nom: str, request: Request, chemin: str = "", _owner: str = Depends(require_owner_nav)
    ):
        """Ouvre une création (et, avec `chemin`, une page sous elle) : le panneau s'en sert."""
        try:
            manifeste = service.manifeste(slug, nom)
        except ERREURS as exc:
            raise _erreur(exc) from None
        serveur = manifeste is not None and manifeste.service
        if not service.expose:
            if serveur:
                raise HTTPException(
                    409, "un artefact serveur ne s'ouvre que sur l'hôte des applications (ATELIER_APPS_PUBLIC_URL vide)"
                )
            # Palier de secours : les fichiers, en bac à sable, sur l'Atelier.
            return RedirectResponse(f"/v1/artifacts/{quote(slug, safe='')}/{nom}/", 302, headers=ENTETES_PASSAGE)
        sid = sid_ou_refus(request)
        if serveur:
            try:
                await service.demarrer(slug, nom, attendre=False)
            except ERREURS as exc:
                log.info("ouverture de %s/%s : %s", slug, nom, exc)
        destination = f"/{slug}/{nom}/" + chemin.lstrip("/")
        if not destination_valide(destination, slug):
            raise HTTPException(400, "chemin invalide")
        return renvoi_par_code(service, sid, slug, destination)
