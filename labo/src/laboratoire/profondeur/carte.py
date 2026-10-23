"""Mettre une carte de profondeur en image pour un œil humain (sans matplotlib : un polynôme de la palette « turbo »)."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image


def turbo(x: np.ndarray) -> np.ndarray:
    """x dans [0, 1] → couleurs (…, 3) uint8. Approximation polynomiale de la palette turbo (Mikhailov, Google, Apache-2.0)."""
    x = np.clip(x, 0.0, 1.0)
    r = 0.13572138 + x * (4.61539260 + x * (-42.66032258 + x * (132.13108234 + x * (-152.94239396 + x * 59.28637943))))
    g = 0.09140261 + x * (2.19418839 + x * (4.84296658 + x * (-14.18503333 + x * (4.27729857 + x * 2.82956604))))
    b = 0.10667330 + x * (12.64194608 + x * (-60.58204836 + x * (110.36276771 + x * (-89.90310912 + x * 27.34824973))))
    return (np.clip(np.stack([r, g, b], -1), 0, 1) * 255).astype(np.uint8)


def colorier(q: np.ndarray, masque: np.ndarray | None = None) -> np.ndarray:
    """Carte `q` (inverse de distance : grand = proche) → image RGB. Rouge : proche, bleu : loin ; gris foncé : pixel que le modèle écarte (ciel)."""
    valide = np.isfinite(q) if masque is None else (masque & np.isfinite(q))
    if not valide.any():
        return np.full((*q.shape, 3), 40, np.uint8)
    lo, hi = np.percentile(q[valide], [2, 98])
    t = np.clip((q - lo) / max(hi - lo, 1e-9), 0, 1)
    img = turbo(t)
    img[~valide] = (40, 40, 40)
    return img


def vers_jpeg(image: np.ndarray, largeur: int | None = None, qualite: int = 85) -> bytes:
    im = Image.fromarray(image)
    if largeur and im.width != largeur:
        im = im.resize((largeur, round(im.height * largeur / im.width)), Image.BILINEAR)
    tampon = io.BytesIO()
    im.convert("RGB").save(tampon, "JPEG", quality=qualite)
    return tampon.getvalue()
