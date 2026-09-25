"""Le journal des gardiens : une ligne JSON par exécution, en ajout seul, sans secret.

`~/work/.atelier-etat/gardiens/journal/AAAA-MM.jsonl` (gardiens.md §3.5). Le
fichier n'est jamais réécrit : on l'ouvre en ajout, une ligne à la fois.

Rien n'y entre sans passer par `Filtre` : une valeur secrète connue devient
son empreinte, un motif de jeton devient « jeton masqué ». Les contrôles
n'écrivent déjà que des chemins, des noms et des nombres ; le filtre est la
seconde barrière, pas la première.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Iterable

# Mêmes motifs que la vérification de cohérence des surfaces (`coherence.py`),
# recopiés pour que ce module reste importable sans la configuration de
# l'Atelier. Le test `test_gardiens_journal` vérifie qu'ils restent alignés.
MOTIFS_DE_JETONS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"glpat-[A-Za-z0-9_-]{16,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"xox[abpr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?i)\b(?:bearer|token|basic)\s+(?!\$\{)[A-Za-z0-9._~+/=-]{16,}"),
)
LONGUEUR_MIN_SECRET = 8


def empreinte_de_valeur(valeur: str) -> str:
    """Ce qu'on peut écrire d'un secret : 12 caractères de son SHA-256."""
    return hashlib.sha256(valeur.encode("utf-8")).hexdigest()[:12]


class Filtre:
    """Retire d'un objet JSON toute valeur secrète connue et tout motif de jeton."""

    def __init__(self, valeurs: Iterable[str] = ()) -> None:
        # Les plus longues d'abord : une valeur qui en contient une autre part entière.
        self._valeurs = sorted(
            {v for v in valeurs if isinstance(v, str) and len(v) >= LONGUEUR_MIN_SECRET},
            key=len,
            reverse=True,
        )

    def texte(self, texte: str) -> str:
        for valeur in self._valeurs:
            if valeur in texte:
                texte = texte.replace(valeur, f"<secret:{empreinte_de_valeur(valeur)}>")
        for motif in MOTIFS_DE_JETONS:
            texte = motif.sub("<jeton masqué>", texte)
        return texte

    def nettoyer(self, objet: Any) -> Any:
        if isinstance(objet, str):
            return self.texte(objet)
        if isinstance(objet, dict):
            return {str(k): self.nettoyer(v) for k, v in objet.items()}
        if isinstance(objet, (list, tuple)):
            return [self.nettoyer(v) for v in objet]
        return objet


def horodatage(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


class Journal:
    """Ajout seul, un fichier par mois ; garde aussi les dernières lignes en mémoire."""

    def __init__(self, dossier: Path | None, filtre: Filtre | None = None, memoire: int = 500) -> None:
        self.dossier = dossier
        self.filtre = filtre or Filtre()
        self._recentes: deque[dict[str, Any]] = deque(maxlen=memoire)
        self._verrou = threading.Lock()

    def chemin(self, t: float) -> Path | None:
        if self.dossier is None:
            return None
        return self.dossier / (time.strftime("%Y-%m", time.gmtime(t)) + ".jsonl")

    def ecrire(self, ligne: dict[str, Any]) -> dict[str, Any]:
        t = time.time()
        propre = self.filtre.nettoyer({"quand": horodatage(t), **ligne})
        texte = json.dumps(propre, ensure_ascii=False, separators=(",", ":"))
        with self._verrou:
            self._recentes.append(propre)
            chemin = self.chemin(t)
            if chemin is not None:
                chemin.parent.mkdir(parents=True, exist_ok=True)
                with chemin.open("a", encoding="utf-8") as f:
                    f.write(texte + "\n")
        return propre

    def recentes(self, n: int = 50, controle: str | None = None) -> list[dict[str, Any]]:
        with self._verrou:
            lignes = list(self._recentes)
        if controle:
            lignes = [l for l in lignes if l.get("controle") == controle]
        return lignes[-n:]
