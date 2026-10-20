"""L'évaluation : les chiffres doivent démasquer un modèle qui n'a rien appris."""

from __future__ import annotations

import pytest

from laboratoire import evaluation as ev

CLASSES = ["0", "1", "2"]


def _repete(vrai: str, predit: str, n: int) -> tuple[list[str], list[str]]:
    return [vrai] * n, [predit] * n


def test_le_cas_du_19_octobre_un_modele_qui_repond_toujours_zero_est_demasque() -> None:
    """Validation réelle de Classification : 141 images « 0 », 4 « 1 », 14 « 2 ». Toujours « 0 » donnait 0,887 d'exactitude."""
    v0, p0 = _repete("0", "0", 141)
    v1, p1 = _repete("1", "0", 4)
    v2, p2 = _repete("2", "0", 14)
    r = ev.rapport(CLASSES, v0 + v1 + v2, p0 + p1 + p2)
    assert r["exactitude"] == pytest.approx(141 / 159)  # 0,887 : flatteur
    assert r["rappel_moyen"] == pytest.approx(1 / 3)  # la vérité : un tiers
    assert r["par_classe"]["1"]["rappel"] == 0.0 and r["par_classe"]["2"]["rappel"] == 0.0
    triviale = ev.reponses_triviales(CLASSES, v0 + v1 + v2)
    assert triviale["majoritaire"]["classe"] == "0"
    assert triviale["majoritaire"]["exactitude"] == pytest.approx(141 / 159)
    # Le modèle n'a aucun gain sur la réponse triviale : c'est écrit noir sur blanc.
    assert ev.gain_sur_trivial(r, triviale)["majoritaire"] == pytest.approx(0.0)


def test_rappel_precision_et_f1_par_classe() -> None:
    vrais = ["0", "0", "0", "1", "1", "2"]
    predits = ["0", "0", "1", "1", "0", "2"]
    r = ev.rapport(CLASSES, vrais, predits)
    assert r["par_classe"]["0"]["rappel"] == pytest.approx(2 / 3)
    assert r["par_classe"]["0"]["precision"] == pytest.approx(2 / 3)
    assert r["par_classe"]["1"]["rappel"] == pytest.approx(1 / 2)
    assert r["par_classe"]["2"]["f1"] == pytest.approx(1.0)
    assert r["confusion"] == [[2, 1, 0], [1, 1, 0], [0, 0, 1]]
    assert r["exactitude"] == pytest.approx(4 / 6)
    assert r["rappel_moyen"] == pytest.approx((2 / 3 + 1 / 2 + 1) / 3)


def test_une_classe_sans_image_n_a_pas_de_rappel_et_ne_pese_pas_dans_la_moyenne() -> None:
    r = ev.rapport(CLASSES, ["0", "0", "1"], ["0", "0", "1"])
    assert r["par_classe"]["2"]["rappel"] is None
    assert r["rappel_moyen"] == pytest.approx(1.0)


def test_une_classe_rare_est_marquee_non_fiable() -> None:
    vrais = ["0"] * 30 + ["1"] * 6
    r = ev.rapport(CLASSES, vrais, vrais)
    assert r["par_classe"]["0"]["fiable"] is True
    assert r["par_classe"]["1"]["fiable"] is False
    assert r["classes_non_fiables"] == ["1"]
    # Le seuil se règle.
    assert ev.rapport(CLASSES, vrais, vrais, seuil_fiable=5)["classes_non_fiables"] == []


def test_une_classe_inconnue_est_une_erreur_et_non_un_silence() -> None:
    with pytest.raises(ValueError, match="inconnue"):
        ev.rapport(CLASSES, ["0", "9"], ["0", "0"])
    with pytest.raises(ValueError, match="inconnue"):
        ev.rapport(CLASSES, ["0"], ["Z"])
    with pytest.raises(ValueError, match="prédictions"):
        ev.rapport(CLASSES, ["0", "1"], ["0"])


def test_jeu_vide() -> None:
    r = ev.rapport(CLASSES, [], [])
    assert r["exactitude"] is None and r["rappel_moyen"] is None
    assert ev.reponses_triviales(CLASSES, [])["majoritaire"]["exactitude"] is None


