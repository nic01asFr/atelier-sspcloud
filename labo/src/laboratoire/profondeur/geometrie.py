"""Géométrie des panoramas équirectangulaires (ERP) et des vues en perspective qu'on en tire.

Convention (celle des essais déjà faits sur le projet) : une vue a un cap (rotation autour de la verticale, en degrés, 0 = centre du panorama,
positif vers la droite) et un tangage (positif vers le haut), un champ de vue horizontal `fov`. Pixel (x, y) → rayon (x, −y, f) normalisé dans le
repère de la caméra (z vers l'avant), puis tourné par `Ry(cap) · Rx(tangage)` dans le repère du panorama.

Les cartes de profondeur ne se comparent pas toutes telles quelles : un modèle rend une profondeur le long de l'axe (z), un autre une disparité.
On les ramène toutes à `q` = **inverse de la distance au centre de prise de vue** (distance radiale), à une transformation affine près
(échelle et décalage inconnus pour les modèles relatifs) : `q = cos(angle à l'axe) / z` pour une profondeur z, `q = cos(angle) · disparité` pour une
disparité. Deux vues qui se recouvrent voient le même point à la même distance radiale : leurs `q` sont donc comparables point à point.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Vue:
    cap: float
    tangage: float
    fov: float = 90.0

    @property
    def nom(self) -> str:
        return f"c{int(round(self.cap)) % 360:03d}_t{int(round(self.tangage)):02d}"


def grille_de_vues(fov: float = 90.0, pas_cap: float = 45.0, tangage_haut: float = 15.0) -> list[Vue]:
    """Les vues d'un panorama : un tour d'horizon par pas de `pas_cap`, et une seconde rangée inclinée (0 : pas de seconde rangée)."""
    if not 20 <= fov <= 140:
        raise ValueError("fov : entre 20 et 140 degrés")
    if not 5 <= pas_cap <= 180:
        raise ValueError("pas_cap : entre 5 et 180 degrés")
    caps = [i * pas_cap for i in range(int(round(360 / pas_cap)))]
    tangages = [0.0] + ([float(tangage_haut)] if tangage_haut else [])
    return [Vue(c, t, fov) for t in tangages for c in caps]


def _focale(largeur: int, fov: float) -> float:
    return (largeur / 2) / math.tan(math.radians(fov / 2))


def _rotation(cap: float, tangage: float) -> np.ndarray:
    t, c = math.radians(tangage), math.radians(cap)
    rx = np.array([[1, 0, 0], [0, math.cos(t), math.sin(t)], [0, -math.sin(t), math.cos(t)]])
    ry = np.array([[math.cos(c), 0, math.sin(c)], [0, 1, 0], [-math.sin(c), 0, math.cos(c)]])
    return ry @ rx


def rayons_camera(largeur: int, hauteur: int, fov: float) -> np.ndarray:
    """Rayons unitaires de chaque pixel, dans le repère de la caméra : (hauteur, largeur, 3)."""
    f = _focale(largeur, fov)
    x, y = np.meshgrid(np.arange(largeur) - largeur / 2 + 0.5, np.arange(hauteur) - hauteur / 2 + 0.5)
    d = np.stack([x, -y, np.full_like(x, f)], -1)
    return d / np.linalg.norm(d, axis=-1, keepdims=True)


def cos_axe(largeur: int, hauteur: int, fov: float) -> np.ndarray:
    """Cosinus de l'angle entre chaque rayon et l'axe optique (pour passer de la profondeur z à la distance radiale)."""
    return rayons_camera(largeur, hauteur, fov)[..., 2]


def rayons_monde(vue: Vue, largeur: int, hauteur: int) -> np.ndarray:
    return rayons_camera(largeur, hauteur, vue.fov) @ _rotation(vue.cap, vue.tangage).T


def echantillonner_erp(erp: np.ndarray, rayons: np.ndarray) -> np.ndarray:
    """Lit le panorama `erp` (H, W[, C]) selon des rayons (h, w, 3) du repère du monde : interpolation bilinéaire, bouclée en longitude."""
    he, we = erp.shape[:2]
    lon = np.arctan2(rayons[..., 0], rayons[..., 2])
    lat = np.arcsin(np.clip(rayons[..., 1], -1, 1))
    x = (lon / (2 * math.pi) + 0.5) * we - 0.5
    y = np.clip((0.5 - lat / math.pi) * he - 0.5, 0, he - 1)
    x0 = np.floor(x).astype(int)
    y0 = np.floor(y).astype(int)
    fx, fy = x - x0, y - y0
    x0m, x1m = x0 % we, (x0 + 1) % we
    y1 = np.minimum(y0 + 1, he - 1)
    if erp.ndim == 3:
        fx, fy = fx[..., None], fy[..., None]
    a = erp[y0, x0m] * (1 - fx) + erp[y0, x1m] * fx
    b = erp[y1, x0m] * (1 - fx) + erp[y1, x1m] * fx
    return a * (1 - fy) + b * fy


def extraire_vue(erp: np.ndarray, vue: Vue, largeur: int, hauteur: int) -> np.ndarray:
    """La vue en perspective, en flottants (même nombre de canaux que le panorama)."""
    return echantillonner_erp(erp.astype(np.float32), rayons_monde(vue, largeur, hauteur))


def vers_q_depuis_z(z: np.ndarray, fov: float) -> np.ndarray:
    """Profondeur z (le long de l'axe) → inverse de la distance radiale."""
    h, w = z.shape
    return cos_axe(w, h, fov) / np.maximum(z, 1e-6)


def vers_q_depuis_disparite(disparite: np.ndarray, fov: float) -> np.ndarray:
    h, w = disparite.shape
    return cos_axe(w, h, fov) * disparite


def correspondances(a: Vue, b: Vue, q_a: np.ndarray, q_b: np.ndarray, m_a: np.ndarray, m_b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Valeurs de `q` de part et d'autre sur les points vus par les deux vues : deux vecteurs de même longueur (éventuellement vides).

    Chaque pixel de `a` est suivi dans `b` par son rayon ; on garde ceux qui tombent dans l'image de `b` et que les deux masques jugent valides.
    """
    h, w = q_a.shape
    hb, wb = q_b.shape
    monde = rayons_monde(a, w, h).reshape(-1, 3)
    cam_b = monde @ _rotation(b.cap, b.tangage)  # (R_b^T)^T = R_b : rayon du monde → repère de b
    z = cam_b[:, 2]
    devant = z > 1e-3
    f = _focale(wb, b.fov)
    xb = np.where(devant, f * cam_b[:, 0] / np.where(devant, z, 1) + wb / 2 - 0.5, -1)
    yb = np.where(devant, -f * cam_b[:, 1] / np.where(devant, z, 1) + hb / 2 - 0.5, -1)
    dans = devant & (xb >= 0) & (xb <= wb - 1) & (yb >= 0) & (yb <= hb - 1)
    xi, yi = np.rint(xb[dans]).astype(int), np.rint(yb[dans]).astype(int)
    va = q_a.reshape(-1)[dans]
    vb = q_b[yi, xi]
    ok = m_a.reshape(-1)[dans] & m_b[yi, xi] & np.isfinite(va) & np.isfinite(vb)
    return va[ok].astype(np.float64), vb[ok].astype(np.float64)
