"""Les recettes : étiqueter, regrouper, corriger, découper, rééquilibrer — sans écrire une image."""

from __future__ import annotations

from pathlib import Path

import pytest

from laboratoire.donnees.brut import ImageBrute
from laboratoire.donnees.recette import Recette, etiqueter, lire_corrections, planifier


def _i(nom: str, groupe: str, cote: str, n=None, forme=None, taille=(36, 24)) -> ImageBrute:
    return ImageBrute(f"V/{groupe}/{cote}/{nom}.jpeg", "V", f"V/{groupe}", cote, n, forme, taille[0], taille[1])


def _images() -> list[ImageBrute]:
    out = []
    for g in range(12):
        out += [_i(f"a{g}{k}", f"g{g}", "droite", n=0) for k in range(8)]
        out += [_i(f"b{g}{k}", f"g{g}", "droite", n=2 + (k % 3)) for k in range(3)]  # 2, 3, 4 places : « 2 et plus »
        out += [_i(f"d{g}{k}", f"g{g}", "gauche", n=1) for k in range(2)]
    out += [_i("un1", "g0", "droite", n=1), _i("un2", "g3", "droite", n=1), _i("un3", "g6", "droite", n=1), _i("un4", "g9", "droite", n=1)]
    out += [_i("bat", "g1", "droite", n=4, forme="bataille"), _i("lon", "g2", "droite", forme="longitudinal")]
    return out


def test_nombre_regroupe_deux_places_et_plus() -> None:
    et, ecartes = etiqueter(_images(), Recette(cote="droite", tache="nombre"))
    classes = {e.classe for e in et}
    assert classes == {"0", "1", "2"}  # 3, 4 places → « 2 »
    assert ecartes == {"sans nombre de places": 1}  # la forme seule n'a pas de N
    assert not any(e.image.cote == "gauche" for e in et)


def test_sans_plafond_une_classe_par_nombre() -> None:
    et, _ = etiqueter(_images(), Recette(cote="droite", tache="nombre", plafond_nombre=None))
    assert {e.classe for e in et} == {"0", "1", "2", "3", "4"}


def test_une_image_a_deux_etiquettes_compte_dans_nombre_et_dans_forme() -> None:
    """Le défaut du 19/10 : « 4 places, bataille » n'allait que dans « forme » ; le jeu « nombre » en était faussé."""
    nombre, _ = etiqueter(_images(), Recette(cote="droite", tache="nombre"))
    forme, _ = etiqueter(_images(), Recette(cote="droite", tache="forme"))
    assert "V/g1/droite/bat.jpeg" in {e.image.chemin for e in nombre}
    assert [e.classe for e in forme if "bat" in e.image.chemin] == ["bataille"]
    assert {e.classe for e in forme} == {"bataille", "longitudinal"}


def test_les_types_d_image_se_filtrent() -> None:
    images = _images() + [_i("plate", "g0", "droite", n=0, taille=(1600, 30))]
    garde, ecartes = etiqueter(images, Recette(cote="droite", tache="nombre", type_image="recadrage"))
    assert not any(e.image.plate for e in garde) and ecartes["photo plate écartée"] == 1
    seules, ecartes = etiqueter(images, Recette(cote="droite", tache="nombre", type_image="plate"))
    assert [e.image.chemin for e in seules] == ["V/g0/droite/plate.jpeg"] and ecartes["recadrage écarté"] > 0


def test_les_corrections_changent_une_classe_ou_ecartent_une_image(tmp_path: Path) -> None:
    csv = tmp_path / "corrections.csv"
    csv.write_text("chemin,decision,note\nV/g0/droite/a00.jpeg,1,vu : une place\nV/g0/droite/a01.jpeg,douteuse,floue\n", encoding="utf-8")
    corr = lire_corrections(csv)
    assert corr == {"V/g0/droite/a00.jpeg": "1", "V/g0/droite/a01.jpeg": None}
    et, ecartes = etiqueter(_images(), Recette(cote="droite", tache="nombre"), corr)
    par = {e.image.chemin: e.classe for e in et}
    assert par["V/g0/droite/a00.jpeg"] == "1" and "V/g0/droite/a01.jpeg" not in par
    assert ecartes["étiquette douteuse écartée"] == 1
    assert lire_corrections(tmp_path / "absent.csv") == {}


