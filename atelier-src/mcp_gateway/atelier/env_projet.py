"""Les variables qu'un projet demande, tirées de secrets par référence.

Un projet déclare parfois dans son `.mcp.json` un serveur local qui attend
un jeton, par référence : `"Authorization": "Bearer ${VOICE_TOKEN}"`. Le CLI
développe la référence avec son environnement — mais rien ne l'y mettait, et
le serveur répondait 401.

Le projet le dit donc lui-même, sans jamais écrire la valeur : dans
`.atelier/env.json`, un nom de variable pour un nom de fichier du dossier des
secrets.

    {"VOICE_TOKEN": "voice_token"}

L'Atelier résout ces références à chaque lancement d'un tour, et les pose
dans l'environnement du CLI ; il les donne aussi à l'extension VS Code, qui ne
reçoit rien d'autre. Mêmes murs que les secrets des applications : un nom de
fichier sans séparateur ni `..`, un fichier ordinaire en 0600. Et une
variable ne peut pas en masquer une que l'Atelier pose lui-même : ni
`ATELIER_*`, ni `ANTHROPIC_*` ou `CLAUDE_*` (un projet redirigerait sinon le
modèle, ou ses réglages), ni `PATH`, `HOME` et leurs voisines.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from mcp_gateway.atelier.apps.secrets import SecretIllisible, lire_secret, reference_valide

log = logging.getLogger("atelier.env_projet")

FICHIER = Path(".atelier") / "env.json"

_VARIABLE = re.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")
PREFIXES_RESERVES = ("ATELIER_", "ANTHROPIC_", "CLAUDE_", "WIKICHAT_", "LD_", "PYTHON")
RESERVEES = frozenset(
    {"PATH", "HOME", "LANG", "SHELL", "USER", "PWD", "PORT", "VIRTUAL_ENV", "NODE_OPTIONS", "BASH_ENV", "ENV"}
)


def raison_du_refus(nom: str) -> str | None:
    if not _VARIABLE.match(nom or ""):
        return f"nom de variable invalide : {nom!r}"
    if nom in RESERVEES or nom.startswith(PREFIXES_RESERVES):
        return f"variable réservée : {nom}"
    return None


def lire_references(racine: Path) -> dict[str, str]:
    """Les références déclarées par le projet, valides seulement.

    Ne lève jamais : un fichier faux ne doit pas empêcher un tour de partir,
    il le prive seulement des variables qu'il déclarait — et le journal le dit.
    """
    chemin = racine / FICHIER
    if not chemin.is_file():
        return {}
    base = racine.resolve()
    if base not in chemin.resolve().parents:
        log.warning("%s sort du projet : ignoré", chemin)
        return {}
    try:
        donnees: Any = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        log.warning("%s illisible : %s", chemin, exc)
        return {}
    if not isinstance(donnees, dict):
        log.warning("%s : un objet {VARIABLE: référence} est attendu", chemin)
        return {}
    retenues: dict[str, str] = {}
    for nom, ref in donnees.items():
        raison = raison_du_refus(str(nom))
        if raison is None and not (isinstance(ref, str) and reference_valide(ref)):
            raison = f"référence invalide pour {nom} : {ref!r}"
        if raison:
            log.warning("%s : %s", chemin, raison)
            continue
        retenues[str(nom)] = ref
    return retenues


def variables_du_projet(secrets_dir: Path, racine: Path | None) -> dict[str, str]:
    """Les valeurs, lues dans le dossier des secrets ; un secret illisible est sauté."""
    if racine is None:
        return {}
    valeurs: dict[str, str] = {}
    for nom, ref in lire_references(racine).items():
        try:
            valeurs[nom] = lire_secret(secrets_dir, ref)
        except SecretIllisible as exc:
            log.warning("%s (%s) : %s", nom, racine.name, exc)
    return valeurs


def empreinte(valeurs: dict[str, str]) -> str:
    """Ce qui change quand une valeur change, sans rien dire des valeurs."""
    h = hashlib.sha256()
    for nom in sorted(valeurs):
        h.update(f"{nom}\0{valeurs[nom]}\0".encode("utf-8"))
    return h.hexdigest()[:16] if valeurs else ""


def variables_de_tous_les_projets(secrets_dir: Path, projects_dir: Path) -> dict[str, str]:
    """Pour VS Code, qui lance son `claude` sans savoir quel projet l'attend.

    Ses réglages sont ceux de l'utilisateur, pas d'un dossier : on y met la
    réunion des variables de tous les projets. Deux projets qui donnent au
    même nom deux secrets différents : le premier, par ordre alphabétique,
    garde le nom — et le journal le dit.
    """
    reunies: dict[str, str] = {}
    origine: dict[str, str] = {}
    if not projects_dir.is_dir():
        return reunies
    for projet in sorted(projects_dir.iterdir()):
        if not projet.is_dir() or projet.is_symlink():
            continue
        for nom, valeur in variables_du_projet(secrets_dir, projet).items():
            if nom in reunies and reunies[nom] != valeur:
                log.warning("%s déclarée par %s et %s : %s garde le nom", nom, origine[nom], projet.name, origine[nom])
                continue
            reunies.setdefault(nom, valeur)
            origine.setdefault(nom, projet.name)
    return reunies
