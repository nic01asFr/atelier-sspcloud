"""Écrit dans le projet ce qu'une session ne peut pas deviner.

Une conversation ignore le nom sous lequel elle parle au coordinateur et le
projet dont elle relève : ce sont des décisions de l'Atelier, prises au
lancement. Sans les lui dire, elle appelle un outil pour se situer — ou pire,
travaille à côté, en écrivant ses notes dans un projet qu'elle a deviné.

`--append-system-prompt` semblait la voie naturelle. Mesuré sur le pod : le
drapeau est accepté sans erreur, mais la consigne n'atteint pas le modèle
servi par la passerelle LLM. On passe donc par ce que Claude Code lit de
lui-même à l'ouverture d'un dossier, `CLAUDE.md` — mécanisme prévu pour cela,
lisible par un humain, et qui survit à tout changement de harnais.

Le fichier appartient au projet : on n'y tient qu'une section délimitée, et
on ne touche jamais au reste.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("atelier.project_context")

DEBUT = "<!-- atelier:contexte -->"
FIN = "<!-- /atelier:contexte -->"


def bloc_contexte(slug: str, chemin: Path) -> str:
    """La section telle qu'elle doit apparaître dans le CLAUDE.md du projet."""
    return "\n".join(
        [
            DEBUT,
            "## Ce projet dans l'Atelier",
            "",
            f"Tu travailles sur le projet **{slug}**, dossier `{chemin}`.",
            "",
            "- Ton inscription auprès du coordinateur wikichat est automatique :"
            " n'appelle pas `register`. Ton nom t'est attribué par l'Atelier et"
            " commence par le nom du projet ; `get_briefing` te le rappelle.",
            "- Ce que tu retiens avec `remember` n'appartient qu'à toi.",
            f"- Ce que tu écris avec `add_project_note` est partagé par toutes les"
            f" conversations de **{slug}**. C'est ce nom de projet qu'attendent"
            " les outils qui en demandent un.",
            "",
            "_Section tenue par l'Atelier ; le reste du fichier est à vous._",
            FIN,
        ]
    )


def ecrire_contexte(cwd: Path, slug: str) -> bool:
    """Pose ou met à jour la section dans `<projet>/CLAUDE.md`.

    Retourne True si le fichier a changé. Rien n'est réécrit quand le contenu
    est déjà le bon : le fichier est souvent sous git, une modification sans
    objet salirait l'état du dépôt à chaque tour.
    """
    bloc = bloc_contexte(slug, cwd)
    chemin = cwd / "CLAUDE.md"
    try:
        ancien = chemin.read_text(encoding="utf-8") if chemin.is_file() else ""
    except OSError as exc:
        log.info("CLAUDE.md illisible dans %s : %s", cwd, exc)
        return False

    if DEBUT in ancien and FIN in ancien:
        avant, _, reste = ancien.partition(DEBUT)
        _, _, apres = reste.partition(FIN)
        nouveau = avant + bloc + apres
    elif ancien.strip():
        nouveau = ancien.rstrip() + "\n\n" + bloc + "\n"
    else:
        nouveau = bloc + "\n"

    if nouveau == ancien:
        return False
    try:
        cwd.mkdir(parents=True, exist_ok=True)
        chemin.write_text(nouveau, encoding="utf-8")
    except OSError as exc:
        log.info("CLAUDE.md non écrit dans %s : %s", cwd, exc)
        return False
    return True
