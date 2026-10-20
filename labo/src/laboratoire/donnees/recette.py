"""Une recette : ce qu'on fait des données brutes pour en faire une variante de jeu de données.

Faire varier la **structure** du jeu (autre regroupement des classes, autre côté, autre préparation de l'image, autre découpage) revient à changer
la recette ; son empreinte identifie la variante. Chaque étape est une fonction pure : on en voit l'effet (l'aperçu) sans écrire une seule image.

    brut → filtrer (côté, panoramiques) → étiqueter (tâche) → regrouper les classes → corrections → découper par groupe → rééquilibrer le train
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from laboratoire.donnees.brut import ImageBrute
from laboratoire.donnees.decoupage import JEUX, decouper_par_groupes
from laboratoire.empreinte import empreinte


class Decoupage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proportions: tuple[float, float, float] = (0.7, 0.15, 0.15)
    graine: int = 7

    @field_validator("proportions")
    @classmethod
    def _valides(cls, v: tuple[float, float, float]) -> tuple[float, float, float]:
        if any(p <= 0 for p in v) or abs(sum(v) - 1) > 1e-6:
            raise ValueError("trois proportions strictement positives, de somme 1")
        return v


class Reequilibrage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actif: bool = True
    # Chaque classe du train est portée, par copie, à au moins cette part de la plus grande. Jamais dans val ni test.
    rapport: float = Field(default=0.5, gt=0, le=1)


class Recette(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cote: Literal["droite", "gauche"]
    tache: Literal["nombre", "forme"]
    # nombre : N places ou plus (jusqu'à ce plafond) forment une classe. 2 donne 0, 1, « 2 et plus ». None : une classe par N.
    plafond_nombre: int | None = Field(default=2, ge=1)
    preparation: Literal["aucune", "masque", "rognage"] = "rognage"
    panoramiques: Literal["inclure", "exclure", "seulement"] = "inclure"
    decoupage: Decoupage = Field(default_factory=Decoupage)
    reequilibrage: Reequilibrage = Field(default_factory=Reequilibrage)
    corrections: bool = True
    nom: str = ""

    def empreinte(self) -> str:
        d = self.model_dump()
        d.pop("nom", None)
        return empreinte(d)


@dataclass(frozen=True)
class Etiquetee:
    image: ImageBrute
    classe: str


def etiqueter(images: list[ImageBrute], recette: Recette, corrections: dict[str, str | None] | None = None) -> tuple[list[Etiquetee], dict[str, int]]:
    """Filtre, étiquette, regroupe, corrige. Rend les images retenues et le décompte de ce qui a été écarté (et pourquoi)."""
    ecartes: dict[str, int] = defaultdict(int)
    sortie: list[Etiquetee] = []
    for i in images:
        if i.cote != recette.cote:
            continue  # l'autre côté n'est pas « écarté » : ce n'est pas le sujet de cette variante
        if recette.panoramiques == "exclure" and i.panoramique:
            ecartes["panoramique exclue"] += 1
            continue
        if recette.panoramiques == "seulement" and not i.panoramique:
            ecartes["non panoramique exclue"] += 1
            continue
        if recette.tache == "nombre":
            if i.n is None:
                ecartes["sans nombre de places"] += 1
                continue
            classe = str(min(i.n, recette.plafond_nombre) if recette.plafond_nombre else i.n)
        else:
            if i.forme is None:
                ecartes["sans forme"] += 1
                continue
            classe = i.forme
        if corrections is not None and i.chemin in corrections:
            decision = corrections[i.chemin]
            if decision is None:
                ecartes["étiquette douteuse écartée"] += 1
                continue
            classe = decision
        sortie.append(Etiquetee(i, classe))
    return sortie, dict(ecartes)


def lire_corrections(chemin: Path) -> dict[str, str | None]:
    """`corrections.csv` : chemin, decision (une classe, ou `douteuse` pour écarter l'image), note. Le brut n'est jamais modifié."""
    if not chemin.is_file():
        return {}
    sortie: dict[str, str | None] = {}
    with chemin.open(encoding="utf-8", newline="") as f:
        for ligne in csv.DictReader(f):
            decision = (ligne.get("decision") or "").strip()
            sortie[ligne["chemin"]] = None if decision in ("", "douteuse") else decision
    return sortie


@dataclass(frozen=True)
class LigneDePlan:
    etiquetee: Etiquetee
    jeu: str
    copie: int  # 0 = l'image elle-même ; k > 0 = k-ième copie de rééquilibrage (train seulement)


@dataclass
class Plan:
    lignes: list[LigneDePlan]
    ecartes: dict[str, int]
    affectation: dict[str, str]  # collection → jeu

    def classes(self) -> list[str]:
        return sorted({l.etiquetee.classe for l in self.lignes})

    def effectifs(self) -> dict[str, dict[str, int]]:
        sortie: dict[str, dict[str, int]] = {j: {} for j in JEUX}
        for l in self.lignes:
            sortie[l.jeu][l.etiquetee.classe] = sortie[l.jeu].get(l.etiquetee.classe, 0) + 1
        return sortie

    def effectifs_sans_copies(self) -> dict[str, dict[str, int]]:
        sortie: dict[str, dict[str, int]] = {j: {} for j in JEUX}
        for l in self.lignes:
            if l.copie == 0:
                sortie[l.jeu][l.etiquetee.classe] = sortie[l.jeu].get(l.etiquetee.classe, 0) + 1
        return sortie

    def groupes_par_jeu(self) -> dict[str, int]:
        return {j: len({g for g, jeu in self.affectation.items() if jeu == j}) for j in JEUX}


def planifier(images: list[ImageBrute], recette: Recette, corrections: dict[str, str | None] | None = None) -> Plan:
    """Tout ce que fera la recette, sans écrire une image : sert à l'aperçu immédiat et à la construction."""
    etiquetees, ecartes = etiqueter(images, recette, corrections if recette.corrections else None)
    comptes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e in etiquetees:
        comptes[e.image.groupe][e.classe] += 1
    affectation = decouper_par_groupes(comptes, recette.decoupage.proportions, recette.decoupage.graine)
    lignes = [LigneDePlan(e, affectation[e.image.groupe], 0) for e in sorted(etiquetees, key=lambda e: e.image.chemin)]
    if recette.reequilibrage.actif:
        lignes += _copies_de_reequilibrage(lignes, recette.reequilibrage.rapport)
    return Plan(lignes, ecartes, affectation)


def _copies_de_reequilibrage(lignes: list[LigneDePlan], rapport: float) -> list[LigneDePlan]:
    """Dans train seulement : porte chaque classe à `rapport` fois la plus grande, en recopiant ses images à tour de rôle."""
    train: dict[str, list[LigneDePlan]] = defaultdict(list)
    for l in lignes:
        if l.jeu == "train":
            train[l.etiquetee.classe].append(l)
    if not train:
        return []
    cible = int(max(len(v) for v in train.values()) * rapport)
    copies: list[LigneDePlan] = []
    for classe in sorted(train):
        originales = train[classe]
        manque = cible - len(originales)
        for k in range(manque):
            source = originales[k % len(originales)]
            copies.append(LigneDePlan(source.etiquetee, "train", k // len(originales) + 1))
    return copies
