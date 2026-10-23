"""Un essai de profondeur de bout en bout (modèles de test, sans GPU) et la constitution d'un jeu de panoramas (API simulée)."""

from __future__ import annotations

import io
import json
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from laboratoire.api import creer_app
from laboratoire.profondeur.panoramax import Candidat, construire_jeu, rechercher, une_par_sequence
from laboratoire.projet import Racine
from laboratoire.variante import Variante


def jpeg(largeur: int, hauteur: int, graine: int = 0) -> bytes:
    rng = np.random.default_rng(graine)
    a = (rng.random((hauteur, largeur, 3)) * 255).astype(np.uint8)
    t = io.BytesIO()
    Image.fromarray(a).save(t, "JPEG")
    return t.getvalue()


def fausse_api(items: list[dict]):
    corps = {"features": items}

    def ouvrir(url: str) -> bytes:
        if "/search" in url:
            return json.dumps(corps).encode()
        return jpeg(*{"pano": (512, 256), "carre": (400, 400)}[url.rsplit("/", 1)[1].split("-")[0]], graine=len(url))

    return ouvrir


def item(i: int, collection: str, licence: str = "etalab-2.0", type_image: str = "pano") -> dict:
    return {
        "id": f"it{i}", "collection": collection, "geometry": {"coordinates": [5.7 + i / 100, 45.1]},
        "properties": {"license": licence, "geovisio:producer": "asso", "datetime": "2025-05-01T10:00:00+00:00",
                       "pers:interior_orientation": {"field_of_view": 360 if type_image == "pano" else 90, "camera_model": "MAX2"}, "pers:pitch": 1.5},
        "assets": {"hd": {"href": f"https://x.test/{type_image}-{i}"}},
    }


def test_un_jeu_ne_garde_que_des_panoramas_ouverts_et_une_prise_par_sequence(racine: Racine) -> None:
    items = [item(1, "s1"), item(2, "s1"), item(3, "s2", licence="all-rights-reserved"), item(4, "s3", type_image="carre"), item(5, "s4"), item(6, "s5", licence="CC-BY-SA-4.0")]
    ouvrir = fausse_api(items)
    cands = rechercher("https://api.test", "5,45,6,46", ouvrir=ouvrir)
    assert [c.item for c in une_par_sequence(cands)] == ["it1", "it3", "it5", "it6", "it4"]  # les 360° d'abord, le champ de 90° en dernier
    resume = construire_jeu(racine, "jeu-test", cands, n=10, ouvrir=ouvrir, journal=lambda s: None)
    assert resume == {"jeu": "jeu-test", "gardes": 3, "ecartes": {"licence": 1, "pas_360": 1, "illisible": 0}}
    v = Variante(racine.dossier_variante("jeu-test"))
    assert [e.fichier.stem for e in v.echantillons("val")] == ["it1", "it5", "it6"]
    assert {e.groupe for e in v.echantillons("val")} == {"s1", "s4", "s5"}
    with pytest.raises(FileExistsError):
        construire_jeu(racine, "jeu-test", cands, n=1, ouvrir=ouvrir)


def test_la_selection_prend_plusieurs_prises_par_sequence_seulement_apres_en_avoir_pris_une_par_sequence() -> None:
    cands = [Candidat(f"a{i}", "A", "u", "etalab-2.0", "p", "d", 0, 0, 360.0) for i in range(30)] + [Candidat("b0", "B", "u", "etalab-2.0", "p", "d", 0, 0, 360.0)]
    choix = [c.item for c in une_par_sequence(cands, par_sequence=3, ecart=8)]
    assert choix == ["a0", "b0", "a8", "a16"]  # B n'a qu'une prise ; A en donne trois, espacées


def _attendre(client: TestClient, ident: str, delai: float = 120.0) -> dict:
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        e = client.get(f"/api/essais/{ident}").json()["essai"]
        if e["etat"] in ("termine", "echoue", "arrete"):
            return e
        time.sleep(0.2)
    raise AssertionError("pas fini")


def config(modele: str, **reglages) -> dict:
    return {"jeu": "jeu-test", "methode": {"famille": "profondeur", "modele": modele, "reglages": {"largeur": 128, "pas_cap": 45, "tangage_haut": 0, "panoramas_max": 2, **reglages}}}


@pytest.fixture()
def client(racine: Racine):
    ouvrir = fausse_api([item(i, f"s{i}") for i in range(1, 4)])
    construire_jeu(racine, "jeu-test", rechercher("https://api.test", "5,45,6,46", ouvrir=ouvrir), n=3, ouvrir=ouvrir, journal=lambda s: None)
    with TestClient(creer_app(racine, demarrer_travailleur=True)) as c:
        yield c


