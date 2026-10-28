"""Une recette : ce qu'on fait des données brutes pour en faire une variante de jeu de données.

Faire varier la **structure** du jeu (autre regroupement des classes, autre côté, autre préparation de l'image, autre découpage) revient à changer
la recette ; son empreinte identifie la variante. Chaque étape est une fonction pure : on en voit l'effet (l'aperçu) sans écrire une seule image.

    brut → filtrer (côté, type d'image) → étiqueter (tâche) → regrouper les classes → corrections → découper par groupe → rééquilibrer le train
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
from laboratoire.validation.journal import Decision


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
    # recadrage : extrait d'une vue panoramique, déjà tourné vers son côté (la consigne dit « panoramique ») ; plate : photo vers l'avant, le côté en est une moitié (« non panoramique »).
    type_image: Literal["tous", "recadrage", "plate"] = "tous"
    decoupage: Decoupage = Field(default_factory=Decoupage)
    reequilibrage: Reequilibrage = Field(default_factory=Reequilibrage)
    corrections: bool = True
    # Comment se forment les groupes, c'est-à-dire ce qu'on n'a jamais le droit de couper entre train, val et test :
    #   route          : le dossier « ville/a/b » du brut (comportement d'origine) ;
    #   contenu        : comme `route`, mais deux dossiers qui portent la même image (mêmes octets) n'en font qu'un : la fuite cachée du 28/10 ;
    #   enregistrement : une prise de vue (collection Panoramax) entière, fusionnée en plus par le contenu ; impossible quand il y a trop peu d'enregistrements.
    regroupement: Literal["route", "contenu", "enregistrement"] = "route"
    # Une image de contenu identique n'est gardée qu'une fois ; si ses étiquettes se contredisent, elle est écartée.
    dedoublonner: bool = False
    # Côté, en pixels, de l'image carrée écrite sur disque (réduction explicite, sans recadrage). None : taille d'origine, le modèle s'en charge.
    taille: int | None = Field(default=None, ge=16, le=2048)
    nom: str = ""

    def empreinte(self) -> str:
        d = self.model_dump()
        d.pop("nom", None)
        # Les options ajoutées après coup n'ont pas d'effet à leur valeur d'origine : elles ne changent pas l'identité des variantes déjà construites.
        for cle, defaut in (("regroupement", "route"), ("dedoublonner", False), ("taille", None)):
            if d.get(cle) == defaut:
                d.pop(cle, None)
        return empreinte(d)


@dataclass(frozen=True)
class Etiquetee:
    image: ImageBrute
    classe: str


def etiqueter(
    images: list[ImageBrute], recette: Recette, corrections: dict[str, str | None] | None = None,
    validations: dict[str, Decision] | None = None,
) -> tuple[list[Etiquetee], dict[str, int]]:
    """Filtre, étiquette, regroupe, corrige. Rend les images retenues et le décompte de ce qui a été écarté (et pourquoi).

    `corrections` : le fichier `corrections.csv` (une classe pour la tâche en cours, ou écartée). `validations` : les décisions humaines
    du journal, qui portent le nombre **et** la forme ; elles passent en dernier et l'emportent.
    """
    ecartes: dict[str, int] = defaultdict(int)
    sortie: list[Etiquetee] = []
    for i in images:
        if i.cote != recette.cote:
            continue  # l'autre côté n'est pas « écarté » : ce n'est pas le sujet de cette variante
        if recette.type_image == "recadrage" and i.plate:
            ecartes["photo plate écartée"] += 1
            continue
        if recette.type_image == "plate" and not i.plate:
            ecartes["recadrage écarté"] += 1
            continue
        v = validations.get(i.chemin) if validations is not None else None
        if v is not None and v.douteuse:
            ecartes["étiquette douteuse écartée"] += 1
            continue
        if recette.tache == "nombre":
            n = v.nombre if v is not None and v.nombre is not None else i.n  # la décision humaine l'emporte sur l'étiquette d'origine
            if n is None:
                ecartes["sans nombre de places"] += 1
                continue
            classe = str(min(n, recette.plafond_nombre) if recette.plafond_nombre else n)
        else:
            forme = (v.forme if v.forme != "aucune" else None) if v is not None and v.forme is not None else i.forme
            if forme is None:
                ecartes["sans forme"] += 1
                continue
            classe = forme
        if v is None and corrections is not None and i.chemin in corrections:
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
    groupe: str = ""  # le groupe effectif (selon le regroupement de la recette), celui qui n'est jamais coupé


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


def planifier(
    images: list[ImageBrute], recette: Recette, corrections: dict[str, str | None] | None = None,
    validations: dict[str, Decision] | None = None,
) -> Plan:
    """Tout ce que fera la recette, sans écrire une image : sert à l'aperçu immédiat et à la construction."""
    etiquetees, ecartes = etiqueter(images, recette, corrections if recette.corrections else None, validations if recette.corrections else None)
    if recette.dedoublonner:
        etiquetees = _dedoublonner(etiquetees, ecartes)
    groupe_de = _groupes_effectifs(etiquetees, recette.regroupement)
    comptes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e in etiquetees:
        comptes[groupe_de[e.image.chemin]][e.classe] += 1
    affectation = decouper_par_groupes(comptes, recette.decoupage.proportions, recette.decoupage.graine)
    lignes = [LigneDePlan(e, affectation[groupe_de[e.image.chemin]], 0, groupe_de[e.image.chemin]) for e in sorted(etiquetees, key=lambda e: e.image.chemin)]
    if recette.reequilibrage.actif:
        lignes += _copies_de_reequilibrage(lignes, recette.reequilibrage.rapport)
    return Plan(lignes, ecartes, affectation)


