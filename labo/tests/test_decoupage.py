"""Le découpage par groupes : sans fuite, sans perdre les classes rares, déterministe."""

from __future__ import annotations

import pytest

from laboratoire.donnees.decoupage import JEUX, decouper_par_groupes


def _reel() -> dict[str, dict[str, int]]:
    """28 collections, à la façon des vraies : la classe « 1 » est rare et concentrée dans quelques collections."""
    comptes = {}
    for i in range(28):
        comptes[f"c{i:02d}"] = {"0": 20 + (i * 7) % 30, "2": 4 + (i * 3) % 12}
    for i in (1, 4, 9, 13, 17, 22, 26):  # sept collections seulement ont des « 1 » : 54 images en tout
        comptes[f"c{i:02d}"]["1"] = 7 if i != 26 else 5
    return comptes


def _par_jeu(comptes, aff, classe):
    return {j: sum(comptes[g].get(classe, 0) for g, jeu in aff.items() if jeu == j) for j in JEUX}


def test_aucune_collection_n_est_coupee_en_deux() -> None:
    comptes = _reel()
    aff = decouper_par_groupes(comptes, graine=3)
    assert set(aff) == set(comptes)  # chaque collection a un jeu, un seul
    assert set(aff.values()) <= set(JEUX)


def test_chaque_jeu_garde_des_images_de_la_classe_rare() -> None:
    """Le défaut du 19/10 : 4 images « 1 » en validation, 6 en test. Ici chaque jeu en reçoit une part vraiment utile."""
    comptes = _reel()
    for graine in range(10):
        aff = decouper_par_groupes(comptes, graine=graine)
        un = _par_jeu(comptes, aff, "1")
        assert all(un[j] > 0 for j in JEUX), (graine, un)
        assert un["val"] >= 5 and un["test"] >= 5, (graine, un)  # au moins une collection porteuse dans chacun


def test_les_proportions_sont_a_peu_pres_respectees_pour_chaque_classe() -> None:
    comptes = _reel()
    aff = decouper_par_groupes(comptes, graine=1)
    for classe in ("0", "1", "2"):
        n = _par_jeu(comptes, aff, classe)
        total = sum(n.values())
        assert n["train"] / total == pytest.approx(0.7, abs=0.2), (classe, n)
        assert n["val"] / total == pytest.approx(0.15, abs=0.1), (classe, n)


def test_le_decoupage_est_deterministe_et_depend_de_la_graine() -> None:
    comptes = _reel()
    assert decouper_par_groupes(comptes, graine=5) == decouper_par_groupes(comptes, graine=5)
    assert decouper_par_groupes(comptes, graine=5) != decouper_par_groupes(comptes, graine=6)


def test_l_ordre_des_groupes_ne_change_pas_le_resultat() -> None:
    comptes = _reel()
    inverse = dict(reversed(list(comptes.items())))
    assert decouper_par_groupes(comptes, graine=2) == decouper_par_groupes(inverse, graine=2)


def test_chaque_jeu_recoit_au_moins_un_groupe_des_que_trois_existent() -> None:
    aff = decouper_par_groupes({"a": {"0": 10}, "b": {"0": 10}, "c": {"0": 10}}, graine=0)
    assert sorted(aff.values()) == ["test", "train", "val"]
    aff4 = decouper_par_groupes({g: {"0": 5} for g in "abcd"}, graine=0)
    assert set(aff4.values()) == set(JEUX)


def test_peu_de_groupes_pas_de_plantage() -> None:
    assert decouper_par_groupes({}, graine=0) == {}
    assert len(decouper_par_groupes({"a": {"0": 3}}, graine=0)) == 1
    assert set(decouper_par_groupes({"a": {"0": 3}, "b": {"0": 3}}, graine=0).values()) <= set(JEUX)
    assert decouper_par_groupes({"a": {"0": 0}}, graine=0) == {}  # un groupe vide n'existe pas


@pytest.mark.parametrize("proportions", [(0.5, 0.5), (0.7, 0.2, 0.2), (0.8, 0.2, 0.0), (-0.1, 0.6, 0.5)])
def test_des_proportions_absurdes_sont_refusees(proportions) -> None:
    with pytest.raises(ValueError):
        decouper_par_groupes({"a": {"0": 1}}, proportions=proportions)
