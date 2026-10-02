"""Ce qu'un agent qui en a lancé un autre peut autoriser à sa place.

Un lancement *supervisé* pose ses demandes d'autorisation au lieu de les
refuser en silence ; c'est le lanceur — un agent, pas la personne — qui répond
par `atelier_decider`. Il ne répond pas à tout : ce module trace la frontière,
et c'est l'Atelier qui l'applique, pas une consigne.

Dans le périmètre (le lanceur peut accepter) : lire et écrire **dans le dossier
du projet**, et lancer des commandes locales courantes sur ses fichiers.
Hors périmètre (reste à la personne) : tout ce qui sort du projet, touche aux
clés (`.secrets`), au dépôt (`.git`), au réseau, aux envois (`git push`), aux
suppressions récursives, ou passe par un autre outil (Onyxia, wikichat, web).

Limite connue : un script du projet lancé par `python` ou `node` fait ce que son
code fait ; le périmètre le traite comme local, car l'agent l'écrit lui-même
avec les droits d'édition qu'on lui laisse. Installer des dépendances
(`pip`, `npm`, `uv`) sort du local : cela remonte à la personne.

La frontière est volontairement étroite : dans le doute, la demande reste posée
et la personne la voit dans l'Atelier. Refuser à tort coûte un clic ; accepter à
tort ne se rattrape pas.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

from mcp_gateway.atelier.decisions import Demande, chemins_vises

OUTILS_DE_LECTURE = frozenset({"Read", "Glob", "Grep", "LS", "NotebookRead"})
OUTILS_D_ECRITURE = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})

# Commandes locales courantes ; tout autre programme remonte à la personne.
PROGRAMMES_LOCAUX = frozenset(
    {
        "ls", "cat", "head", "tail", "wc", "grep", "rg", "find", "sort", "uniq", "diff", "tree",
        "echo", "printf", "pwd", "true", "false", "test", "which", "stat", "file", "du",
        "mkdir", "touch", "cp", "mv", "sed", "awk", "cut", "tr", "jq",
        "python", "python3", "node", "pytest", "ruff", "tsc",
        "git",
    }
)
# `git` : lire et préparer un commit, jamais envoyer ni réécrire.
SOUS_COMMANDES_GIT = frozenset(
    {"status", "diff", "log", "show", "branch", "add", "commit", "restore", "stash", "rev-parse", "ls-files", "blame"}
)
# Ce qui sort du local, quel que soit le programme.
MOTIFS_INTERDITS = re.compile(
    r"(?:^|[\s/='\"])\.secrets(?:[/\s'\"]|$)"
    r"|(?:^|[\s/='\"])\.git(?:/|[\s'\"]|$)"
    r"|\b(?:curl|wget|ssh|scp|rsync|nc|ncat|sudo|su|kubectl|helm|docker|chmod|chown|kill|pkill|killall)\b"
    r"|\bgit\s+(?:push|reset|clean|checkout|rebase|remote|config|filter)\b"
    r"|\brm\s+-\w*[rf]"
    r"|\b(?:pip3?|npm|npx|yarn|pnpm|uv|apt|apt-get)\b"
    r"|\bpython3?\s+-m\s+(?:pip|venv|ensurepip)\b"
)
_REDIRECTION_DE_FLUX = re.compile(r"\d*>&\d+|&>>?\s*\S+")
_SEPARATEURS = re.compile(r"\|\||&&|[;|&\n]|\$\(|`|\)")


def _dedans(chemin: str, racine: Path) -> bool:
    """Le chemin, résolu, est dans le projet (et pas dans un dossier réservé)."""
    if not chemin or "\x00" in chemin:
        return False
    brut = os.path.expanduser(chemin)
    candidat = Path(brut) if os.path.isabs(brut) else racine / brut
    try:
        reel = candidat.resolve()
        base = racine.resolve()
    except OSError:
        return False
    if reel != base and base not in reel.parents:
        return False
    relatif = reel.relative_to(base).parts
    return not (relatif and relatif[0] in {".secrets", ".git"})


def _commande_locale(commande: str, racine: Path) -> str | None:
    """None si la commande est locale ; sinon, pourquoi elle remonte à la personne."""
    if MOTIFS_INTERDITS.search(commande):
        return "sort du local (réseau, clés, dépôt, envoi, suppression récursive)"
    for morceau in _SEPARATEURS.split(_REDIRECTION_DE_FLUX.sub(" ", commande)):
        morceau = morceau.strip()
        if not morceau:
            continue
        try:
            mots = shlex.split(morceau)
        except ValueError:
            return "commande illisible"
        while mots and "=" in mots[0] and not mots[0].startswith(("-", "/", ".")):
            mots = mots[1:]  # VAR=valeur devant la commande
        if not mots:
            continue
        programme = os.path.basename(mots[0])
        if programme not in PROGRAMMES_LOCAUX:
            return f"programme hors de la liste locale : {programme}"
        if programme == "git":
            sous = next((m for m in mots[1:] if not m.startswith("-")), "")
            if sous not in SOUS_COMMANDES_GIT:
                return f"git {sous or '?'} n'est pas une commande locale de lecture ou de commit"
        for mot in mots[1:]:
            if mot.startswith("-"):
                continue
            if mot.startswith(("/", "~", "..")) and not _dedans(mot, racine):
                return f"chemin hors du projet : {mot}"
    return None


def hors_perimetre(demande: Demande, racine: Path) -> str | None:
    """None si le lanceur peut autoriser cette demande ; sinon la raison, en une phrase.

    Une question posée à la personne (`AskUserQuestion`) n'est jamais au
    lanceur : elle lui est adressée.
    """
    if demande.genre == "question":
        return "c'est une question pour la personne"
    outil = demande.outil
    chemins = chemins_vises(demande)
    if outil in OUTILS_DE_LECTURE or outil in OUTILS_D_ECRITURE:
        for chemin in chemins:
            if not _dedans(chemin, racine):
                return f"chemin hors du projet ou réservé : {chemin}"
        return None
    if outil == "Bash":
        commande = str(demande.arguments.get("command") or "")
        if not commande.strip():
            return "commande vide"
        return _commande_locale(commande, racine)
    return f"l'outil {outil} n'est pas du périmètre du lanceur"


def resume_de_la_demande(demande: Demande) -> str:
    """Une ligne qui dit ce que l'agent veut faire, pour la liste du lanceur."""
    if demande.outil == "Bash":
        return "Bash : " + str(demande.arguments.get("command") or "")[:200]
    chemins = chemins_vises(demande)
    return f"{demande.outil}" + (f" : {chemins[0]}" if chemins else "")
