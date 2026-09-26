"""Une copie du Lecteur Grist (`projet-sans-nom-5`) telle que relevée sur le pod le 26/09/2026.

Relevée en lecture seule : `CLAUDE.md` et `.gitignore` à l'identique (mêmes
empreintes sha256 que sur le pod), le reste de l'arbre réduit à une partie
des fichiers suivis. `CLAUDE.md` n'est pas suivi par git, comme là-bas (D1).
Voir `fixtures/lecteur_grist/README-copie.md`.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "lecteur_grist"
EMPREINTE_CLAUDE_MD = "2689ba98b366136b98d5a894505283a3e41983d9a18bf92ab2a8adc0f107d485"
EMPREINTE_GITIGNORE = "6a46d4586ba572c5023527490b441e4d5afea2495bad05ec511b9e0ad8e798ca"


def _git(racine: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Essai",
        "GIT_AUTHOR_EMAIL": "essai@exemple.invalid",
        "GIT_COMMITTER_NAME": "Essai",
        "GIT_COMMITTER_EMAIL": "essai@exemple.invalid",
    }
    return subprocess.run(
        ["git", "-C", str(racine), *args], capture_output=True, text=True, check=True, env=env
    ).stdout.strip()


def copier_le_lecteur_grist(racine: Path) -> Path:
    """Pose la copie dans `racine` (un dépôt git sur `main`, un commit). Rend `racine`."""
    racine.mkdir(parents=True, exist_ok=True)
    for relatif in (FIXTURE / "fichiers-suivis.txt").read_text(encoding="utf-8").split():
        chemin = racine / relatif
        chemin.parent.mkdir(parents=True, exist_ok=True)
        if relatif == ".gitignore":
            chemin.write_bytes((FIXTURE / "gitignore").read_bytes())
        else:
            chemin.write_bytes(f"(copie : {relatif})\n".encode("utf-8"))
    _git(racine, "init", "-q", "-b", "main")
    _git(racine, "config", "core.autocrlf", "false")
    _git(racine, "add", "-A")
    _git(racine, "commit", "-q", "-m", "Décrire la parité des widgets entre mode fichier et mode servi, et la consigner")
    # Ce qui vit à côté, hors git : CLAUDE.md non suivi, et des fichiers ignorés.
    (racine / "CLAUDE.md").write_bytes((FIXTURE / "CLAUDE.md").read_bytes())
    for relatif in (FIXTURE / "hors-git.txt").read_text(encoding="utf-8").split():
        if relatif == "CLAUDE.md":
            continue
        chemin = racine / relatif
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_bytes(f"(copie : {relatif})\n".encode("utf-8"))
    return racine


__all__ = ["EMPREINTE_CLAUDE_MD", "EMPREINTE_GITIGNORE", "FIXTURE", "copier_le_lecteur_grist"]
