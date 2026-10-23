"""Ce qu'on peut mesurer sans profondeur de référence, et comment on classe des jugements par paires.

Aucune de ces mesures n'est une erreur de profondeur : ce sont des **cohérences**. Un modèle peut être cohérent et se tromper ; il ne peut pas être
incohérent et avoir raison partout. Elles écartent les mauvais modèles, elles ne désignent pas le meilleur : pour cela il y a le vote.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import Any

import numpy as np

from laboratoire.profondeur.geometrie import Vue, correspondances

MIN_POINTS = 400  # en deçà, un recouvrement ne dit rien
MAX_POINTS = 20000  # sous-échantillon (déterministe) : la corrélation n'a pas besoin de plus


def ajustement_affine(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """(r, a, b) : corrélation de Pearson et droite y ≈ a·x + b. Rend (nan, nan, nan) si l'un des deux est constant ou trop court."""
    if x.size < MIN_POINTS:
        return math.nan, math.nan, math.nan
    if x.size > MAX_POINTS:
        pas = x.size // MAX_POINTS + 1
        x, y = x[::pas], y[::pas]
    sx, sy = x.std(), y.std()
    if sx < 1e-12 or sy < 1e-12:
        return math.nan, math.nan, math.nan
    r = float(np.corrcoef(x, y)[0, 1])
    a = r * sy / sx
    return r, float(a), float(y.mean() - a * x.mean())


def incoherence(r: float) -> float:
    """Part de la variation que la droite n'explique pas : √(1 − r²), de 0 (cohérent) à 1 (sans rapport)."""
    return math.sqrt(max(0.0, 1.0 - r * r)) if math.isfinite(r) else math.nan


def _mediane(valeurs: list[float]) -> float:
    v = [x for x in valeurs if math.isfinite(x)]
    return float(np.median(v)) if v else math.nan


def _moyenne(valeurs: list[float]) -> float:
    v = [x for x in valeurs if math.isfinite(x)]
    return float(np.mean(v)) if v else math.nan


def coherence_recouvrement(q: np.ndarray, masque: np.ndarray, vues: list[Vue], metrique: bool = False) -> dict[str, Any]:
    """Un panorama, un modèle : les vues qui se recouvrent racontent-elles la même scène ?

    `q` (n_vues, h, w) : inverses de distance radiale (voir `geometrie`) ; `masque` : pixels que le modèle juge valides (pas le ciel).
    Pour chaque paire de vues qui se recouvrent, on ajuste une droite entre leurs `q` sur les points communs ; l'incohérence est la part non expliquée.
    Pour un modèle métrique, la pente doit valoir 1 (même échelle d'une vue à l'autre) : `derive_echelle` = |ln pente| médiane.
    """
    incoh, derives, paires = [], [], 0
    for i, j in combinations(range(len(vues)), 2):
        x, y = correspondances(vues[i], vues[j], q[i], q[j], masque[i], masque[j])
        r, a, _ = ajustement_affine(x, y)
        if not math.isfinite(r):
            continue
        paires += 1
        incoh.append(incoherence(r))
        if metrique and a > 0:
            derives.append(abs(math.log(a)))
    return {"incoherence": _mediane(incoh), "paires": paires, "derive_echelle": _mediane(derives) if metrique else None}


