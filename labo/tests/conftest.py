"""Des jeux de données minuscules, fabriqués pour les tests : deux classes que le jouet sépare (images claires / sombres)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from PIL import Image

from laboratoire.modeles import ConfigEssai, Methode
from laboratoire.projet import Racine
from laboratoire.registre import Registre

NIVEAUX = {"clair": 220, "sombre": 30, "moyen": 125}


def faire_variante(
    racine: Racine,
    ident: str = "v1",
    plan: dict[str, dict[str, list[tuple[str, int]]]] | None = None,
) -> Path:
    """`plan[jeu][classe]` = liste de (groupe, nombre d'images). Par défaut : 3 collections en train, 1 en val, 1 en test, 2 classes."""
    plan = plan or {
        "train": {"clair": [("c1", 6), ("c2", 6)], "sombre": [("c1", 6), ("c2", 6)]},
        "val": {"clair": [("c3", 4)], "sombre": [("c3", 4)]},
        "test": {"clair": [("c4", 4)], "sombre": [("c4", 4)]},
    }
    dossier = racine.dossier_variante(ident)
    lignes = []
    for jeu, classes in plan.items():
        for classe, groupes in classes.items():
            (dossier / jeu / classe).mkdir(parents=True, exist_ok=True)
            for groupe, n in groupes:
                for i in range(n):
                    nom = f"{jeu}/{classe}/{groupe}__{i:03d}.png"
                    niveau = NIVEAUX.get(classe, 125) + (i % 5)
                    Image.new("RGB", (24, 24), (niveau, niveau, niveau)).save(dossier / nom)
                    lignes.append({"fichier": nom, "jeu": jeu, "classe": classe, "groupe": groupe, "source": f"brut/{groupe}/{i}.png"})
    with (dossier / "manifeste.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["fichier", "jeu", "classe", "groupe", "source"])
        w.writeheader()
        w.writerows(lignes)
    return dossier


@pytest.fixture()
def racine(tmp_path: Path) -> Racine:
    r = Racine(tmp_path / "labo")
    r.preparer()
    return r


@pytest.fixture()
def registre(racine: Racine) -> Registre:
    return Registre(racine.base)


def config_jouet(jeu: str = "v1", **reglages) -> ConfigEssai:
    return ConfigEssai(jeu=jeu, methode=Methode(famille="jouet", modele="centres", imgsz=8, epochs=1, reglages=reglages))
