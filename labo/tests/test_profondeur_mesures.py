"""Géométrie des panoramas et mesures sans référence, sur une scène dont on connaît la profondeur : un sol plat et un mur cylindrique."""

from __future__ import annotations

import math

import numpy as np
import pytest

from laboratoire.profondeur import geometrie as g
from laboratoire.profondeur import mesures as m

H_CAM, RAYON = 2.0, 12.0


def erp_q(he: int = 256, we: int = 512) -> np.ndarray:
    """Inverse de la distance radiale d'une scène simple : sol à 2 m sous la caméra, mur cylindrique à 12 m, rien au-dessus de l'horizon proche."""
    lat = (0.5 - (np.arange(he) + 0.5) / he) * math.pi
    r = np.where(lat < 0, np.minimum(H_CAM / np.maximum(-np.sin(lat), 1e-6), RAYON / np.maximum(np.cos(lat), 1e-6)), RAYON / np.maximum(np.cos(lat), 1e-6))
    return np.repeat((1.0 / r)[:, None], we, axis=1)


def vues_q(vues, largeur=160, hauteur=120, bruit=0.0, deformation=None, graine=0):
    rng = np.random.default_rng(graine)
    erp = erp_q()
    qs = []
    for k, v in enumerate(vues):
        q = g.echantillonner_erp(erp, g.rayons_monde(v, largeur, hauteur))
        if deformation:
            a, b = deformation(k)
            q = a * q + b  # un modèle relatif : échelle et décalage propres à chaque vue
        qs.append(q + bruit * rng.standard_normal(q.shape) * q.std())
    return np.stack(qs)


def test_la_grille_de_vues_fait_un_tour_et_une_rangee_inclinee() -> None:
    v = g.grille_de_vues(90, 45, 15)
    assert len(v) == 16 and v[0].nom == "c000_t00" and v[-1].nom == "c315_t15"
    assert len(g.grille_de_vues(90, 90, 0)) == 4
    with pytest.raises(ValueError):
        g.grille_de_vues(10)


def test_une_vue_au_centre_regarde_le_centre_du_panorama() -> None:
    erp = np.zeros((64, 128, 3), np.float32)
    erp[:, 60:68] = 255  # bande verticale au centre (longitude 0)
    centre = g.extraire_vue(erp, g.Vue(0, 0, 60), 64, 48)
    cote = g.extraire_vue(erp, g.Vue(90, 0, 60), 64, 48)
    assert centre[24, 32, 0] > 200 and cote[24, 32, 0] < 1


def test_la_longitude_boucle() -> None:
    erp = np.zeros((32, 64), np.float32)
    erp[:, 0] = 1.0  # le bord gauche touche le bord droit
    vue = g.extraire_vue(erp, g.Vue(180, 0, 40), 32, 24)  # regarde la couture
    assert vue.max() > 0.5


def test_un_modele_exact_est_coherent_meme_avec_une_echelle_par_vue() -> None:
    vues = g.grille_de_vues(90, 45, 15)
    q = vues_q(vues, deformation=lambda k: (1.0 + 0.3 * k, 0.05 * k))
    masque = np.ones(q.shape, bool)
    res = m.coherence_recouvrement(q, masque, vues, metrique=True)
    assert res["paires"] > 20
    assert res["incoherence"] < 0.1  # affine-invariant : l'échelle propre à chaque vue ne compte pas
    assert res["derive_echelle"] > 0.2  # …mais un modèle « métrique » qui change d'échelle d'une vue à l'autre le paie


def test_le_bruit_degrade_la_coherence() -> None:
    vues = g.grille_de_vues(90, 45, 15)
    propre = m.coherence_recouvrement(vues_q(vues), np.ones((16, 120, 160), bool), vues)["incoherence"]
    bruite = m.coherence_recouvrement(vues_q(vues, bruit=1.5), np.ones((16, 120, 160), bool), vues)["incoherence"]
    assert propre < 0.1 < bruite


def test_l_accord_entre_deux_modeles_qui_voient_le_meme_relief() -> None:
    vues = g.grille_de_vues(90, 45, 15)
    a = vues_q(vues)
    b = 3.0 * a + 0.2  # même relief, autre échelle
    c = vues_q(vues, bruit=4.0, graine=1)
    ones = np.ones(a.shape, bool)
    assert m.accord(a, ones, b, ones) > 0.99
    assert m.accord(a, ones, c, ones) < 0.7


def test_le_classement_par_paires_retrouve_le_meilleur() -> None:
    rng = np.random.default_rng(0)
    force = {"a": 1.5, "b": 0.0, "c": -1.0}
    juges = []
    for k in range(300):
        x, y = rng.choice(["a", "b", "c"], size=2, replace=False)
        p = 1 / (1 + math.exp(-(force[x] - force[y])))
        gagnant, perdant = (x, y) if rng.random() < p else (y, x)
        juges.append(m.Jugement(gagnant, perdant, str(x), str(y), groupe=f"p{k % 20}"))
    r = m.classement(["a", "b", "c"], juges, tirages=60)
    assert [r["modeles"][k]["rang"] for k in "abc"] == [1, 2, 3]
    assert r["fiable"] and r["modeles"]["a"]["intervalle"][0] > r["modeles"]["b"]["force"] - 1
    assert abs(sum(v["force"] for v in r["modeles"].values())) < 1e-6


def test_sans_vote_pas_de_classement_fiable() -> None:
    r = m.classement(["a", "b"], [])
    assert not r["fiable"] and r["modeles"]["a"]["force"] == pytest.approx(0.0, abs=1e-6)


def test_les_egalites_rapprochent_les_modeles() -> None:
    juges = [m.Jugement(None, None, "a", "b", groupe=f"p{k}") for k in range(30)]
    f = m.bradley_terry(["a", "b"], juges)
    assert abs(f["a"] - f["b"]) < 1e-6