def test_reponses_triviales() -> None:
    t = ev.reponses_triviales(CLASSES, ["0"] * 6 + ["1"] * 3 + ["2"])
    assert t["majoritaire"]["classe"] == "0"
    assert t["majoritaire"]["exactitude"] == pytest.approx(0.6)
    assert t["majoritaire"]["rappel_moyen"] == pytest.approx(1 / 3)
    assert t["hasard"]["rappel_moyen"] == pytest.approx(1 / 3)


def test_les_classes_absentes_du_jeu_ne_comptent_pas_dans_la_reponse_triviale_majoritaire() -> None:
    t = ev.reponses_triviales(CLASSES, ["0"] * 5 + ["1"] * 5)
    assert t["majoritaire"]["rappel_moyen"] == pytest.approx(1 / 2)  # deux classes présentes, pas trois


def test_l_intervalle_par_groupes_est_deterministe_et_contient_l_estimation() -> None:
    vrais, predits, groupes = [], [], []
    for g in range(8):
        for i in range(10):
            vrais.append("0" if i < 7 else "1")
            predits.append("0" if (i != 8 or g % 2) else "0")
            groupes.append(f"c{g}")
    a = ev.intervalle_par_groupes(CLASSES, vrais, predits, groupes, tirages=300, graine=3)
    b = ev.intervalle_par_groupes(CLASSES, vrais, predits, groupes, tirages=300, graine=3)
    assert a == b
    assert a["bas"] <= a["estimation"] <= a["haut"]
    assert a["groupes"] == 8


def test_l_intervalle_est_plus_large_quand_les_groupes_different() -> None:
    """Des groupes qui se ressemblent donnent un intervalle étroit ; des groupes très différents, un intervalle large."""
    homogene_v, homogene_p, homogene_g = [], [], []
    divers_v, divers_p, divers_g = [], [], []
    for g in range(8):
        for i in range(10):
            vrai = "0" if i < 5 else "1"
            homogene_v.append(vrai)
            homogene_p.append(vrai if i % 5 else ("1" if vrai == "0" else "0"))  # une erreur sur cinq, partout
            homogene_g.append(f"h{g}")
            divers_v.append(vrai)
            divers_p.append(vrai if g % 2 == 0 else ("1" if vrai == "0" else "0"))  # groupes parfaits ou tout faux
            divers_g.append(f"d{g}")
    h = ev.intervalle_par_groupes(CLASSES, homogene_v, homogene_p, homogene_g, tirages=400, graine=1)
    d = ev.intervalle_par_groupes(CLASSES, divers_v, divers_p, divers_g, tirages=400, graine=1)
    assert (d["haut"] - d["bas"]) > (h["haut"] - h["bas"])


def test_un_seul_groupe_ne_donne_pas_d_intervalle() -> None:
    r = ev.intervalle_par_groupes(CLASSES, ["0", "1"], ["0", "1"], ["c1", "c1"])
    assert r["bas"] is None and r["haut"] is None and r["groupes"] == 1


def test_comparaison_appariee_distingue_le_reel_du_bruit() -> None:
    reel = ev.comparaison_appariee([0.71, 0.74, 0.69, 0.72, 0.73], [0.55, 0.58, 0.52, 0.57, 0.54], graine=2)
    assert reel["verdict"] == "A meilleur que B" and reel["bas"] > 0
    inverse = ev.comparaison_appariee([0.5, 0.52, 0.51, 0.5], [0.7, 0.71, 0.69, 0.72], graine=2)
    assert inverse["verdict"] == "B meilleur que A"
    bruit = ev.comparaison_appariee([0.60, 0.70, 0.55, 0.65, 0.62], [0.62, 0.66, 0.60, 0.61, 0.64], graine=2)
    assert "bruit" in bruit["verdict"]


def test_on_ne_conclut_pas_avec_moins_de_trois_paires() -> None:
    assert "trop peu" in ev.comparaison_appariee([0.9, 0.9], [0.1, 0.1])["verdict"]
    assert ev.comparaison_appariee([], [])["verdict"] == "aucune donnée"
    with pytest.raises(ValueError):
        ev.comparaison_appariee([1.0], [1.0, 2.0])