def _dedoublonner(etiquetees: list[Etiquetee], ecartes: dict[str, int]) -> list[Etiquetee]:
    """Une seule image par contenu. Si deux exemplaires portent des étiquettes différentes, on ne sait pas laquelle croire : on les écarte tous."""
    par_contenu: dict[str, list[Etiquetee]] = defaultdict(list)
    sans_contenu: list[Etiquetee] = []
    for e in etiquetees:
        (par_contenu[e.image.contenu] if e.image.contenu else sans_contenu).append(e)
    gardees = list(sans_contenu)
    for contenu in sorted(par_contenu):
        exemplaires = sorted(par_contenu[contenu], key=lambda e: e.image.chemin)
        if len({e.classe for e in exemplaires}) > 1:
            ecartes["étiquettes contradictoires pour une même image"] = ecartes.get("étiquettes contradictoires pour une même image", 0) + len(exemplaires)
            continue
        gardees.append(exemplaires[0])
        if len(exemplaires) > 1:
            ecartes["exemplaire en double écarté"] = ecartes.get("exemplaire en double écarté", 0) + len(exemplaires) - 1
    return gardees


def _groupes_effectifs(etiquetees: list[Etiquetee], regroupement: str) -> dict[str, str]:
    """`chemin d'image → groupe effectif`, selon le regroupement. Les groupes qui partagent une image (mêmes octets) sont fusionnés, sauf pour `route`."""
    base = {e.image.chemin: (e.image.enregistrement if regroupement == "enregistrement" else e.image.groupe) for e in etiquetees}
    if regroupement == "route":
        return base
    parent: dict[str, str] = {}

    def racine(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    par_contenu: dict[str, list[str]] = defaultdict(list)
    for e in etiquetees:
        racine(base[e.image.chemin])
        if e.image.contenu:
            par_contenu[e.image.contenu].append(base[e.image.chemin])
    for groupes in par_contenu.values():
        for g in groupes[1:]:
            a, b = racine(groupes[0]), racine(g)
            if a != b:
                parent[max(a, b)] = min(a, b)  # le plus petit nom l'emporte : le résultat ne dépend pas de l'ordre des images
    return {chemin: racine(g) for chemin, g in base.items()}


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
            copies.append(LigneDePlan(source.etiquetee, "train", k // len(originales) + 1, source.groupe))
    return copies
