"""Un « projet » mal désigné : dire à l'agent quoi prendre à la place, pas seulement « inconnu ».

Constaté le 13/10 : l'Assistant veut montrer un fichier qu'il vient d'écrire, passe l'identifiant de
sa propre conversation comme `projet`, reçoit « projet inconnu : 7c4373ee-… », et conclut que « l'Assistant
n'a pas de projet ». Le 12/10, un autre passe `wikichat-memory` (le slug de l'Assistant, qui figure
pourtant dans `atelier_projets`) et reçoit « projet inconnu » : il ne lui reste qu'à tâtonner.

Une erreur de désignation se corrige en une phrase quand elle porte ce qu'il faut : la liste des projets qui
existent, le nom proche s'il y en a un, et — pour l'espace de l'Assistant ou un identifiant de
conversation — pourquoi ce n'est pas un projet et ce qu'on fait alors. Toutes les commandes passent par ici,
pour qu'on ne retrouve pas dix messages différents, dont la moitié muets.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
MAX_LISTE = 15


def slugs(settings: Any) -> list[str]:
    """Les projets du pod (dossiers de `projects/`), sans l'espace de l'Assistant ni les dossiers techniques."""
    try:
        entrees = sorted(settings.projects_dir.iterdir())
    except OSError:
        return []
    return [
        e.name
        for e in entrees
        if e.is_dir() and not e.is_symlink() and not e.name.startswith((".", "_")) and e.name != settings.assistant_slug
    ]


def _liste(noms: list[str]) -> str:
    if not noms:
        return "aucun pour l'instant"
    vus = ", ".join(noms[:MAX_LISTE])
    return vus + (f" … ({len(noms)} au total : atelier_projets les liste)" if len(noms) > MAX_LISTE else "")


def espace_de_l_assistant(settings: Any, noms: list[str] | None = None) -> str:
    """Pourquoi l'espace de l'Assistant n'est pas la cible d'une création, d'un lancement ou d'un déploiement."""
    noms = slugs(settings) if noms is None else noms
    return (
        f"« {settings.assistant_slug} » est l'espace de l'Assistant, pas un projet : ce qui se crée, se lance "
        f"ou se déploie vit dans un projet. Prends-en un ({_liste(noms)}) "
        "ou crée-en un avec atelier_projet_creer(titre=…)."
    )


def projet_inconnu(settings: Any, valeur: Any) -> str:
    """Le refus d'un `projet` qui n'existe pas, avec de quoi se corriger."""
    v = str(valeur or "").strip()
    noms = slugs(settings)
    if v and v == settings.assistant_slug:
        return espace_de_l_assistant(settings, noms)
    if _UUID.match(v):
        return (
            f"« {v} » est l'identifiant d'une conversation, pas un projet. "
            f"Un projet se désigne par son slug : {_liste(noms)}."
        )
    proche = difflib.get_close_matches(v, noms, n=1, cutoff=0.6) if v else []
    piste = f" Voulais-tu dire « {proche[0]} » ?" if proche else ""
    return f"projet inconnu : {v}.{piste} Ceux qui existent : {_liste(noms)}."
