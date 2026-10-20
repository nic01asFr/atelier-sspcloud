"""Toute la chaîne, sans GPU : file → sous-processus → journal → résultats → test scellé."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from conftest import config_jouet, faire_variante
from laboratoire.executeur import Executeur
from laboratoire.projet import Racine, identifiant_sur
from laboratoire.registre import Registre
from laboratoire.travailleur import Travailleur
from laboratoire.variante import Variante, VarianteInvalide


def _attendre(travailleur: Travailleur, registre: Registre, ident: str, delai: float = 60.0) -> dict:
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        travailleur.tick()
        e = registre.essai(ident)
        if e["etat"] in ("termine", "echoue", "arrete", "interrompu"):
            return e
        time.sleep(0.05)
    raise AssertionError(f"{ident} n'a pas fini : {registre.essai(ident)['etat']}")


def test_un_essai_de_bout_en_bout(racine: Racine, registre: Registre) -> None:
    faire_variante(racine)
    exe = Executeur(racine, registre)
    travailleur = Travailleur(registre, exe)
    ident = registre.creer_essai(config_jouet())
    e = _attendre(travailleur, registre, ident)
    assert e["etat"] == "termine", e.get("erreur")
    assert e["code_sortie"] == 0 and e["pid"] and e["debut"] and e["fin"]
    # La validation est visible : le jouet sépare parfaitement clair et sombre.
    assert e["rappel_moyen_val"] == pytest.approx(1.0) and e["exactitude_val"] == pytest.approx(1.0)
    r = exe.resultats(ident)
    assert r["rapport"]["classes"] == ["clair", "sombre"] and r["triviales"]["majoritaire"]["rappel_moyen"] == pytest.approx(0.5)
    assert r["gain_sur_trivial"]["majoritaire"] == pytest.approx(0.5)
    # Les fichiers promis existent.
    d = racine.dossier_essai(ident)
    for nom in ("config.json", "journal.log", "metriques.csv", "resultats.json", "erreurs.json", "test_scelle.json"):
        assert (d / nom).is_file(), nom
    assert "[essai] terminé" in (d / "journal.log").read_text(encoding="utf-8")


def test_le_test_est_scelle_jusqu_a_son_ouverture_et_chaque_ouverture_est_comptee(racine: Racine, registre: Registre) -> None:
    faire_variante(racine)
    exe = Executeur(racine, registre)
    ident = registre.creer_essai(config_jouet())
    _attendre(Travailleur(registre, exe), registre, ident)
    e = registre.essai(ident)
    assert e["rappel_moyen_test"] is None and e["consultations_test"] == 0  # scellé : le tableau ne montre rien
    ouvert = exe.ouvrir_test(ident)
    assert ouvert["consultations"] == 1 and ouvert["rapport"]["rappel_moyen"] == pytest.approx(1.0)
    assert registre.essai(ident)["rappel_moyen_test"] == pytest.approx(1.0)
    assert exe.ouvrir_test(ident)["consultations"] == 2


def test_on_n_ouvre_pas_le_test_d_un_essai_qui_n_a_pas_fini(racine: Racine, registre: Registre) -> None:
    ident = registre.creer_essai(config_jouet())
    with pytest.raises(FileNotFoundError):
        Executeur(racine, registre).ouvrir_test(ident)


def test_un_echec_dit_pourquoi_et_la_file_continue(racine: Racine, registre: Registre) -> None:
    faire_variante(racine)
    exe = Executeur(racine, registre)
    travailleur = Travailleur(registre, exe)
    mauvais = registre.creer_essai(config_jouet(echec=True))
    bon = registre.creer_essai(config_jouet())
    e = _attendre(travailleur, registre, mauvais)
    assert e["etat"] == "echoue" and e["code_sortie"] == 1
    assert "échec demandé" in e["erreur"]  # la fin du journal, pas un code muet
    assert _attendre(travailleur, registre, bon)["etat"] == "termine"


def test_un_reglage_inconnu_est_refuse_par_la_famille_et_non_ignore(racine: Racine, registre: Registre) -> None:
    faire_variante(racine)
    exe = Executeur(racine, registre)
    ident = registre.creer_essai(config_jouet(vitese_max=True))  # faute de frappe
    e = _attendre(Travailleur(registre, exe), registre, ident)
    assert e["etat"] == "echoue" and "réglages inconnus" in e["erreur"]


def test_un_jeu_absent_fait_echouer_tout_de_suite_sans_occuper_la_file(racine: Racine, registre: Registre) -> None:
    exe = Executeur(racine, registre)
    ident = registre.creer_essai(config_jouet(jeu="n-existe-pas"))
    travailleur = Travailleur(registre, exe)
    travailleur.tick()
    e = registre.essai(ident)
    assert e["etat"] == "echoue" and "inutilisable" in e["erreur"] and e["pid"] is None


def test_un_seul_essai_a_la_fois(racine: Racine, registre: Registre) -> None:
    faire_variante(racine)
    exe = Executeur(racine, registre)
    travailleur = Travailleur(registre, exe, parallelisme=1)
    a = registre.creer_essai(config_jouet(lenteur_s=1.0))
    b = registre.creer_essai(config_jouet())
    travailleur.tick()
    assert registre.essai(a)["etat"] == "en_cours" and registre.essai(b)["etat"] == "en_file"
    _attendre(travailleur, registre, a)
    assert _attendre(travailleur, registre, b)["etat"] == "termine"


def test_arreter_un_essai_en_cours_tue_son_processus_et_garde_la_trace(racine: Racine, registre: Registre) -> None:
    faire_variante(racine)
    exe = Executeur(racine, registre)
    travailleur = Travailleur(registre, exe)
    ident = registre.creer_essai(config_jouet(lenteur_s=30))
    travailleur.tick()
    pid = registre.essai(ident)["pid"]
    from laboratoire.executeur import processus_vivant

    assert processus_vivant(pid)
    e = exe.arreter(ident)
    assert e["etat"] == "arrete" and "par la personne" in e["erreur"]
    assert not processus_vivant(pid)
    travailleur.tick()
    assert registre.essai(ident)["etat"] == "arrete"  # la surveillance ne le ressuscite pas


def test_arreter_un_essai_en_file(racine: Racine, registre: Registre) -> None:
    ident = registre.creer_essai(config_jouet())
    assert Executeur(racine, registre).arreter(ident)["etat"] == "arrete"


def test_le_battement_n_a_lieu_que_tant_qu_un_essai_tourne(racine: Racine, registre: Registre) -> None:
    faire_variante(racine)
    exe = Executeur(racine, registre)
    battements: list[int] = []
    t = [0.0]
    travailleur = Travailleur(registre, exe, battement=lambda: battements.append(1), intervalle_battement=100.0, horloge=lambda: t[0])
    travailleur.tick()
    assert battements == []  # rien ne tourne : pas de battement
    ident = registre.creer_essai(config_jouet(lenteur_s=30))
    travailleur.tick()
    assert battements == [1]
    t[0] = 50.0
    travailleur.tick()
    assert battements == [1]  # pas avant l'intervalle
    t[0] = 150.0
    travailleur.tick()
    assert battements == [1, 1]
    exe.arreter(ident)


def test_un_battement_qui_echoue_ne_tue_pas_l_essai(racine: Racine, registre: Registre) -> None:
    faire_variante(racine)
    exe = Executeur(racine, registre)

    def casse() -> None:
        raise RuntimeError("GPU absent")

    travailleur = Travailleur(registre, exe, battement=casse, intervalle_battement=0.0)
    ident = registre.creer_essai(config_jouet())
    assert _attendre(travailleur, registre, ident)["etat"] == "termine"


def test_un_essai_orphelin_apres_redemarrage_est_interrompu_et_la_file_repart(racine: Racine, registre: Registre) -> None:
    faire_variante(racine)
    orphelin = registre.creer_essai(config_jouet())
    registre.changer_etat(orphelin, "en_cours", pid=999999)  # un pid qui n'existe pas
    suivant = registre.creer_essai(config_jouet())
    exe = Executeur(racine, registre)
    travailleur = Travailleur(registre, exe)
    travailleur.demarrer(pause=0.05)
    try:
        fin = time.monotonic() + 60
        while time.monotonic() < fin and registre.essai(suivant)["etat"] != "termine":
            time.sleep(0.05)
    finally:
        travailleur.arreter()
    assert registre.essai(orphelin)["etat"] == "interrompu"
    assert registre.essai(suivant)["etat"] == "termine"


def test_un_manifeste_qui_sort_de_la_variante_est_refuse(racine: Racine) -> None:
    d = faire_variante(racine)
    m = d / "manifeste.csv"
    m.write_text(m.read_text(encoding="utf-8").replace("train/clair/c1__000.png", "../../../etc/passwd", 1), encoding="utf-8")
    with pytest.raises(VarianteInvalide, match="sort de la variante"):
        Variante(d)


def test_les_identifiants_ne_sortent_pas_de_la_racine() -> None:
    for mauvais in ("../x", "a/b", "", ".caché", "x" * 200, "a..b"):
        with pytest.raises(ValueError):
            identifiant_sur(mauvais)
    assert identifiant_sur("E0001") == "E0001" and identifiant_sur("droite-nombre_v2.1") == "droite-nombre_v2.1"
