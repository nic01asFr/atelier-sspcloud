"""Les contrôles d'une variante : ce qui rendrait ses mesures trompeuses, dit avant qu'on lance le moindre essai.

Chaque contrôle rend un constat `{code, gravite, message, ...}` ; `bloquant` = les mesures n'ont pas de sens, `avertissement` = à savoir.
Les mêmes contrôles servent à l'aperçu d'une recette (sans image écrite) et à la variante construite.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from laboratoire.evaluation import SEUIL_FIABLE

JEUX = ("train", "val", "test")
DESEQUILIBRE_MAX = 10.0  # plus grande classe / plus petite classe, dans un même jeu


@dataclass(frozen=True)
class Ligne:
    jeu: str
    classe: str
    groupe: str
    source: str
    copie: bool = False  # copie de rééquilibrage (train seulement)


def controler(lignes: Iterable[Ligne], classes_attendues: list[str] | None = None) -> list[dict]:
    lignes = list(lignes)
    constats: list[dict] = []

    def ajouter(code: str, gravite: str, message: str, **plus) -> None:
        constats.append({"code": code, "gravite": gravite, "message": message, **plus})

    par_jeu = {j: [l for l in lignes if l.jeu == j] for j in JEUX}
    for j in JEUX:
        if not par_jeu[j]:
            ajouter("jeu_vide", "bloquant", f"Le jeu « {j} » est vide.", jeu=j)

    # Fuite : une collection (ou une image) présente dans deux jeux gonfle les chiffres de val/test.
    jeux_du_groupe: dict[str, set[str]] = defaultdict(set)
    jeux_de_la_source: dict[str, set[str]] = defaultdict(set)
    for l in lignes:
        jeux_du_groupe[l.groupe].add(l.jeu)
        jeux_de_la_source[l.source].add(l.jeu)
    fuites = sorted(g for g, js in jeux_du_groupe.items() if len(js) > 1)
    if fuites:
        ajouter("fuite_groupe", "bloquant", f"{len(fuites)} collection(s) se retrouvent dans plusieurs jeux : les mesures seraient trop belles.", groupes=fuites[:20])
    fuites_img = sorted(s for s, js in jeux_de_la_source.items() if len(js) > 1)
    if fuites_img:
        ajouter("fuite_image", "bloquant", f"{len(fuites_img)} image(s) se retrouvent dans plusieurs jeux.", images=fuites_img[:20])

    toutes = sorted(classes_attendues or {l.classe for l in lignes})
    for j in JEUX:
        if not par_jeu[j]:
            continue
        presentes = {l.classe for l in par_jeu[j]}
        absentes = [c for c in toutes if c not in presentes]
        if absentes:
            gravite = "bloquant" if j == "train" else "avertissement"
            ajouter("classe_absente", gravite, f"Classe(s) {', '.join(absentes)} absente(s) du jeu « {j} ».", jeu=j, classes=absentes)

    # Les classes rares : en val/test, un rappel calculé sur moins de SEUIL_FIABLE images est un chiffre fragile.
    for j in ("val", "test"):
        compte = defaultdict(int)
        for l in par_jeu[j]:
            compte[l.classe] += 1
        rares = sorted(c for c, n in compte.items() if n < SEUIL_FIABLE)
        if rares:
            ajouter("classe_rare", "avertissement", f"Dans « {j} », moins de {SEUIL_FIABLE} images pour : {', '.join(rares)} — leur rappel sera marqué non fiable.", jeu=j, classes=rares)

    for j in JEUX:
        compte = defaultdict(int)
        for l in par_jeu[j]:
            if not l.copie:
                compte[l.classe] += 1
        if len(compte) >= 2 and min(compte.values()) > 0 and max(compte.values()) / min(compte.values()) > DESEQUILIBRE_MAX:
            ajouter("desequilibre", "avertissement", f"Dans « {j} », la plus grande classe a plus de {int(DESEQUILIBRE_MAX)} fois les images de la plus petite.", jeu=j)

    # Doublons : la même image source deux fois dans un jeu, hors copies de rééquilibrage voulues.
    vus: dict[tuple[str, str], int] = defaultdict(int)
    for l in lignes:
        if not l.copie:
            vus[(l.jeu, l.source)] += 1
    doublons = sorted({s for (_, s), n in vus.items() if n > 1})
    if doublons:
        ajouter("doublon", "avertissement", f"{len(doublons)} image(s) apparaissent plusieurs fois dans un même jeu.", images=doublons[:20])

    copies_hors_train = [l for l in lignes if l.copie and l.jeu != "train"]
    if copies_hors_train:
        ajouter("copie_hors_train", "bloquant", "Des copies de rééquilibrage sont en dehors du train.")
    return constats


def fichiers_manquants(dossier: Path, fichiers: Iterable[str]) -> list[str]:
    return [f for f in fichiers if not (dossier / f).is_file()]


def bloquants(constats: list[dict]) -> list[dict]:
    return [c for c in constats if c["gravite"] == "bloquant"]
