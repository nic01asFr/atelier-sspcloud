"""Lire un secret désigné par référence : un nom de fichier, jamais une valeur.

Partagé par les applications (`secrets` d'un manifeste, sous
`~/work/.secrets/apps/`) et par l'environnement des projets
(`.atelier/env.json`, sous `~/work/.secrets/`). Les mêmes murs dans les deux
cas : la référence est un nom sans séparateur ni `..`, le fichier est
ordinaire (pas un lien, qui mènerait ailleurs) et fermé aux autres (0600).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Une référence est un nom de fichier du dossier des secrets, rien de plus.
FORME_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class SecretIllisible(ValueError):
    """Le secret n'existe pas, ou pas sous une forme qu'on accepte de lire."""


def reference_valide(ref: str) -> bool:
    return bool(FORME_REFERENCE.match(ref or "")) and ".." not in ref


def lire_secret(dossier: Path, ref: str) -> str:
    """La valeur du secret `ref` rangé dans `dossier`, fin de ligne retirée."""
    if not reference_valide(ref):
        raise SecretIllisible(f"référence de secret invalide : {ref!r}")
    chemin = dossier / ref
    try:
        infos = chemin.lstat()
    except FileNotFoundError:
        raise SecretIllisible(f"secret manquant : {ref} (attendu dans {dossier})") from None
    if chemin.is_symlink() or not chemin.is_file():
        raise SecretIllisible(f"secret {ref} : pas un fichier ordinaire")
    if os.name == "posix" and infos.st_mode & 0o077:
        raise SecretIllisible(f"secret {ref} lisible par d'autres : chmod 600 attendu")
    return chemin.read_text(encoding="utf-8").rstrip("\r\n")
