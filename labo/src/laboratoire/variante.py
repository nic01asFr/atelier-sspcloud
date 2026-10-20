"""Une variante de jeu de données, telle que les essais la lisent.

Le contrat (la couche données le produit, les adaptateurs le consomment) :

    <variante>/manifeste.csv        fichier,jeu,classe,groupe,source
    <variante>/<jeu>/<classe>/…     les images, rangées comme ultralytics classify les lit (train/, val/, test/)

`groupe` est la collection d'origine : elle sert à découper sans fuite et à donner un intervalle par rééchantillonnage de groupes.
On lit le manifeste, on ne devine pas les groupes en parcourant les dossiers.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

JEUX = ("train", "val", "test")
COLONNES = ("fichier", "jeu", "classe", "groupe", "source")


@dataclass(frozen=True)
class Echantillon:
    fichier: Path  # chemin absolu
    classe: str
    groupe: str
    jeu: str


class VarianteInvalide(Exception):
    pass


class Variante:
    def __init__(self, dossier: Path) -> None:
        self.dossier = Path(dossier)
        manifeste = self.dossier / "manifeste.csv"
        if not manifeste.is_file():
            raise VarianteInvalide(f"pas de manifeste.csv dans {self.dossier}")
        self._lignes: list[Echantillon] = []
        with manifeste.open(encoding="utf-8", newline="") as f:
            lecteur = csv.DictReader(f)
            manquantes = [c for c in COLONNES if c not in (lecteur.fieldnames or [])]
            if manquantes:
                raise VarianteInvalide(f"colonnes manquantes dans le manifeste : {manquantes}")
            for n, ligne in enumerate(lecteur, start=2):
                if ligne["jeu"] not in JEUX:
                    raise VarianteInvalide(f"manifeste ligne {n} : jeu « {ligne['jeu']} » (attendu : {', '.join(JEUX)})")
                chemin = (self.dossier / ligne["fichier"]).resolve()
                if self.dossier.resolve() not in chemin.parents:
                    raise VarianteInvalide(f"manifeste ligne {n} : le fichier sort de la variante ({ligne['fichier']})")
                self._lignes.append(Echantillon(chemin, ligne["classe"], ligne["groupe"], ligne["jeu"]))

    def classes(self) -> list[str]:
        return sorted({e.classe for e in self._lignes})

    def echantillons(self, jeu: str) -> list[Echantillon]:
        if jeu not in JEUX:
            raise ValueError(f"jeu inconnu : {jeu}")
        return [e for e in self._lignes if e.jeu == jeu]

    def effectifs(self) -> dict[str, dict[str, int]]:
        """jeu → classe → nombre d'images."""
        sortie: dict[str, dict[str, int]] = {j: {} for j in JEUX}
        for e in self._lignes:
            sortie[e.jeu][e.classe] = sortie[e.jeu].get(e.classe, 0) + 1
        return sortie

    def groupes(self, jeu: str) -> set[str]:
        return {e.groupe for e in self.echantillons(jeu)}