def test_planifier_decoupe_par_collection_et_ne_fuit_pas() -> None:
    plan = planifier(_images(), Recette(cote="droite", tache="nombre", reequilibrage={"actif": False}))
    jeux_par_collection: dict[str, set[str]] = {}
    for l in plan.lignes:
        jeux_par_collection.setdefault(l.etiquetee.image.groupe, set()).add(l.jeu)
    assert all(len(j) == 1 for j in jeux_par_collection.values())  # aucune collection dans deux jeux
    eff = plan.effectifs()
    assert all(sum(eff[j].values()) > 0 for j in eff)
    assert plan.groupes_par_jeu()["train"] > plan.groupes_par_jeu()["val"] >= 1


def test_le_reequilibrage_ne_touche_que_le_train_et_marque_les_copies() -> None:
    sans = planifier(_images(), Recette(cote="droite", tache="nombre", reequilibrage={"actif": False}))
    avec = planifier(_images(), Recette(cote="droite", tache="nombre", reequilibrage={"actif": True, "rapport": 0.5}))
    s, a = sans.effectifs(), avec.effectifs()
    assert a["val"] == s["val"] and a["test"] == s["test"]  # val et test inchangés
    cible = int(max(s["train"].values()) * 0.5)
    assert all(a["train"][c] >= cible for c in a["train"])  # chaque classe du train atteint la cible
    assert a["train"]["1"] > s["train"]["1"]  # la classe rare a été complétée
    assert all(l.jeu == "train" and l.copie > 0 for l in avec.lignes if l.copie)
    assert avec.effectifs_sans_copies() == s  # les effectifs « vrais » ne bougent pas


def test_l_empreinte_ignore_le_nom_mais_pas_les_parametres() -> None:
    a = Recette(cote="droite", tache="nombre", nom="premier")
    assert a.empreinte() == Recette(cote="droite", tache="nombre", nom="autre").empreinte()
    assert a.empreinte() != Recette(cote="gauche", tache="nombre").empreinte()
    assert a.empreinte() != Recette(cote="droite", tache="nombre", preparation="masque").empreinte()
    assert a.empreinte() != Recette(cote="droite", tache="nombre", decoupage={"graine": 8}).empreinte()


@pytest.mark.parametrize("mauvais", [{"cote": "devant", "tache": "nombre"}, {"cote": "droite", "tache": "x"}, {"cote": "droite", "tache": "nombre", "vitesse": 1},
                                     {"cote": "droite", "tache": "nombre", "plafond_nombre": 0}, {"cote": "droite", "tache": "nombre", "decoupage": {"proportions": [0.5, 0.5, 0.5]}},
                                     {"cote": "droite", "tache": "nombre", "reequilibrage": {"rapport": 0}}])
def test_une_recette_inventee_est_refusee(mauvais) -> None:
    with pytest.raises(Exception):
        Recette(**mauvais)


def _avec_contenu(image: ImageBrute, contenu: str) -> ImageBrute:
    from dataclasses import replace

    return replace(image, contenu=contenu)