def flou(q: np.ndarray, sigma: float = 6.0) -> np.ndarray:
    """Flou gaussien séparable (les cartes gardées sont petites : la convolution directe suffit)."""
    r = max(1, int(3 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    horizontal = (np.lib.stride_tricks.sliding_window_view(np.pad(q, ((0, 0), (r, r)), mode="reflect"), 2 * r + 1, axis=1) * k).sum(axis=-1)
    return (np.lib.stride_tricks.sliding_window_view(np.pad(horizontal, ((r, r), (0, 0)), mode="reflect"), 2 * r + 1, axis=0) * k).sum(axis=-1)


def accord(q_a: np.ndarray, m_a: np.ndarray, q_b: np.ndarray, m_b: np.ndarray, detail: bool = True, sigma: float = 6.0) -> float:
    """Deux modèles, un panorama : corrélation médiane, vue par vue, de leurs `q` sur les pixels que les deux jugent valides (1 : même relief).

    Une corrélation « globale » est presque toujours proche de 1 : toute scène a un sol proche en bas et un fond loin en haut, et tout modèle le sait.
    Avec `detail` (par défaut) on retire d'abord le flou de chaque carte : il reste les marches, les bords, les objets — ce sur quoi les modèles
    peuvent vraiment différer.
    """
    rs = []
    for i in range(q_a.shape[0]):
        a, b = q_a[i].astype(np.float64), q_b[i].astype(np.float64)
        if detail:
            a, b = a - flou(a, sigma), b - flou(b, sigma)
        ok = m_a[i] & m_b[i] & np.isfinite(a) & np.isfinite(b)
        r, _, _ = ajustement_affine(a[ok], b[ok])
        rs.append(r)
    return _mediane(rs)


# -- classement par paires -------------------------------------------------


@dataclass(frozen=True)
class Jugement:
    gagnant: str | None  # None : égalité
    perdant: str | None
    a: str
    b: str
    groupe: str = ""  # le panorama : on rééchantillonne par groupes pour l'intervalle


def bradley_terry(modeles: list[str], jugements: list[Jugement], iterations: int = 500) -> dict[str, float]:
    """Force de chaque modèle (logarithme, centrée sur 0) d'après des jugements par paires ; une égalité compte une demi-victoire de chacun.

    Algorithme de Hunter (MM). Un petit a priori (une demi-victoire fictive contre chaque autre) garde les forces finies quand un modèle n'a jamais perdu.
    """
    idx = {m: k for k, m in enumerate(modeles)}
    n = len(modeles)
    gains = np.full((n, n), 0.0)
    for j in jugements:
        if j.a not in idx or j.b not in idx or j.a == j.b:
            continue
        ia, ib = idx[j.a], idx[j.b]
        if j.gagnant is None:
            gains[ia, ib] += 0.5
            gains[ib, ia] += 0.5
        else:
            perdant = j.perdant or (j.b if j.gagnant == j.a else j.a)
            gains[idx[j.gagnant], idx[perdant]] += 1.0
    gains += 0.5 * (1 - np.eye(n))
    force = np.ones(n)
    for _ in range(iterations):
        nouveau = np.empty(n)
        for i in range(n):
            denom = sum((gains[i, k] + gains[k, i]) / (force[i] + force[k]) for k in range(n) if k != i)
            nouveau[i] = gains[i].sum() / denom
        nouveau /= np.exp(np.mean(np.log(nouveau)))
        if np.max(np.abs(np.log(nouveau) - np.log(force))) < 1e-9:
            force = nouveau
            break
        force = nouveau
    return {m: float(math.log(force[idx[m]])) for m in modeles}


def classement(modeles: list[str], jugements: list[Jugement], tirages: int = 300, graine: int = 0) -> dict[str, Any]:
    """Forces, rangs et intervalle à 90 % obtenu en rééchantillonnant des **panoramas** (les votes d'un même panorama ne sont pas indépendants)."""
    forces = bradley_terry(modeles, jugements)
    groupes: dict[str, list[Jugement]] = {}
    for j in jugements:
        groupes.setdefault(j.groupe, []).append(j)
    cles = sorted(groupes)
    rng = np.random.default_rng(graine)
    echantillons: dict[str, list[float]] = {m: [] for m in modeles}
    if len(cles) >= 3:
        for _ in range(tirages):
            tirage = [j for c in rng.choice(cles, size=len(cles), replace=True) for j in groupes[c]]
            f = bradley_terry(modeles, tirage, iterations=200)
            for m in modeles:
                echantillons[m].append(f[m])
    sortie = {}
    for m in modeles:
        e = echantillons[m]
        sortie[m] = {
            "force": forces[m],
            "intervalle": [float(np.percentile(e, 5)), float(np.percentile(e, 95))] if e else None,
            "victoires": sum(1 for j in jugements if j.gagnant == m),
            "defaites": sum(1 for j in jugements if j.perdant == m),
            "egalites": sum(1 for j in jugements if j.gagnant is None and m in (j.a, j.b)),
        }
    ordre = sorted(modeles, key=lambda m: -forces[m])
    for rang, m in enumerate(ordre, start=1):
        sortie[m]["rang"] = rang
    return {"modeles": sortie, "jugements": len(jugements), "panoramas": len(cles), "fiable": len(cles) >= 10 and len(jugements) >= 30}
