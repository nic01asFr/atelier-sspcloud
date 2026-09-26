"""Les liens entre projets : `atelier_projets_lier`, écrit dans wikichat.

Les relations entre projets appartiennent à la couche projets et connaissance,
donc à wikichat (transverse §1.3, S5) : `set_project_meta.relations`, que la
cartographie (`GET /api/cartographie`) publie en arêtes `relation`, et que
l'Atelier assemble dans sa carte. La commande n'écrit rien chez elle : elle
appelle l'outil de wikichat par le pool de la passerelle.

`set_project_meta` **remplace** la liste des relations d'un projet. La
commande lit donc d'abord celles qui existent (arêtes `relation` de la
cartographie qui partent du projet), ajoute ou retire la sienne, et écrit la
liste entière. Annuler réécrit la liste d'avant.

Limite : une relation déjà enregistrée vers un projet que la cartographie ne
connaît pas (`limites.relations_sans_cible`) n'y figure pas ; réécrire la
liste la perd. Le nombre est rendu dans la preuve.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_gateway.atelier.commandes import structure
from mcp_gateway.atelier.commandes.catalogue import Catalogue
from mcp_gateway.atelier.commandes.creations import booleen, services_de, texte, texte_de_reponse_mcp
from mcp_gateway.atelier.commandes.modele import REVERSIBLE, Commande, Contexte, Effet, Refus

log = logging.getLogger("atelier.commandes")

LIER = "atelier_projets_lier"
OUTIL_META = "wikichat__set_project_meta"
# wikichat commence un refus par ce signe (U+274C).
ECHEC_WIKICHAT = "\u274c"
TYPES = ("depends-on", "provides-to", "sibling-of", "superseded-by", "fork-of")


def relations_de(cartographie: Any, slug: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Les relations déclarées qui partent de `slug`, et son nœud (None s'il est inconnu)."""
    if not isinstance(cartographie, dict):
        raise Refus("cartographie de wikichat illisible")
    noeuds = [n for n in cartographie.get("noeuds") or [] if isinstance(n, dict)]
    noeud = next((n for n in noeuds if n.get("id") == slug), None) or next(
        (n for n in noeuds if structure.slugifier(str(n.get("nom") or "")) == slug), None
    )
    if noeud is None:
        return [], None
    relations = []
    for a in cartographie.get("aretes") or []:
        if not isinstance(a, dict) or a.get("type") != "relation" or a.get("de") != noeud.get("id"):
            continue
        r: dict[str, Any] = {"type": str(a.get("sous_type") or ""), "project": str(a.get("vers") or "")}
        if a.get("note"):
            r["note"] = str(a["note"])
        if r["type"] in TYPES and r["project"]:
            relations.append(r)
    return relations, noeud


def _cle(r: dict[str, Any]) -> tuple[str, str]:
    return (r["type"], r["project"])


