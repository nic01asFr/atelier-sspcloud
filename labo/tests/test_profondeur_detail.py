"""L'erreur par tranche de distance et par couche, relue depuis les cartes qu'un essai a gardées."""

from __future__ import annotations

import json

import numpy as np
from fastapi.testclient import TestClient

from laboratoire.profondeur import detail
from laboratoire.projet import Racine
from test_profondeur_essai import _ajouter_verite_sol_plat, _attendre, client, config  # noqa: F401


def _detail_de(client: TestClient, racine: Racine, modele: str) -> dict:
    ident = client.post("/api/essais", json=config(modele)).json()["id"]
    assert _attendre(client, ident)["etat"] == "termine"
    reglages = json.loads((racine.dossier_essai(ident) / "resultats.json").read_text(encoding="utf-8"))["reglages"]
    return detail.detail(racine.dossier_essai(ident), racine.dossier_variante("jeu-test"), reglages)


def test_un_modele_de_sol_plat_n_a_presque_pas_d_erreur_sur_un_sol_plat_et_aucun_biais(client: TestClient, racine: Racine) -> None:  # noqa: F811
    _ajouter_verite_sol_plat(racine)
    d = _detail_de(client, racine, "plan")
    assert d["panoramas"] == 2 and d["ensemble"]["pixels"] > 1000
    assert d["ensemble"]["absrel"] < 0.05 and abs(d["ensemble"]["biais"]) < 0.05
    assert any(t and t["absrel"] < 0.05 for t in d["tranches"].values())
    assert set(d["couches"]) == {"c0"}  # le jeu de test n'a qu'une couche ; sans couches.json elle s'appelle c0


def test_un_modele_sans_relief_se_trompe_plus_que_le_sol_plat_et_les_tranches_partagent_les_pixels(client: TestClient, racine: Racine) -> None:  # noqa: F811
    _ajouter_verite_sol_plat(racine)
    plan, contraste = _detail_de(client, racine, "plan"), _detail_de(client, racine, "contraste")
    assert contraste["ensemble"]["absrel"] > plan["ensemble"]["absrel"]
    n_tranches = sum(t["pixels"] for t in plan["tranches"].values() if t)
    assert n_tranches <= plan["ensemble"]["pixels"] and n_tranches > 0.9 * plan["ensemble"]["pixels"]  # quelques tranches trop petites peuvent manquer


def test_les_noms_de_couches_viennent_du_jeu(tmp_path) -> None:
    (tmp_path / "couches.json").write_text(json.dumps(["terrain", "sol"]), encoding="utf-8")
    assert detail.noms_des_couches(tmp_path) == ["terrain", "sol"]
    assert detail.noms_des_couches(tmp_path / "ailleurs")[:2] == ["c0", "c1"]
    assert np.isclose(detail.BORNES_M[-1], 100.0, atol=1e-3)
