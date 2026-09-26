"""Un seul fichier porte les valeurs secrètes ; tout le reste n'a que des références.

Les fichiers que lit Claude Code — le fichier effectif d'un tour, `~/.claude.json`,
le `.mcp.json` d'un projet — n'écrivent que `${ATELIER_MCP_…}` (ou `${VOICE_TOKEN}`
pour une variable qu'un projet demande par `.atelier/env.json`). Claude Code
développe ces références avec son environnement : mesuré sur le pod (2.1.281),
dans `--mcp-config`, dans la portée utilisateur et dans le `.mcp.json` d'un
projet. Seules quelques variables du CLI lui-même (`ANTHROPIC_API_KEY`…) ne
sont jamais développées ; nos noms n'en sont pas.

Les valeurs, elles, vivent dans `~/work/.secrets/claude-env.sh` (0600), que
l'Atelier régénère depuis leurs sources (clé de l'Atelier, base du pool, secrets
référencés par les projets). Qui lance un `claude` le charge :

- le harnais de l'Atelier, à chaque tour (les mêmes valeurs, lues à la source) ;
- code-server : `claudeCode.environmentVariables` est écrit depuis ce fichier ;
- le shell : `~/.bashrc` le source (ligne posée par `install/atelier-init.sh`) ;
- wikichat, pour les processus qu'il lance : il source ce fichier au moment de
  chaque lancement (`docs/archives/chantiers/coherence-projet.md`, « Secrets pour wikichat »).

Format : une ligne `export NOM='valeur'` par variable, en guillemets simples
(une apostrophe s'écrit `'\\''`). Lisible par `sh`, `bash`, et par
`lire_le_fichier` ci-dessous sans shell.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

log = logging.getLogger("atelier.env_secrets")

NOM_DU_FICHIER = "claude-env.sh"
_LIGNE = re.compile(r"^export ([A-Za-z_][A-Za-z0-9_]*)='(.*)'$")
_NOM = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def chemin_du_fichier(settings: Any) -> Path:
    return Path(settings.secrets_dir) / NOM_DU_FICHIER


def variables_secretes(settings: Any) -> dict[str, str]:
    """Toutes les valeurs que les références des surfaces attendent.

    Ne lève jamais : une source illisible prive seulement ses connecteurs.
    """
    valeurs: dict[str, str] = {}
    try:
        cle = Path(settings.owner_key_path).read_text(encoding="utf-8").strip()
    except OSError:
        cle = ""
    if cle:
        valeurs["ATELIER_MCP_KEY"] = cle
    from mcp_gateway.atelier.mcp_secrets import variables_du_pool

    valeurs.update(variables_du_pool(settings))
    from mcp_gateway.atelier.env_projet import variables_de_tous_les_projets

    try:
        projets = variables_de_tous_les_projets(settings.secrets_dir, settings.projects_dir)
    except OSError as exc:
        log.warning("variables des projets illisibles : %s", exc)
        projets = {}
    for nom, valeur in projets.items():
        valeurs.setdefault(nom, valeur)
    return valeurs


def _citer(valeur: str) -> str:
    return "'" + valeur.replace("'", "'\\''") + "'"


def rendu(valeurs: dict[str, str]) -> str:
    lignes = [
        "# Généré par l'Atelier (mcp_gateway/atelier/env_secrets.py) : ne pas éditer.",
        "# Valeurs des références ${…} des fichiers MCP. 0600, jamais dans un dépôt.",
    ]
    for nom in sorted(valeurs):
        valeur = valeurs[nom]
        if not _NOM.match(nom) or "\n" in valeur or "\r" in valeur:
            log.warning("variable écartée du fichier d'environnement : %s", nom)
            continue
        lignes.append(f"export {nom}={_citer(valeur)}")
    return "\n".join(lignes) + "\n"


def lire_le_fichier(chemin: Path) -> dict[str, str]:
    """Les variables du fichier, sans shell. Un fichier absent donne {}."""
    try:
        texte = chemin.read_text(encoding="utf-8")
    except OSError:
        return {}
    valeurs: dict[str, str] = {}
    for ligne in texte.splitlines():
        m = _LIGNE.match(ligne.strip())
        if m:
            valeurs[m.group(1)] = m.group(2).replace("'\\''", "'")
    return valeurs


def ecrire_le_fichier(settings: Any, valeurs: dict[str, str] | None = None) -> dict[str, str]:
    """Régénère le fichier s'il a changé ; rend les valeurs qu'il porte.

    Écrit en 0600 dès sa création (jamais un instant lisible par d'autres),
    puis remplacé d'un coup : un shell qui le source au même moment lit
    l'ancien ou le nouveau, jamais un morceau.
    """
    if valeurs is None:
        valeurs = variables_secretes(settings)
    chemin = chemin_du_fichier(settings)
    contenu = rendu(valeurs)
    try:
        if chemin.is_file() and chemin.read_text(encoding="utf-8") == contenu:
            _proteger(chemin)
            return valeurs
    except OSError:
        pass
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_name(chemin.name + ".tmp")
    try:
        temporaire.unlink(missing_ok=True)
        fd = os.open(str(temporaire), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(contenu)
        _proteger(temporaire)
        temporaire.replace(chemin)
    except OSError as exc:
        log.warning("fichier d'environnement non écrit (%s) : %s", chemin, exc)
    return valeurs


def _proteger(chemin: Path) -> None:
    try:
        chemin.chmod(0o600)
    except OSError:
        pass
