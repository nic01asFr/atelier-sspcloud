"""`atelier_carte` et `GET /v1/carte` : la carte de l'Atelier, par la porte du catalogue.

Le calcul vit dans `atelier/carte.py`. Ce module le branche :

- la commande `atelier_carte`, classe `lecture`, objet `carte`. Elle n'est pas
  dans le profil `code` (`profils.OUTILS_DU_PROFIL_CODE`) : un agent code ne la
  voit pas et son appel est refusé, par la porte `/mcp` comme par
  `/v1/commandes` et `/v1/carte`. L'Assistant la reçoit ;
- la route `GET /v1/carte?forme=synthetique|complete|projet&projet=<slug>&rafraichir=1`,
  qui passe par la même commande, donc par les mêmes gardes ;
- le crochet `apres_commande` du catalogue : toute commande réussie qui agit
  invalide la carte, recalculée à la lecture suivante.

`inscrire_la_carte(app, catalogue)` est la ligne que `commandes.enregistrer`
appelle.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse

from mcp_gateway.atelier.carte import (
    FORME_PROJET,
    FORME_SYNTHETIQUE,
    FORMES,
    Carte,
    Sources,
    lire_conversations,
    lire_creations,
    lire_pool,
    lire_projets,
    sources_http,
)
from mcp_gateway.atelier.commandes.catalogue import FAIT, REFUSE, Catalogue
from mcp_gateway.atelier.commandes.modele import (
    LECTURE,
    ORIGINE_CLE,
    ORIGINE_INTERFACE,
    Commande,
    Contexte,
    Effet,
    Refus,
)

NOM = "atelier_carte"
ACTEUR_INTERNE = "atelier:carte"


def sources_de_l_atelier(app: Any, catalogue: Catalogue) -> Sources:
    """Les lecteurs de la carte, branchés sur ce que l'Atelier tient déjà."""
    from mcp_gateway.atelier.wikichat_pilote_proxy import wikichat_http_origin

    settings = app.state.settings
    http = sources_http(wikichat_http_origin(settings))

    async def a_valider() -> Any:
        # La file et le pilote de wikichat, lus par la commande qui les lit déjà.
        reponse = await catalogue.executer(
            "atelier_a_valider", {"statut": "en_attente"}, Contexte(acteur=ACTEUR_INTERNE, origine=ORIGINE_CLE)
        )
        if reponse.statut != FAIT:
            raise ValueError(f"atelier_a_valider : {reponse.statut}")
        return reponse.charge

    return Sources(
        projets=lambda: lire_projets(app.state.projects),
        pool=lambda: lire_pool(settings),
        creations=lambda: lire_creations(getattr(app.state, "apps", None)),
        conversations=lambda: lire_conversations(app.state.store, getattr(app.state, "harness", None)),
        wikichat=http["wikichat"],
        gardiens_alertes=http["gardiens_alertes"],
        gardiens_automates=http["gardiens_automates"],
        a_valider=a_valider,
        filtre=catalogue.journal.filtre.nettoyer,
        assistant=str(getattr(settings, "assistant_slug", "") or ""),
    )


def _arguments(args: dict[str, Any]) -> tuple[str, str, bool]:
    forme = args.get("forme")
    projet = args.get("projet")
    rafraichir = args.get("rafraichir", False)
    if forme is not None and not isinstance(forme, str):
        raise Refus("forme : un texte")
    if projet is not None and not isinstance(projet, str):
        raise Refus("projet : un slug")
    if not isinstance(rafraichir, bool):
        raise Refus("rafraichir : vrai ou faux")
    projet = (projet or "").strip()
    forme = (forme or "").strip() or (FORME_PROJET if projet else FORME_SYNTHETIQUE)
    return forme, projet, rafraichir


