"""La profondeur de référence d'un jeu synthétique : ce que la maquette 3D sait exactement, et comment on mesure l'erreur d'un modèle contre elle.

Un jeu dont les panoramas sont des rendus de maquette porte, à côté de chaque image, `verite/<panorama>.npz` :
`profondeur` (mètres, distance le long du rayon, 0 = pas d'impact), `ciel`, `hors_emprise` (la maquette s'arrête là : rien à comparer) et `couche`.
La référence est exacte pour l'image rendue : il n'y a ni photo, ni pose à recaler.

Elle se compare dans la même grandeur que les cartes des modèles, `q` = inverse de la distance radiale (voir `geometrie`). Les modèles relatifs ne
donnent la profondeur qu'à une transformation affine près : l'erreur se mesure donc **après** ajustement d'une droite par vue. Les modèles métriques sont
mesurés aussi sans ajustement : leur échelle fait partie de ce qu'on leur demande.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from laboratoire.profondeur.mesures import MIN_POINTS, ajustement_affine

PORTEE_MAX_M = 100.0  # au-delà, q est minuscule et le moindre écart de maquette pèse lourd : on ne juge pas
SEUIL_DELTA = 1.25  # un pixel est « juste » si la distance prédite est à moins de 25 % de la vérité (usage courant en profondeur monoculaire)
Q_PLANCHER = 1.0 / 500.0  # une droite ajustée peut rendre un q ≤ 0 : on le ramène à une distance très grande, pas à une division par zéro


def chemin_verite(panorama: Path) -> Path:
    """`<jeu>/val/panorama/<id>.png` → `<jeu>/val/verite/<id>.npz`."""
    return panorama.parent.parent / "verite" / f"{panorama.stem}.npz"


def charger(chemin: Path) -> tuple[np.ndarray, np.ndarray]:
    """(q, valide) en panorama : q = 1 / distance là où la référence est exacte et à portée, 0 ailleurs ; valide : bool."""
    with np.load(chemin) as f:
        d = f["profondeur"].astype(np.float32)
        ciel, hors = f["ciel"], f["hors_emprise"]
    valide = (d > 0) & (d <= PORTEE_MAX_M) & ~ciel & ~hors
    q = np.where(valide, 1.0 / np.maximum(d, 1e-6), 0.0).astype(np.float32)
    return q, valide


def echantillonner_plus_proche(carte: np.ndarray, rayons: np.ndarray) -> np.ndarray:
    """Lit un panorama (H, W) selon des rayons (h, w, 3), au pixel le plus proche : une référence ne se mélange pas à ses bords."""
    he, we = carte.shape[:2]
    lon = np.arctan2(rayons[..., 0], rayons[..., 2])
    lat = np.arcsin(np.clip(rayons[..., 1], -1, 1))
    x = np.rint((lon / (2 * math.pi) + 0.5) * we - 0.5).astype(int) % we
    y = np.clip(np.rint((0.5 - lat / math.pi) * he - 0.5).astype(int), 0, he - 1)
    return carte[y, x]


def eroder(masque: np.ndarray, pixels: int = 2) -> np.ndarray:
    """Retire `pixels` pixels au bord du masque : les cartes gardées sont réduites par moyenne avec le fond, leurs bords ne valent rien."""
    m = masque.copy()
    for _ in range(pixels):
        n = m.copy()
        n[1:] &= m[:-1]
        n[:-1] &= m[1:]
        n[:, 1:] &= m[:, :-1]
        n[:, :-1] &= m[:, 1:]
        m = n
    return m


def erreurs_vue(q_modele: np.ndarray, masque_modele: np.ndarray, q_ref: np.ndarray, valide: np.ndarray, metrique: bool) -> dict[str, float] | None:
    """Erreurs d'un modèle sur une vue, ou None si trop peu de pixels sont comparables.

    - `r_q` : corrélation entre `q` du modèle et `q` de la référence (1 : même relief, indépendamment de l'échelle) ;
    - `absrel`, `delta1` : après ajustement affine de `q`, erreur relative moyenne sur la distance, et part des pixels à moins de 25 % ;
    - pour un modèle métrique : `absrel_brut` et `ln_echelle` (|ln| du rapport médian distance prédite / vraie ; 0 : échelle juste), sans ajustement.
    """
    ok = masque_modele & valide & np.isfinite(q_modele) & (q_ref > 0)
    if int(ok.sum()) < MIN_POINTS:
        return None
    x, y = q_modele[ok].astype(np.float64), q_ref[ok].astype(np.float64)
    r, a, b = ajustement_affine(x, y)
    if not math.isfinite(r):
        return None
    d_ref = 1.0 / y
    d_aj = 1.0 / np.maximum(a * x + b, Q_PLANCHER)
    rapport = np.maximum(d_aj / d_ref, d_ref / d_aj)
    sortie: dict[str, float] = {"r_q": r, "absrel": float(np.mean(np.abs(d_aj - d_ref) / d_ref)), "delta1": float(np.mean(rapport < SEUIL_DELTA)), "pixels": float(ok.sum())}
    if metrique:
        d_mod = 1.0 / np.maximum(x, Q_PLANCHER)
        sortie["absrel_brut"] = float(np.mean(np.abs(d_mod - d_ref) / d_ref))
        sortie["ln_echelle"] = abs(math.log(max(float(np.median(d_mod / d_ref)), 1e-9)))
    return sortie


def _mediane(valeurs: list[float]) -> float | None:
    v = [x for x in valeurs if math.isfinite(x)]
    return float(np.median(v)) if v else None


def resume_panorama(par_vue: list[dict[str, float] | None]) -> dict[str, Any]:
    """Médiane, sur les vues d'un panorama, de chaque erreur ; `vues_jugees` dit combien de vues avaient assez de pixels comparables."""
    vues = [v for v in par_vue if v]
    cles = ("r_q", "absrel", "delta1", "absrel_brut", "ln_echelle")
    return {"vues_jugees": len(vues), **{k: _mediane([v[k] for v in vues if k in v]) for k in cles}}


def resume_jeu(par_panorama: list[dict[str, Any]]) -> dict[str, Any]:
    """Médiane, sur les panoramas, des médianes par vue : les clés du rapport de l'essai (`absrel_mediane`, `delta1_mediane`…)."""
    avec = [p for p in par_panorama if p.get("vues_jugees")]
    noms = {"r_q": "r_q_mediane", "absrel": "absrel_mediane", "delta1": "delta1_mediane", "absrel_brut": "absrel_brut_mediane", "ln_echelle": "ecart_echelle_mediane"}
    sortie: dict[str, Any] = {"panoramas_avec_verite": len(avec)}
    for cle, nom in noms.items():
        m = _mediane([p[cle] for p in avec if p.get(cle) is not None])
        sortie[nom] = None if m is None else round(m, 4)
    return sortie
