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
from typing import Any

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
            "### Montrer ce que tu produis",
            "",
            "Un port ouvert sur le pod n'est joignable par personne : ne cherche pas"
            " d'URL publique, ne lance pas de serveur à la main pour le montrer. Un"
            " artefact = un dossier `artifacts/<nom>/` = une adresse sur l'hôte des"
            " applications ; `atelier_artefacts` la donne.",
            "",
            "- **Autonome** (fichiers) : `atelier_artefact_creer(projet, nom)`, dépose"
            " tes fichiers dans `artifacts/<nom>/` (`index.html` s'ouvre à la racine,"
            " liens relatifs, tout embarqué : bac à sable sans réseau extérieur).",
            "- **Serveur** (processus) : `atelier_artefact_creer(projet, nom,"
            " mode=\"serveur\")`, complète `artifacts/<nom>/artefact.json` (`commande`"
            " en liste avec `{port}`, `sante`, `protocoles`, `repertoire` relatif au"
            " dossier), puis `atelier_artefact_verifier` et `atelier_artefact_demarrer`.",
            "- Même adresse dans les deux modes. On n'agit pas sur l'artefact d'une"
            " autre conversation (`forcer` seulement si on te le demande) ; sans MCP,"
            " `~/work/bin/atelier-app`.",
            "",
            "### Le web",
            "",
            "- WebSearch n'existe pas ici (la passerelle LLM le simulerait) : pour"
            " chercher, ouvre `https://html.duckduckgo.com/html/?q=<mots>` avec le"
            " navigateur (`chrome-devtools-mcp`). WebFetch lit une page dont tu as l'adresse.",
            "- Le navigateur est un Chrome sans écran, à toi seul, fermé avec la"
            " conversation. Pour lire une longue page, préfère `evaluate_script`"
            " (`() => document.body.innerText.slice(0, 20000)`) à `take_snapshot`,"
            " qui rend tout l'arbre de la page.",
            "",
            "_Section tenue par l'Atelier ; le reste du fichier est à vous._",
            FIN,
        ]
    )


IMPORT_DU_CONTEXTE = "@.atelier/contexte.md"


def dossier_du_contexte(settings: Any, cwd: Path, slug: str) -> Path | None:
    """Le seul dossier où le contexte de `slug` peut s'écrire, ou None.

    Le contexte s'écrivait dans le `cwd` de la conversation, quel qu'il soit.
    Le 24/09, une fiche dont le `cwd` était `/tmp` a produit `/tmp/CLAUDE.md`
    (le bloc de `projet-sans-nom-5`), que chargeait ensuite toute session
    lancée sous `/tmp`. Désormais :

    - un projet : exactement `~/work/projects/<slug>`, et seulement si le `cwd`
      de la conversation est ce dossier ;
    - l'Assistant : son dossier, ou un sous-dossier de celui-ci ;
    - rien d'autre, jamais.
    """
    if not slug or slug in (".", "..") or "/" in slug or "\\" in slug:
        return None
    try:
        ici = Path(cwd).resolve()
        if slug == settings.assistant_slug:
            racine = Path(settings.assistant_root).resolve()
            ici.relative_to(racine)
            return ici
        attendu = (Path(settings.projects_dir) / slug).resolve()
        if Path(settings.projects_dir).resolve() not in attendu.parents:
            return None
    except (OSError, ValueError):
        return None
    return attendu if ici == attendu else None


def ecrire_contexte(cwd: Path, slug: str, settings: Any = None) -> bool:
    """Pose ou met à jour le contexte du projet.

    Là où le projet l'attend : `.atelier/contexte.md` si son `CLAUDE.md`
    l'importe (structure type), sinon la section délimitée de `CLAUDE.md`.
    Rien n'est écrit hors du dossier du projet (voir `dossier_du_contexte`).

    Retourne True si un fichier a changé. Rien n'est réécrit quand le contenu
    est déjà le bon : le fichier est souvent sous git, une modification sans
    objet salirait l'état du dépôt à chaque tour.
    """
    if settings is None:
        from mcp_gateway.atelier.config import get_settings

        settings = get_settings()
    dossier = dossier_du_contexte(settings, cwd, slug)
    if dossier is None:
        log.warning("contexte de %s non écrit : %s n'est pas le dossier du projet", slug, cwd)
        return False
    bloc = bloc_contexte(slug, dossier)
    chemin = dossier / "CLAUDE.md"
    try:
        ancien = chemin.read_text(encoding="utf-8") if chemin.is_file() else ""
    except OSError as exc:
        log.info("CLAUDE.md illisible dans %s : %s", dossier, exc)
        return False

    if ancien.lstrip().startswith(IMPORT_DU_CONTEXTE):
        return _ecrire_si_change(dossier / ".atelier" / "contexte.md", bloc + "\n")

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
    return _ecrire_si_change(chemin, nouveau)


def _ecrire_si_change(chemin: Path, contenu: str) -> bool:
    try:
        if chemin.is_file() and chemin.read_text(encoding="utf-8") == contenu:
            return False
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(contenu, encoding="utf-8")
    except OSError as exc:
        log.info("%s non écrit : %s", chemin, exc)
        return False
    return True
