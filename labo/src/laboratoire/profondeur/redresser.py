"""Incliner ou redresser un panorama : la caméra d'une prise n'est pas toujours horizontale.

Un modèle qui traite le panorama entier (DAP) suppose le haut en haut et l'horizon au milieu. Les modèles par vue, eux, découpent des vues à des
caps et des tangages fixes dans le repère du panorama : si le panorama est penché, toutes les vues le sont.

Convention du laboratoire (repère du panorama : x à droite, y en haut, z devant) : `tangage` > 0 = la caméra regarde vers le haut ; `roulis` > 0 =
le côté droit de la caméra monte. Un panorama pris avec une caméra inclinée de (tangage, roulis) se redresse en l'inclinant de l'inverse.
Cette convention n'est PAS vérifiée contre celle de Panoramax (champs `pers:pitch` / `pers:roll`) : à contrôler sur une prise dont on connaît l'inclinaison.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np

from laboratoire.profondeur import geometrie as g
from laboratoire.profondeur import verite


def rotation(tangage_deg: float, roulis_deg: float) -> np.ndarray:
    """Matrice R qui envoie l'axe de la caméra inclinée (0, 0, 1) vers sa direction dans le monde."""
    p, r = math.radians(tangage_deg), math.radians(roulis_deg)
    rx = np.array([[1, 0, 0], [0, math.cos(p), math.sin(p)], [0, -math.sin(p), math.cos(p)]])
    rz = np.array([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1]])
    return rz @ rx


def _directions(hauteur: int, largeur: int) -> np.ndarray:
    lon = ((np.arange(largeur) + 0.5) / largeur - 0.5) * 2 * math.pi
    lat = (0.5 - (np.arange(hauteur) + 0.5) / hauteur) * math.pi
    lo, la = np.meshgrid(lon, lat)
    return np.stack([np.cos(la) * np.sin(lo), np.sin(la), np.cos(la) * np.cos(lo)], -1)


def pivoter(carte: np.ndarray, matrice: np.ndarray, plus_proche: bool = False) -> np.ndarray:
    """Nouvelle carte telle que `nouvelle(d) = carte(matrice @ d)` pour chaque direction `d`. Bilinéaire, ou au pixel le plus proche (profondeurs, masques)."""
    d = _directions(*carte.shape[:2]) @ matrice.T
    if plus_proche:
        return verite.echantillonner_plus_proche(carte, d)
    sortie = g.echantillonner_erp(carte.astype(np.float32), d)
    return (np.rint(sortie) if np.issubdtype(carte.dtype, np.integer) else sortie).astype(carte.dtype)


def incliner(carte: np.ndarray, tangage: float, roulis: float, plus_proche: bool = False) -> np.ndarray:
    """Ce qu'une caméra inclinée de (tangage, roulis) aurait enregistré de la scène que montre `carte`."""
    return pivoter(carte, rotation(tangage, roulis), plus_proche)


def redresser(carte: np.ndarray, tangage: float, roulis: float, plus_proche: bool = False) -> np.ndarray:
    """L'inverse de `incliner` : la carte telle qu'une caméra horizontale l'aurait enregistrée."""
    return pivoter(carte, rotation(tangage, roulis).T, plus_proche)


def inclinaisons(dossier_variante: Path) -> dict[str, tuple[float, float]]:
    """(tangage, roulis) de chaque panorama d'un jeu, par nom de fichier sans extension ; une case vide vaut 0 (inclinaison inconnue)."""
    sortie: dict[str, tuple[float, float]] = {}
    with (Path(dossier_variante) / "manifeste.csv").open(encoding="utf-8", newline="") as f:
        for ligne in csv.DictReader(f):
            def val(c: str) -> float:
                try:
                    return float(ligne.get(c) or 0.0)
                except ValueError:
                    return 0.0
            sortie[Path(ligne["fichier"]).stem] = (val("tangage"), val("roulis"))
    return sortie
