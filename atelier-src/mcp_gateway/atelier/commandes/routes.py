"""L'API HTTP du catalogue, du journal et de la file « À valider ».

Toutes les routes demandent le propriétaire (clé au porteur, ou session de
l'interface). Mais seule la session de l'interface vaut « la personne » :
la clé au porteur est aussi celle des agents du pod, et un appel qui la porte
est traité comme celui d'un modèle (une commande réservée lui est refusée,
une engageante lui rend un aperçu).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Annotated, Any, Iterator

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from mcp_gateway.atelier.auth import ENTETE_INTERFACE
from mcp_gateway.atelier.commandes.a_valider import ErreurAValider
from mcp_gateway.atelier.commandes.catalogue import APERCU, ERREUR, FAIT, REFUSE, Catalogue, Reponse
from mcp_gateway.atelier.commandes.modele import ORIGINE_CLE, ORIGINE_INTERFACE, Contexte
from mcp_gateway.atelier.commandes.profils import ENTETE_PROFIL, PROFIL_APPELANT, lire_profil, outil_permis
from mcp_gateway.atelier.vscode_bridge import COOKIE_NAME
from mcp_gateway.auth import bearer_from_header

_STATUTS_HTTP = {FAIT: 200, APERCU: 200, REFUSE: 403, ERREUR: 422}


class CorpsCommande(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)
    confirmation: str | None = None


class CorpsConfirmation(BaseModel):
    jeton: str


class CorpsDepot(BaseModel):
    source: str
    titre: str
    resume: str = ""
    projet: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)
    action: dict[str, Any] | None = None
    empreinte: str = ""


class CorpsDecision(BaseModel):
    decision: str
    motif: str = ""
    complete: dict[str, Any] | None = None


def _rendre(reponse: Reponse) -> JSONResponse:
    corps = {"statut": reponse.statut, "action": reponse.action or None, "resultat": reponse.charge}
    return JSONResponse(corps, status_code=_STATUTS_HTTP.get(reponse.statut, 200))


@contextmanager
def _appel_de(request: Request, ctx: Contexte) -> Iterator[None]:
    """La conversation et le profil annoncés, pour la durée de l'appel.

    Les mêmes que la porte `/mcp` : une commande appelée ici par un agent
    (`atelier-app`) passe par les mêmes gardes que son outil. La personne,
    dans l'interface, n'annonce ni l'un ni l'autre.
    """
    from mcp_gateway.atelier.outils_conversation import CONVERSATION_APPELANTE

    if ctx.est_la_personne:
        yield
        return
    conversation = (request.headers.get("x-atelier-conversation") or "").strip()[:200]
    jeton = CONVERSATION_APPELANTE.set(conversation)
    jeton_profil = PROFIL_APPELANT.set(lire_profil(request.headers.get(ENTETE_PROFIL)))
    try:
        yield
    finally:
        CONVERSATION_APPELANTE.reset(jeton)
        PROFIL_APPELANT.reset(jeton_profil)


def construire_le_routeur(app: Any) -> APIRouter:
    router = APIRouter(prefix="/v1")

    def contexte(
        request: Request, authorization: Annotated[str | None, Header()] = None
    ) -> Contexte:
        auth = app.state.auth
        qui = auth.check_api(
            bearer_from_header(authorization),
            request.cookies.get(COOKIE_NAME),
            request.headers.get(ENTETE_INTERFACE) == "1",
        )
        conversation = (request.headers.get("x-atelier-conversation") or "").strip()[:200]
        if qui == "session":
            return Contexte(acteur="personne", origine=ORIGINE_INTERFACE)
        return Contexte(
            acteur=f"conversation:{conversation}" if conversation else "cle-proprietaire",
            origine=ORIGINE_CLE,
        )

    def catalogue() -> Catalogue:
        return app.state.commandes

    @router.get("/commandes")
    def lister_les_commandes(request: Request, ctx: Contexte = Depends(contexte)) -> dict[str, Any]:
        with _appel_de(request, ctx):
            return {"commandes": [c for c in catalogue().declarations() if outil_permis(c["nom"])]}

    @router.post("/commandes/confirmer")
    async def confirmer(
        request: Request, corps: CorpsConfirmation, ctx: Contexte = Depends(contexte)
    ) -> JSONResponse:
        with _appel_de(request, ctx):
            return _rendre(await catalogue().confirmer(corps.jeton, ctx))

    @router.post("/commandes/{nom}")
    async def executer(
        request: Request, nom: str, corps: CorpsCommande, ctx: Contexte = Depends(contexte)
    ) -> JSONResponse:
        if catalogue().commande(nom) is None:
            raise HTTPException(404, f"commande inconnue : {nom}")
        arguments = dict(corps.arguments)
        if corps.confirmation:
            arguments["confirmation"] = corps.confirmation
        with _appel_de(request, ctx):
            return _rendre(await catalogue().executer(nom, arguments, ctx))

    @router.get("/journal")
    def lire_le_journal(
        depuis: str = "",
        source: str = "",
        acteur: str = "",
        objet_type: str = "",
        objet: str = "",
        commande: str = "",
        limite: int = 100,
        ctx: Contexte = Depends(contexte),
    ) -> dict[str, Any]:
        del ctx
        evenements = catalogue().journal.lire(
            depuis=depuis,
            source=source,
            acteur=acteur,
            objet_type=objet_type,
            objet_id=objet,
            commande=commande,
            limite=max(1, min(limite, 1000)),
        )
        return {"evenements": evenements, "nombre": len(evenements)}

    @router.get("/a-valider")
    async def lire_la_file(
        statut: str = "en_attente", projet: str = "", source: str = "", ctx: Contexte = Depends(contexte)
    ) -> JSONResponse:
        arguments = {"statut": statut, "projet": projet, "source": source}
        return _rendre(await catalogue().executer("atelier_a_valider", arguments, ctx))

    @router.post("/a-valider")
    def deposer(corps: CorpsDepot, ctx: Contexte = Depends(contexte)) -> dict[str, Any]:
        try:
            p = app.state.a_valider.deposer(
                corps.source,
                corps.titre,
                corps.resume,
                acteur=ctx.acteur,
                projet=corps.projet,
                detail=corps.detail,
                action=corps.action,
                empreinte=corps.empreinte,
            )
        except ErreurAValider as exc:
            raise HTTPException(422, str(exc)) from None
        return {"proposition": p.to_dict()}

    @router.post("/a-valider/{identifiant}/decision")
    async def decider(identifiant: str, corps: CorpsDecision, ctx: Contexte = Depends(contexte)) -> JSONResponse:
        choix = corps.decision.strip().lower()
        if choix in ("accepter", "acceptee", "approve"):
            nom = "atelier_a_valider_accepter"
        elif choix in ("refuser", "refusee", "reject"):
            nom = "atelier_a_valider_refuser"
        else:
            raise HTTPException(422, "decision : accepter ou refuser")
        arguments: dict[str, Any] = {"id": identifiant, "motif": corps.motif}
        if corps.complete is not None and nom == "atelier_a_valider_accepter":
            arguments["complete"] = corps.complete
        return _rendre(await catalogue().executer(nom, arguments, ctx))

    return router


__all__ = ["construire_le_routeur"]