def test_un_essai_de_profondeur_ecrit_cartes_apercus_et_mesures(client: TestClient, racine: Racine) -> None:
    ident = client.post("/api/essais", json=config("plan")).json()["id"]
    e = _attendre(client, ident)
    assert e["etat"] == "termine", e.get("erreur")
    d = client.get(f"/api/essais/{ident}").json()
    r = d["resultats"]
    assert r["tache"] == "profondeur" and r["rapport"]["panoramas"] == 2 and r["rapport"]["vues_par_panorama"] == 8
    assert r["rapport"]["incoherence_mediane"] is not None and r["rapport"]["incoherence_mediane"] < 0.3  # le sol plat est cohérent d'une vue à l'autre
    dossier = racine.dossier_essai(ident)
    npz = np.load(dossier / "profondeur" / "it1.npz")
    assert npz["q"].shape[0] == 8 and npz["masque"].dtype == bool and list(npz["vues"])[0] == "c000_t00"
    assert (dossier / "apercus" / "it1" / "c000_t00.jpg").stat().st_size > 500
    assert len(d["metriques"]) == 2 and d["metriques"][0]["panorama"] == 1.0


def test_un_modele_de_test_sans_relief_est_moins_coherent_que_le_sol_plat(client: TestClient) -> None:
    a = client.post("/api/essais", json=config("plan")).json()["id"]
    b = client.post("/api/essais", json=config("contraste")).json()["id"]
    _attendre(client, a)
    _attendre(client, b)
    ra = client.get(f"/api/essais/{a}").json()["resultats"]["rapport"]["incoherence_mediane"]
    rb = client.get(f"/api/essais/{b}").json()["resultats"]["rapport"]["incoherence_mediane"]
    assert ra < rb


def test_un_modele_de_panorama_est_ramene_aux_memes_vues_et_aussi_coherent_que_le_modele_par_vue(client: TestClient) -> None:
    a = client.post("/api/essais", json=config("plan")).json()["id"]
    b = client.post("/api/essais", json=config("plan-panorama")).json()["id"]
    assert _attendre(client, a)["etat"] == "termine" and _attendre(client, b)["etat"] == "termine"
    ra = client.get(f"/api/essais/{a}").json()["resultats"]["rapport"]
    rb = client.get(f"/api/essais/{b}").json()["resultats"]["rapport"]
    assert rb["vues_par_panorama"] == ra["vues_par_panorama"] and rb["incoherence_mediane"] < 0.3  # la même géométrie, vue de deux façons


def test_un_reglage_inconnu_ou_un_modele_inconnu_est_refuse(client: TestClient) -> None:
    assert client.post("/api/essais", json=config("plan", fov_typo=1)).status_code == 422
    assert client.post("/api/essais", json=config("inconnu")).status_code == 422
    assert client.post("/api/essais", json=config("plan", fov=500)).status_code == 422
    assert client.post("/api/essais", json=config("plan", pas_cap=90)).status_code == 422  # des vues qui ne se recouvrent pas ne se comparent pas


# -- le vote à l'aveugle, la synthèse, les rôles ------------------------------


@pytest.fixture()
def labo(racine: Racine):
    """Un laboratoire avec jeton, trois porteurs (admin, relecteur, valideur) et deux modèles terminés sur le même jeu."""
    ouvrir = fausse_api([item(i, f"s{i}") for i in range(1, 5)])
    construire_jeu(racine, "jeu-test", rechercher("https://api.test", "5,45,6,46", ouvrir=ouvrir), n=4, ouvrir=ouvrir, journal=lambda s: None)
    (racine.chemin / "valideurs.json").write_text(json.dumps({"Mathieu": {"jeton": "tm", "role": "relecteur"}, "Julie": "tj"}), encoding="utf-8")
    with TestClient(creer_app(racine, jeton="adm", demarrer_travailleur=True, tache="profondeur")) as c:
        admin = {"Authorization": "Bearer adm"}
        ids = [c.post("/api/essais", json=config(m, panoramas_max=4), headers=admin).json()["id"] for m in ("plan", "contraste")]
        for i in ids:
            fin = time.monotonic() + 120
            while time.monotonic() < fin and c.get(f"/api/essais/{i}", headers=admin).json()["essai"]["etat"] not in ("termine", "echoue"):
                time.sleep(0.2)
        yield c, racine


def h(jeton: str) -> dict:
    return {"Authorization": f"Bearer {jeton}"}


