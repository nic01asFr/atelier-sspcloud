"""Le registre : transitions strictes, rien ne s'écrase, reprise après arrêt."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from laboratoire.empreinte import canonique, empreinte
from laboratoire.modeles import ConfigEssai, Methode
from laboratoire.registre import MIGRATIONS, EssaiInconnu, Registre, TransitionRefusee


def _config(**kw) -> ConfigEssai:
    base = dict(jeu="droite-nombre-v1", methode=Methode(famille="yolo_cls", modele="yolo26n-cls", imgsz=224))
    base.update(kw)
    return ConfigEssai(**base)


@pytest.fixture()
def registre(tmp_path: Path) -> Registre:
    horloge = iter(range(1000, 100000))
    return Registre(tmp_path / "labo.db", horloge=lambda: float(next(horloge)))


def test_l_empreinte_ne_depend_pas_de_l_ordre_des_cles() -> None:
    assert empreinte({"a": 1, "b": [1, 2]}) == empreinte({"b": [1, 2], "a": 1})
    assert canonique({"é": 1}) == '{"é":1}'
    assert empreinte({"a": 1}) != empreinte({"a": 2})


def test_la_note_ne_change_pas_l_empreinte_mais_le_reste_oui() -> None:
    assert _config(note="premier").empreinte() == _config(note="autre").empreinte()
    assert _config(graine=1).empreinte() != _config(graine=2).empreinte()
    assert _config().empreinte() != _config(methode=Methode(famille="yolo_cls", modele="yolo26s-cls", imgsz=224)).empreinte()


def test_une_configuration_inventee_est_refusee() -> None:
    with pytest.raises(Exception):
        ConfigEssai(jeu="x", methode=Methode(famille="f", modele="m"), vitesse="max")  # type: ignore[call-arg]
    with pytest.raises(Exception):
        Methode(famille="f", modele="m", imgsz=0)
    with pytest.raises(Exception):
        Methode(famille="f", modele="m", epochs=0)


def test_creer_un_essai_donne_des_identifiants_qui_se_suivent_et_ne_s_ecrasent_pas(registre: Registre) -> None:
    a, b = registre.creer_essai(_config()), registre.creer_essai(_config())  # même configuration : deux essais, deux identifiants
    assert (a, b) == ("E0001", "E0002")
    assert registre.essai(a)["empreinte"] == registre.essai(b)["empreinte"]
    e = registre.essai(a)
    assert e["etat"] == "en_file" and e["config"]["jeu"] == "droite-nombre-v1" and e["imgsz"] == 224


def test_le_cycle_de_vie_et_ses_evenements(registre: Registre) -> None:
    ident = registre.creer_essai(_config())
    registre.changer_etat(ident, "en_cours", debut=5.0, pid=4242)
    e = registre.changer_etat(ident, "termine", fin=9.0, code_sortie=0)
    assert (e["etat"], e["pid"], e["code_sortie"], e["fin"]) == ("termine", 4242, 0, 9.0)
    assert [x["genre"] for x in registre.evenements(ident)] == ["cree", "en_cours", "termine"]


@pytest.mark.parametrize(
    "chemin",
    [
        ["en_cours", "termine", "en_cours"],  # un terminé ne repart pas
        ["en_cours", "echoue", "termine"],
        ["arrete", "en_cours"],
    ],
)
def test_les_transitions_interdites_sont_refusees(registre: Registre, chemin: list[str]) -> None:
    ident = registre.creer_essai(_config())
    with pytest.raises(TransitionRefusee):
        for etat in chemin:
            registre.changer_etat(ident, etat)


def test_un_interrompu_peut_etre_remis_en_file(registre: Registre) -> None:
    ident = registre.creer_essai(_config())
    registre.changer_etat(ident, "en_cours", pid=1)
    registre.changer_etat(ident, "interrompu")
    assert registre.changer_etat(ident, "en_file")["etat"] == "en_file"


def test_une_colonne_non_modifiable_est_refusee_et_rien_n_est_ecrit(registre: Registre) -> None:
    ident = registre.creer_essai(_config())
    with pytest.raises(ValueError):
        registre.changer_etat(ident, "en_cours", empreinte="truquée")
    assert registre.essai(ident)["etat"] == "en_file"


def test_essai_inconnu(registre: Registre) -> None:
    with pytest.raises(EssaiInconnu):
        registre.essai("E9999")
    with pytest.raises(EssaiInconnu):
        registre.changer_etat("E9999", "en_cours")
    with pytest.raises(EssaiInconnu):
        registre.consulter_test("E9999")


def test_la_file_sert_le_plus_ancien_d_abord(registre: Registre) -> None:
    a, b = registre.creer_essai(_config()), registre.creer_essai(_config(graine=1))
    assert registre.prochain_en_file()["id"] == a
    registre.changer_etat(a, "en_cours", pid=1)
    assert registre.prochain_en_file()["id"] == b
    registre.changer_etat(b, "arrete")
    assert registre.prochain_en_file() is None


def test_les_resultats_sont_retenus_par_jeu_evalue(registre: Registre) -> None:
    ident = registre.creer_essai(_config())
    registre.enregistrer_resultats(ident, "val", {"rappel_moyen": 0.61, "exactitude": 0.8})
    registre.enregistrer_resultats(ident, "test", {"rappel_moyen": 0.55, "exactitude": 0.7})
    e = registre.essai(ident)
    assert (e["rappel_moyen_val"], e["exactitude_val"], e["rappel_moyen_test"], e["exactitude_test"]) == (0.61, 0.8, 0.55, 0.7)
    with pytest.raises(ValueError):
        registre.enregistrer_resultats(ident, "train", {})


def test_chaque_ouverture_du_test_est_comptee_et_tracee(registre: Registre) -> None:
    ident = registre.creer_essai(_config())
    assert registre.consulter_test(ident) == 1
    assert registre.consulter_test(ident) == 2
    assert registre.essai(ident)["consultations_test"] == 2
    assert [x["genre"] for x in registre.evenements(ident)].count("test_consulte") == 2


def test_lister_filtre_et_ordonne(registre: Registre) -> None:
    a = registre.creer_essai(_config(jeu="v1"))
    b = registre.creer_essai(_config(jeu="v2"))
    registre.changer_etat(a, "arrete")
    assert [e["id"] for e in registre.lister()] == [b, a]  # plus récent d'abord
    assert [e["id"] for e in registre.lister(jeu="v1")] == [a]
    assert [e["id"] for e in registre.lister(etat="en_file")] == [b]


def test_apres_un_arret_les_essais_orphelins_sont_interrompus(registre: Registre) -> None:
    vivant, mort, sans_pid = (registre.creer_essai(_config(graine=g)) for g in range(3))
    registre.changer_etat(vivant, "en_cours", pid=111)
    registre.changer_etat(mort, "en_cours", pid=222)
    registre.changer_etat(sans_pid, "en_cours")
    interrompus = registre.reprendre_apres_arret(lambda pid: pid == 111)
    assert sorted(interrompus) == sorted([mort, sans_pid])
    assert registre.essai(vivant)["etat"] == "en_cours"
    assert registre.essai(mort)["etat"] == "interrompu" and "redémarré" in registre.essai(mort)["erreur"]


def test_la_base_survit_a_une_reouverture_et_migre_une_seule_fois(tmp_path: Path) -> None:
    chemin = tmp_path / "labo.db"
    r = Registre(chemin)
    ident = r.creer_essai(_config())
    r.fermer()
    r2 = Registre(chemin)
    assert r2.essai(ident)["etat"] == "en_file"
    assert r2.creer_essai(_config()) == "E0002"
    r2.fermer()
    assert sqlite3.connect(chemin).execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)


def test_une_base_plus_recente_que_le_laboratoire_est_refusee(tmp_path: Path) -> None:
    chemin = tmp_path / "labo.db"
    Registre(chemin).fermer()
    c = sqlite3.connect(chemin)
    c.execute("PRAGMA user_version=99")
    c.close()
    with pytest.raises(RuntimeError, match="plus récente"):
        Registre(chemin)
