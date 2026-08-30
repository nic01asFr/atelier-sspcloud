"""Déclare les projets de l'Atelier au coordinateur.

Un projet de l'Atelier et un projet wikichat sont la même chose : un dossier
de travail, ses agents, sa mémoire. Ils vivaient pourtant dans deux registres
séparés — celui du coordinateur restait vide, et les outils qui en dépendent
(suivi, audit, clôture, agents d'un projet) parlaient d'un ensemble sans
rapport avec ce que l'écran montrait.

Ce module tient l'alignement : ce que l'Atelier crée, le coordinateur le sait.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("atelier.wikichat_projects")

OUTIL_DECLARER = "wikichat__declare_project"
OUTIL_LISTER = "wikichat__list_projects"


def _description(rec: Any) -> str:
    """Une description est exigée ; à défaut, on dit au moins d'où ça vient."""
    titre = (getattr(rec, "title", "") or "").strip()
    slug = getattr(rec, "slug", "")
    return titre if titre and titre != slug else f"Projet de l'Atelier ({slug})"


async def declarer_projet(app: Any, rec: Any) -> dict[str, Any] | None:
    """Déclare un projet au coordinateur. Silencieux en cas d'échec.

    L'Atelier doit rester utilisable quand le coordinateur est absent : un
    projet créé ne peut pas dépendre de sa disponibilité.
    """
    pool = getattr(app.state, "pool", None)
    if pool is None:
        return None
    arguments = {
        "name": getattr(rec, "slug", "") or getattr(rec, "title", ""),
        "description": _description(rec),
        "repo": str(getattr(rec, "path", "") or ""),
    }
    if not arguments["name"]:
        return None
    try:
        return await pool.call(OUTIL_DECLARER, arguments)
    except Exception as exc:  # noqa: BLE001 — le coordinateur peut être arrêté
        log.info("déclaration wikichat impossible pour %s : %s", arguments["name"], exc)
        return None


async def synchroniser(app: Any, projets: list[Any]) -> dict[str, Any]:
    """Déclare tous les projets Code, pour rattraper l'existant.

    `declare_project` met à jour quand le nom existe déjà : rejouer la
    synchronisation ne duplique rien.
    """
    faits: list[str] = []
    echecs: list[str] = []
    for rec in projets:
        if getattr(rec, "kind", "") == "assistant":
            continue
        if getattr(rec, "archived", False):
            continue
        resultat = await declarer_projet(app, rec)
        (faits if resultat is not None else echecs).append(getattr(rec, "slug", "?"))
    return {"declares": faits, "echecs": echecs}