def test_la_paire_est_anonyme_et_le_vote_se_range_au_nom_du_votant(labo) -> None:
    c, _ = labo
    assert c.get("/api/tache", headers=h("tj")).json() == {"tache": "profondeur", "auteur": "Julie", "role": "valideur"}
    p = c.get("/api/profondeur/paire?jeu=jeu-test", headers=h("tj")).json()
    assert set(p) >= {"jeton", "panorama", "vue", "restantes"} and "modele" not in json.dumps(p) and "plan" not in json.dumps(p)
    for cote in ("source", "gauche", "droite"):
        r = c.get(f"/api/profondeur/paire/{p['jeton']}/{cote}.jpg", headers=h("tj"))
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert c.get(f"/api/profondeur/paire/{p['jeton']}/gauche.jpg", headers=h("tm")).status_code == 403  # la paire est à Julie
    assert c.post(f"/api/profondeur/paire/{p['jeton']}/vote", json={"choix": "n'importe quoi"}, headers=h("tj")).status_code == 422
    assert c.post(f"/api/profondeur/paire/{p['jeton']}/vote", json={"choix": "gauche"}, headers=h("tj")).status_code == 201
    assert c.get("/api/profondeur/votes/moi?jeu=jeu-test", headers=h("tj")).json()["total"] == 1


def test_une_personne_ne_revoit_pas_une_paire_et_les_moins_jugees_passent_d_abord(labo) -> None:
    c, _ = labo
    vues = set()
    for _ in range(12):
        p = c.get("/api/profondeur/paire?jeu=jeu-test", headers=h("tj")).json()
        assert (p["panorama"], p["vue"]) not in vues  # un seul couple de modèles : jamais deux fois la même vue
        vues.add((p["panorama"], p["vue"]))
        c.post(f"/api/profondeur/paire/{p['jeton']}/vote", json={"choix": "egal"}, headers=h("tj"))
    p = c.get("/api/profondeur/paire?jeu=jeu-test", headers=h("tm")).json()  # Mathieu : une vue que Julie a déjà jugée passe après les non jugées
    assert (p["panorama"], p["vue"]) not in vues


def test_un_valideur_ne_voit_jamais_les_modeles_un_relecteur_voit_tout(labo) -> None:
    c, _ = labo
    for chemin in ("/api/profondeur/synthese?jeu=jeu-test", "/api/profondeur/jeux", "/api/profondeur/jeu/jeu-test/panoramas", "/api/essais"):
        assert c.get(chemin, headers=h("tj")).status_code == 403, chemin
    s = c.get("/api/profondeur/synthese?jeu=jeu-test", headers=h("tm")).json()
    assert {m["modele"] for m in s["modeles"]} == {"plan", "contraste"} and s["classement"]["fiable"] is False
    assert c.post("/api/essais", json=config("plan"), headers=h("tm")).status_code == 403  # lecture seule, hors vote et commentaires
    assert c.get("/api/profondeur/votes/export?jeu=jeu-test", headers=h("tm")).status_code == 403
    assert c.get("/api/profondeur/votes/export?jeu=jeu-test", headers=h("adm")).status_code == 200


def test_le_classement_suit_les_votes_et_un_vote_s_annule_par_une_ligne(labo) -> None:
    c, racine = labo
    votes = c.app.state.votes
    essais = {e["modele"]: e["id"] for e in c.get("/api/essais", headers=h("adm")).json()}
    for k in range(16):  # 4 panoramas × 4 vues : « plan » l'emporte presque toujours, avec quelques égalités
        gauche_est_plan = k % 2 == 0
        choix = "egal" if k % 8 == 7 else ("gauche" if gauche_est_plan else "droite")
        votes.voter(
            jeu="jeu-test", panorama=f"it{k % 4 + 1}", vue=f"c{(k // 4) * 45:03d}_t00", votant="Mathieu", choix=choix,
            modele_gauche="plan" if gauche_est_plan else "contraste", modele_droite="contraste" if gauche_est_plan else "plan",
            essai_gauche=essais["plan" if gauche_est_plan else "contraste"], essai_droite=essais["contraste" if gauche_est_plan else "plan"],
        )
    s = c.get("/api/profondeur/synthese?jeu=jeu-test", headers=h("tm")).json()
    assert s["classement"]["modeles"]["plan"]["rang"] == 1 and s["classement"]["fiable"] is False  # 4 panoramas : trop peu pour s'y fier
    assert s["votes"]["par_votant"] == {"Mathieu": 16}
    dernier = c.get("/api/profondeur/votes/moi?jeu=jeu-test", headers=h("tm")).json()["dernier"]
    assert c.post(f"/api/profondeur/votes/{dernier}/annuler", headers=h("tj")).status_code == 422  # pas son vote
    assert c.post(f"/api/profondeur/votes/{dernier}/annuler", headers=h("tm")).status_code == 200
    assert c.post(f"/api/profondeur/votes/{dernier}/annuler", headers=h("tm")).status_code == 422  # déjà annulé
    assert c.get("/api/profondeur/votes/moi?jeu=jeu-test", headers=h("tm")).json()["total"] == 15
    s = c.get("/api/profondeur/synthese?jeu=jeu-test", headers=h("tm")).json()
    assert s["classement"]["jugements"] == 15 and s["accord"]["contraste|plan"] is not None
    import sqlite3

    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(racine.chemin / "donnees" / "votes.db").execute("DELETE FROM votes")
