"""Où vit le laboratoire d'un projet : tout sous un seul dossier du volume, donc persistant.

    <racine>/
      labo.db                      le registre des essais (SQLite)
      donnees/variantes/<id>/      une variante de jeu de données : manifeste.csv + train/ val/ test/
      essais/<id>/                 config.json, journal.log, metriques.csv, resultats.json, test_scelle.json, erreurs.json, poids/
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

_IDENTIFIANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


def identifiant_sur(valeur: str) -> str:
    """Un identifiant qui sert de nom de dossier ne sort jamais de la racine : pas de `/`, pas de `..`."""
    if not _IDENTIFIANT.match(valeur) or ".." in valeur:
        raise ValueError(f"identifiant refusé : {valeur!r}")
    return valeur


@dataclass(frozen=True)
class Racine:
    chemin: Path

    @classmethod
    def depuis_environnement(cls) -> "Racine":
        brut = os.environ.get("LABO_RACINE")
        if not brut:
            raise RuntimeError("LABO_RACINE n'est pas défini : c'est le dossier du laboratoire du projet, sur le volume")
        return cls(Path(brut))

    @property
    def base(self) -> Path:
        return self.chemin / "labo.db"

    @property
    def essais(self) -> Path:
        return self.chemin / "essais"

    @property
    def variantes(self) -> Path:
        return self.chemin / "donnees" / "variantes"

    def dossier_essai(self, ident: str) -> Path:
        return self.essais / identifiant_sur(ident)

    def dossier_variante(self, ident: str) -> Path:
        return self.variantes / identifiant_sur(ident)

    def preparer(self) -> None:
        self.essais.mkdir(parents=True, exist_ok=True)
        self.variantes.mkdir(parents=True, exist_ok=True)
