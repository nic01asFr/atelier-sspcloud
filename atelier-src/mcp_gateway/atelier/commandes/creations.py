"""Les commandes de création cadrée (vague 2, équipe K) : ce qu'elles partagent.

Quatre familles, une par module :

- `agents.py` : les agents planifiés ou à la demande, tenus par le Pilote de
  wikichat (ses triggers), qui est aussi ce que montre la vue Agents ;
- `connecteurs.py` : le pool de connecteurs de la passerelle, et le choix des
  connecteurs d'un projet ;
- `liens.py` : les relations entre projets, écrites dans wikichat
  (`set_project_meta.relations`), que lit la carte ;
- `migration.py` : la migration d'un projet d'avant vers la structure type.

`inscrire_les_creations(app, catalogue)` est la ligne que `commandes`
appelle. Les accès extérieurs (Pilote, outils wikichat, cartographie, sonde
d'un connecteur) sont rangés dans `app.state.creations` : un harnais de test
les remplace par des faux sans toucher au reste. Absents (harnais factice),
les commandes qui en dépendent refusent et disent pourquoi.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from mcp_gateway.atelier.commandes.modele import Refus

log = logging.getLogger("atelier.commandes")

# (chemin, corps) -> réponse JSON du Pilote.
PiloteLire = Callable[[], Awaitable[Any]]
PiloteEcrire = Callable[[str, "dict[str, Any] | None"], Awaitable[Any]]
PiloteSupprimer = Callable[[str], Awaitable[Any]]
# (outil qualifié, arguments) -> réponse MCP de l'outil.
OutilWikichat = Callable[[str, "dict[str, Any]"], Awaitable[Any]]
LireCartographie = Callable[[], Awaitable[Any]]
# nom du connecteur -> ce que la sonde a vu.
Sonder = Callable[[str], Awaitable["dict[str, Any]"]]


@dataclass
class AccesPilote:
    """Le Pilote de wikichat, par son API HTTP (celle qu'emploie la vue Agents)."""

    lire: PiloteLire
    ecrire: PiloteEcrire
    supprimer: PiloteSupprimer


@dataclass
class ServicesCreations:
    pilote: AccesPilote | None = None
    outil_wikichat: OutilWikichat | None = None
    cartographie: LireCartographie | None = None
    sonder: Sonder | None = None


# ── Arguments ───────────────────────────────────────────────────────────


def texte(args: dict[str, Any], cle: str, *, requis: bool = False, maximum: int = 500) -> str | None:
    valeur = args.get(cle)
    if valeur is None:
        if requis:
            raise Refus(f"{cle} requis")
        return None
    if not isinstance(valeur, str):
        raise Refus(f"{cle} doit être un texte")
    valeur = valeur.strip()
    if requis and not valeur:
        raise Refus(f"{cle} requis")
    if len(valeur) > maximum:
        raise Refus(f"{cle} : {maximum} caractères au plus")
    return valeur


def booleen(args: dict[str, Any], cle: str) -> bool:
    valeur = args.get(cle, False)
    if not isinstance(valeur, bool):
        raise Refus(f"{cle} : vrai ou faux")
    return valeur


def liste_de_noms(args: dict[str, Any], cle: str) -> list[str] | None:
    valeur = args.get(cle)
    if valeur is None:
        return None
    if not isinstance(valeur, list) or not all(isinstance(v, str) and v.strip() for v in valeur):
        raise Refus(f"{cle} : une liste de noms")
    return list(dict.fromkeys(v.strip() for v in valeur))


def entier(args: dict[str, Any], cle: str, *, minimum: int, maximum: int) -> int | None:
    valeur = args.get(cle)
    if valeur is None:
        return None
    if not isinstance(valeur, int) or isinstance(valeur, bool):
        raise Refus(f"{cle} : un entier")
    if not minimum <= valeur <= maximum:
        raise Refus(f"{cle} : entre {minimum} et {maximum}")
    return valeur


def texte_de_reponse_mcp(reponse: Any) -> str:
    """Le texte d'une réponse d'outil MCP (`content[].text`), ou sa forme JSON."""
    if isinstance(reponse, dict):
        morceaux = [
            str(b.get("text") or "")
            for b in reponse.get("content") or []
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        if morceaux:
            return "\n".join(morceaux)
    if isinstance(reponse, str):
        return reponse
    return json.dumps(reponse, ensure_ascii=False, default=str)


# ── Les accès réels ─────────────────────────────────────────────────────


def services_reels(app: Any) -> ServicesCreations:
    """Les accès du service en marche : Pilote et cartographie par HTTP, outils par le pool."""
    settings = app.state.settings
    if getattr(app.state, "use_fake", False):
        return ServicesCreations()

    from mcp_gateway.atelier.pilote_client import pilote_delete, pilote_get, pilote_post

    async def lire() -> Any:
        return await pilote_get(settings, "/pilote/api/data")

    async def ecrire(chemin: str, corps: dict[str, Any] | None) -> Any:
        return await pilote_post(settings, chemin, corps or {})

    async def supprimer(chemin: str) -> Any:
        return await pilote_delete(settings, chemin)

    async def outil_wikichat(nom: str, arguments: dict[str, Any]) -> Any:
        pool = getattr(app.state, "pool", None)
        if pool is None:
            raise RuntimeError("la passerelle n'a pas démarré")
        return await pool.call(nom, arguments)

    async def cartographie() -> Any:
        return await pilote_get(settings, "/api/cartographie?liens=relation")

    async def sonder(nom: str) -> dict[str, Any]:
        pool = getattr(app.state, "pool", None)
        if pool is None:
            return {"sonde": "non faite", "raison": "passerelle absente"}
        from mcp_gateway.registry import registry_pool_key

        statut = await pool.probe_registry_server(nom)
        vu = pool.client_probe(registry_pool_key(nom))
        return {"sonde": str(statut), **vu}

    return ServicesCreations(
        pilote=AccesPilote(lire=lire, ecrire=ecrire, supprimer=supprimer),
        outil_wikichat=outil_wikichat,
        cartographie=cartographie,
        sonder=sonder,
    )


def inscrire_les_creations(app: Any, catalogue: Any) -> ServicesCreations:
    """La ligne que `commandes.enregistrer` appelle : les quatre familles."""
    from mcp_gateway.atelier.commandes.agents import inscrire_les_agents
    from mcp_gateway.atelier.commandes.connecteurs import inscrire_les_connecteurs
    from mcp_gateway.atelier.commandes.liens import inscrire_les_liens
    from mcp_gateway.atelier.commandes.migration import inscrire_la_migration

    services = services_reels(app)
    app.state.creations = services
    inscrire_les_agents(app, catalogue)
    inscrire_les_connecteurs(app, catalogue)
    inscrire_les_liens(app, catalogue)
    inscrire_la_migration(app, catalogue)
    return services


def services_de(app: Any) -> ServicesCreations:
    """Les accès en vigueur, relus à chaque appel (un test peut les remplacer)."""
    services = getattr(app.state, "creations", None)
    return services if isinstance(services, ServicesCreations) else ServicesCreations()


__all__ = [
    "AccesPilote",
    "ServicesCreations",
    "booleen",
    "entier",
    "inscrire_les_creations",
    "liste_de_noms",
    "services_de",
    "services_reels",
    "texte",
    "texte_de_reponse_mcp",
]