def inscrire_les_liens(app: Any, catalogue: Catalogue) -> None:
    settings = app.state.settings

    def projet_connu(slug: str, noeuds: list[dict[str, Any]]) -> bool:
        if (settings.projects_dir / slug).is_dir():
            return True
        return any(n.get("id") == slug for n in noeuds)

    async def lire_la_carte() -> dict[str, Any]:
        lire = services_de(app).cartographie
        if lire is None:
            raise Refus("wikichat n'est pas joignable ici : les liens entre projets vivent chez lui")
        try:
            carte = await lire()
        except Exception as exc:  # noqa: BLE001
            raise Refus(f"cartographie de wikichat illisible : {type(exc).__name__}: {exc}") from None
        if not isinstance(carte, dict):
            raise Refus("cartographie de wikichat illisible")
        return carte

    async def ecrire(slug: str, relations: list[dict[str, Any]]) -> str:
        outil = services_de(app).outil_wikichat
        if outil is None:
            raise Refus("wikichat n'est pas joignable ici : les liens entre projets vivent chez lui")
        arguments = {"project": slug, "relations": relations}
        try:
            texte_retour = texte_de_reponse_mcp(await outil(OUTIL_META, arguments))
            if "introuvable" in texte_retour and texte_retour.lstrip().startswith(ECHEC_WIKICHAT):
                # Un projet que wikichat ne connaît pas encore : on le déclare,
                # comme l'Atelier le fait à la création, puis on réécrit.
                from mcp_gateway.atelier.wikichat_projects import OUTIL_DECLARER

                titre = structure.titre_declare(settings.projects_dir / slug) or slug
                await outil(
                    OUTIL_DECLARER,
                    {"name": slug, "description": titre, "repo": str(settings.projects_dir / slug)},
                )
                texte_retour = texte_de_reponse_mcp(await outil(OUTIL_META, arguments))
        except Refus:
            raise
        except Exception as exc:  # noqa: BLE001
            raise Refus(f"wikichat n'a pas pris les relations : {type(exc).__name__}: {exc}") from None
        if texte_retour.lstrip().startswith(ECHEC_WIKICHAT):
            raise Refus(f"wikichat a refusé : {texte_retour[:300]}")
        return texte_retour

    async def lier(ctx: Contexte, args: dict[str, Any]) -> Effet:
        slug = texte(args, "projet", requis=True, maximum=60) or ""
        if structure.slugifier(slug) != slug:
            raise Refus("projet : un slug (minuscules, chiffres, tirets)")
        carte = await lire_la_carte()
        noeuds = [n for n in carte.get("noeuds") or [] if isinstance(n, dict)]
        if not projet_connu(slug, noeuds):
            raise Refus(f"projet inconnu : {slug}")
        avant, _ = relations_de(carte, slug)
        remplacement = args.get("relations")
        if remplacement is not None:
            # Forme de l'annulation : la liste entière, telle qu'elle était.
            if set(args) - {"projet", "relations"}:
                raise Refus("relations (la liste entière) ne se combine pas avec vers, type ou retirer")
            if not isinstance(remplacement, list):
                raise Refus("relations : une liste de {type, project, note?}")
            apres = []
            for r in remplacement:
                if not isinstance(r, dict) or r.get("type") not in TYPES or not isinstance(r.get("project"), str):
                    raise Refus(f"relation invalide : {r!r}")
                propre = {"type": r["type"], "project": r["project"]}
                if isinstance(r.get("note"), str) and r["note"].strip():
                    propre["note"] = r["note"].strip()[:300]
                apres.append(propre)
        else:
            vers = texte(args, "vers", requis=True, maximum=60) or ""
            genre = texte(args, "type", maximum=20) or "depends-on"
            if genre not in TYPES:
                raise Refus(f"type : {', '.join(TYPES)}")
            if vers == slug:
                raise Refus("un projet ne se lie pas à lui-même")
            if not projet_connu(vers, noeuds):
                raise Refus(f"projet inconnu : {vers}")
            note = texte(args, "note", maximum=300)
            retirer = booleen(args, "retirer")
            cle = (genre, vers)
            apres = [r for r in avant if _cle(r) != cle]
            if not retirer:
                nouvelle: dict[str, Any] = {"type": genre, "project": vers}
                if note:
                    nouvelle["note"] = note
                apres.append(nouvelle)
            elif len(apres) == len(avant):
                raise Refus(f"aucun lien {genre} de {slug} vers {vers}")
        change = sorted(map(_cle, apres)) != sorted(map(_cle, avant)) or apres != avant
        reponse = await ecrire(slug, apres) if change else ""
        limites = carte.get("limites") if isinstance(carte.get("limites"), dict) else {}
        return Effet(
            charge={"projet": slug, "relations": apres, "avant": avant},
            objet_id=slug,
            titre="Lien entre projets enregistré" if change else "Liens inchangés",
            resume=", ".join(f"{r['type']} {r['project']}" for r in apres) or "aucun lien",
            voir=f"/?slug={slug}",
            preuve={
                "wikichat": reponse.splitlines()[0] if reponse else "",
                "outil": OUTIL_META,
                "relations_ecrites": len(apres),
                "relations_sans_cible_dans_la_carte": limites.get("relations_sans_cible"),
            },
            avant=avant,
            apres=apres,
            inverse_arguments={"projet": slug, "relations": avant} if change else None,
        )

    catalogue.ajouter(
        Commande(
            nom=LIER,
            description=(
                "Lie deux projets (depends-on, provides-to, sibling-of, superseded-by, fork-of), ou "
                "retire ce lien (retirer=true). Écrit les relations du projet dans wikichat : elles "
                "apparaissent dans la carte. Annuler remet les relations d'avant."
            ),
            objet="projet",
            classe=REVERSIBLE,
            inverse=LIER,
            regles=[
                "écrit par wikichat (set_project_meta.relations), jamais dans l'Atelier",
                "garde les autres relations du projet : lit la liste, la complète, la réécrit",
                "un projet inconnu de wikichat y est d'abord déclaré",
            ],
            executer=lier,
            schema={
                "type": "object",
                "properties": {
                    "projet": {"type": "string", "description": "Slug du projet d'où part le lien."},
                    "vers": {"type": "string", "description": "Slug du projet visé."},
                    "type": {"type": "string", "enum": list(TYPES), "description": "Défaut : depends-on."},
                    "note": {"type": "string"},
                    "retirer": {"type": "boolean"},
                    "relations": {
                        "type": "array",
                        "description": "Réservé à l'annulation : la liste entière d'avant.",
                        "items": {"type": "object"},
                    },
                },
                "required": ["projet"],
            },
        )
    )


__all__ = ["LIER", "TYPES", "inscrire_les_liens", "relations_de"]