def test_le_regroupement_par_contenu_ne_coupe_pas_une_image_rangee_sous_deux_routes() -> None:
    images = []
    for g in range(12):
        images += [_avec_contenu(_i(f"a{g}{k}", f"g{g}", "droite", n=0), f"c{g}-{k}") for k in range(6)]
        images += [_avec_contenu(_i(f"b{g}{k}", f"g{g}", "droite", n=2), f"d{g}-{k}") for k in range(6)]
    # Les routes g1 et g2 portent la même image : par route elles sont séparables, par contenu elles ne le sont plus.
    images.append(_avec_contenu(_i("copie1", "g1", "droite", n=0), "partagee"))
    images.append(_avec_contenu(_i("copie2", "g2", "droite", n=0), "partagee"))
    for graine in range(40):
        recette = Recette(cote="droite", tache="nombre", regroupement="contenu", reequilibrage={"actif": False}, decoupage={"graine": graine})
        plan = planifier(images, recette)
        jeux = {}
        for l in plan.lignes:
            jeux.setdefault(l.etiquetee.image.contenu, set()).add(l.jeu)
        assert all(len(j) == 1 for j in jeux.values()), graine
        assert "V/g2" not in plan.affectation  # g2 est fusionnée dans g1 : un seul groupe, donc un seul jeu
    # Par route, g1 et g2 restent deux groupes (le découpage peut donc les séparer) ; par contenu, ce n'en est qu'un.
    from laboratoire.donnees.recette import _groupes_effectifs, etiqueter

    etiquetees, _ = etiqueter(images, Recette(cote="droite", tache="nombre"))
    par_route = _groupes_effectifs(etiquetees, "route")
    par_contenu = _groupes_effectifs(etiquetees, "contenu")
    c1, c2 = (next(e.image.chemin for e in etiquetees if e.image.chemin.endswith(f"copie{k}.jpeg")) for k in (1, 2))
    assert par_route[c1] != par_route[c2]
    assert par_contenu[c1] == par_contenu[c2]


def test_le_regroupement_par_enregistrement_garde_une_prise_de_vue_entiere() -> None:
    from laboratoire.donnees.brut import identifiant_enregistrement

    u = "251470fc-cd59-4c07-b680-27989d2cca12"
    assert identifiant_enregistrement(f"MEYLAN/11463/{u}") == identifiant_enregistrement(f"MEYLAN/{u}/6486") == u
    assert identifiant_enregistrement("V/g1/x") == "V/g1/x"  # pas d'identifiant reconnu : le groupe lui-même
    uuids = [f"{i:08x}-0000-4000-8000-{i:012x}" for i in range(12)]
    images = []
    for i, u in enumerate(uuids):
        for route in ("r1", "r2"):
            images += [
                ImageBrute(f"V/{route}/{u}/droite/{k}.jpeg", "V", f"V/{route}/{u}", "droite", k % 3, None, 36, 24, f"{i}-{route}-{k}")
                for k in range(6)
            ]
    plan = planifier(images, Recette(cote="droite", tache="nombre", regroupement="enregistrement", reequilibrage={"actif": False}))
    par_enregistrement = {}
    for l in plan.lignes:
        par_enregistrement.setdefault(l.etiquetee.image.enregistrement, set()).add(l.jeu)
    assert all(len(j) == 1 for j in par_enregistrement.values())  # une prise de vue ne se coupe pas, même répartie sur deux routes


def test_dedoublonner_garde_un_exemplaire_et_ecarte_les_etiquettes_contradictoires() -> None:
    a = _avec_contenu(_i("a", "g0", "droite", n=0), "x")
    b = _avec_contenu(_i("b", "g1", "droite", n=0), "x")  # même image, même étiquette : un seul exemplaire
    c = _avec_contenu(_i("c", "g2", "droite", n=1), "y")
    d = _avec_contenu(_i("d", "g3", "droite", n=2), "y")  # même image, étiquettes différentes : on ne sait pas laquelle croire
    e = _i("e", "g4", "droite", n=0)  # contenu inconnu : conservé tel quel
    recette = Recette(cote="droite", tache="nombre", dedoublonner=True, reequilibrage={"actif": False})
    plan = planifier([a, b, c, d, e], recette)
    gardees = {l.etiquetee.image.chemin for l in plan.lignes}
    assert gardees == {a.chemin, e.chemin}
    assert plan.ecartes == {"exemplaire en double écarté": 1, "étiquettes contradictoires pour une même image": 2}


def test_les_options_ajoutees_ne_changent_pas_l_identite_des_variantes_existantes() -> None:
    d_origine = Recette(cote="droite", tache="nombre")
    assert d_origine.empreinte() == Recette(cote="droite", tache="nombre", regroupement="route", dedoublonner=False, taille=None).empreinte()
    assert d_origine.empreinte() != Recette(cote="droite", tache="nombre", regroupement="contenu").empreinte()
    assert d_origine.empreinte() != Recette(cote="droite", tache="nombre", taille=64).empreinte()