def commande_carte(carte: Carte) -> Commande:
    async def executer(ctx: Contexte, args: dict[str, Any]) -> Effet:
        forme, projet, rafraichir = _arguments(args)
        try:
            charge = await carte.forme(forme, projet=projet, rafraichir=rafraichir)
        except ValueError as exc:
            raise Refus(str(exc)) from None
        return Effet(charge=charge, objet_id=projet or forme)

    return Commande(
        nom=NOM,
        description=(
            "La carte de l'Atelier : projets, créations, conversations et agents en cours, "
            "connecteurs, tâches automatiques, alertes des gardiens, propositions à valider, et "
            "les liens entre projets (wikichat). Par défaut une vue synthétique courte ; "
            "forme=projet avec projet=<slug> pour le détail d'un projet et de son voisinage ; "
            "forme=complete pour le graphe entier (volumineux). Calculée par le code, jamais saisie."
        ),
        objet="carte",
        classe=LECTURE,
        regles=[
            "lecture seule : ne change rien",
            "calculée depuis projet.json, le pool, le superviseur, les fiches, wikichat et les gardiens",
            "recalculée après chaque commande qui agit, et au plus tard après un court délai",
            "servie même quand wikichat ne répond pas, et le dit dans sources",
            "aucun secret : noms des connecteurs seulement, textes filtrés",
        ],
        executer=executer,
        schema={
            "type": "object",
            "properties": {
                "forme": {"type": "string", "enum": list(FORMES),
                          "description": "synthetique (défaut), projet ou complete."},
                "projet": {"type": "string", "description": "Slug du projet, pour forme=projet."},
                "rafraichir": {"type": "boolean", "description": "Recalculer sans attendre le délai."},
            },
        },
    )


def construire_le_routeur(app: Any) -> APIRouter:
    from mcp_gateway.atelier.auth import ENTETE_INTERFACE
    from mcp_gateway.atelier.commandes.profils import outil_permis
    from mcp_gateway.atelier.commandes.routes import _appel_de
    from mcp_gateway.atelier.vscode_bridge import COOKIE_NAME
    from mcp_gateway.auth import bearer_from_header

    router = APIRouter(prefix="/v1")

    def contexte(request: Request, authorization: Annotated[str | None, Header()] = None) -> Contexte:
        # Le même contrôle que `/v1/commandes` : la session de l'interface est la
        # personne, la clé au porteur un modèle possible.
        qui = app.state.auth.check_api(
            bearer_from_header(authorization),
            request.cookies.get(COOKIE_NAME),
            request.headers.get(ENTETE_INTERFACE) == "1",
        )
        conversation = (request.headers.get("x-atelier-conversation") or "").strip()[:200]
        if qui == "session":
            return Contexte(acteur="personne", origine=ORIGINE_INTERFACE)
        return Contexte(
            acteur=f"conversation:{conversation}" if conversation else "cle-proprietaire", origine=ORIGINE_CLE
        )

    @router.get("/carte")
    async def lire_la_carte(
        request: Request,
        forme: str = "",
        projet: str = "",
        rafraichir: bool = False,
        ctx: Contexte = Depends(contexte),
    ) -> JSONResponse:
        arguments: dict[str, Any] = {"rafraichir": rafraichir}
        if forme:
            arguments["forme"] = forme
        if projet:
            arguments["projet"] = projet
        with _appel_de(request, ctx):
            hors_profil = not outil_permis(NOM)
            reponse = await app.state.commandes.executer(NOM, arguments, ctx)
        if reponse.statut == FAIT:
            return JSONResponse(reponse.charge)
        if reponse.statut == REFUSE:
            # Hors profil : interdit ; sinon, une demande mal formée (forme, projet).
            statut = 403 if hors_profil else 422
        else:
            statut = 500
        return JSONResponse({"statut": reponse.statut, "resultat": reponse.charge}, status_code=statut)

    return router


def inscrire_la_carte(app: Any, catalogue: Catalogue) -> Carte:
    """La commande, la route, le crochet d'invalidation ; `app.state.carte`."""
    carte = Carte(sources_de_l_atelier(app, catalogue))
    catalogue.ajouter(commande_carte(carte))
    catalogue.apres_commande.append(lambda nom, _charge: carte.invalider(nom))
    app.include_router(construire_le_routeur(app))
    app.state.carte = carte
    return carte


__all__ = ["NOM", "commande_carte", "construire_le_routeur", "inscrire_la_carte", "sources_de_l_atelier"]
