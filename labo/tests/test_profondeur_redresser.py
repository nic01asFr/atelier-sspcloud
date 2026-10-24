"""Incliner et redresser un panorama, et ce que ça change pour la mesure d'un essai."""

from __future__ import annotations

import csv

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from laboratoire.profondeur import redresser
from laboratoire.projet import Racine
from test_profondeur_essai import _attendre, _ajouter_verite_sol_plat, client, config  # noqa: F401  (le client et la vérité de sol plat sont ceux des essais)


def carte_lisse(hauteur: int = 128, largeur: int = 256) -> np.ndarray:
    y, x = np.mgrid[0:hauteur, 0:largeur]
    return (np.sin(x / 17.0) + np.cos(y / 9.0)).astype(np.float32)


def test_incliner_puis_redresser_rend_la_carte_a_l_interpolation_pres() -> None:
    c = carte_lisse()
    retour = redresser.redresser(redresser.incliner(c, 5.0, 3.0), 5.0, 3.0)
    milieu = (slice(30, 100), slice(None))  # loin des pôles, où la grille d'un panorama se déforme
    assert np.abs(retour[milieu] - c[milieu]).mean() < 0.05


def test_une_inclinaison_nulle_ne_change_rien_et_une_vraie_deplace_l_horizon() -> None:
    c = carte_lisse()
    assert np.allclose(redresser.incliner(c, 0.0, 0.0), c, atol=1e-4)
    sol = np.zeros((128, 256), np.float32)
    sol[64:] = 1.0  # horizon au milieu
    haut = redresser.incliner(sol, 10.0, 0.0)  # caméra qui regarde 10° plus haut : l'horizon descend dans l'image
    assert (haut[:, 128] > 0.5).argmax() > 64 + 5


def test_les_inclinaisons_du_manifeste_se_lisent_et_une_case_vide_vaut_zero(tmp_path) -> None:
    (tmp_path / "manifeste.csv").write_text("fichier,tangage,roulis\nval/panorama/a.png,2.5,-1\nval/panorama/b.png,,\n", encoding="utf-8")
    assert redresser.inclinaisons(tmp_path) == {"a": (2.5, -1.0), "b": (0.0, 0.0)}


def _pencher_le_jeu(racine: Racine, tangage: float = 6.0, roulis: float = 4.0) -> None:
    """Le jeu de test (vérité de sol plat) pris avec une caméra penchée : images, références et manifeste."""
    dossier = racine.dossier_variante("jeu-test")
    for npz in (dossier / "val" / "verite").glob("*.npz"):
        with np.load(npz) as f:
            champs = {k: redresser.incliner(f[k], tangage, roulis, plus_proche=True) for k in f.files}
        np.savez_compressed(npz, **champs)
    manifeste = dossier / "manifeste.csv"
    with manifeste.open(encoding="utf-8", newline="") as f:
        lecteur = csv.DictReader(f)
        colonnes, lignes = list(lecteur.fieldnames or []), list(lecteur)
    colonnes += [c for c in ("tangage", "roulis") if c not in colonnes]
    for ligne in lignes:
        ligne["tangage"], ligne["roulis"] = tangage, roulis
    with manifeste.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, colonnes)
        w.writeheader()
        w.writerows(lignes)


def test_redresser_efface_l_effet_d_une_inclinaison_sur_l_erreur_mesuree(client: TestClient, racine: Racine) -> None:  # noqa: F811
    _ajouter_verite_sol_plat(racine)
    _pencher_le_jeu(racine)
    penche = client.post("/api/essais", json=config("plan")).json()["id"]
    redresse = client.post("/api/essais", json=config("plan", redresser=True)).json()["id"]
    assert _attendre(client, penche)["etat"] == "termine" and _attendre(client, redresse)["etat"] == "termine"
    rp = client.get(f"/api/essais/{penche}").json()["resultats"]["rapport"]
    rr = client.get(f"/api/essais/{redresse}").json()["resultats"]["rapport"]
    assert rp["absrel_mediane"] > 0.15  # le sol n'est plus à plat dans le repère du panorama : le modèle de sol plat se trompe
    assert rr["absrel_mediane"] < 0.06 and rr["delta1_mediane"] > 0.9  # remis d'aplomb, il retrouve la vérité


def test_le_reglage_redresser_est_connu_et_une_faute_de_frappe_est_refusee() -> None:
    from laboratoire.profondeur.executer import reglages_complets

    assert reglages_complets({"redresser": True})["fov"] == 90.0
    with pytest.raises(ValueError):
        reglages_complets({"redresse": True})
