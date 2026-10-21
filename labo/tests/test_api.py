"""Le service : ce que la page et l'agent en voient, et ce qu'il refuse."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from conftest import faire_variante
from laboratoire.__main__ import est_boucle_locale, main
from laboratoire.api import creer_app
from laboratoire.projet import Racine

CONFIG = {"jeu": "v1", "methode": {"famille": "jouet", "modele": "centres", "imgsz": 8, "epochs": 1}}


@pytest.fixture()
def client(racine: Racine):
    faire_variante(racine)
    with TestClient(creer_app(racine, demarrer_travailleur=True)) as c:
        yield c


def _attendre(client: TestClient, ident: str, etats=("termine", "echoue", "arrete"), delai: float = 60.0) -> dict:
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        e = client.get(f"/api/essais/{ident}").json()["essai"]
        if e["etat"] in etats:
            return e
        time.sleep(0.1)
    raise AssertionError("pas fini")


def test_lancer_un_essai_et_lire_tout_ce_qu_il_a_produit(client: TestClient) -> None:
    r = client.post("/api/essais", json=CONFIG)
    assert r.status_code == 201
    ident = r.json()["id"]
    assert _attendre(client, ident)["etat"] == "termine"
    d = client.get(f"/api/essais/{ident}").json()
    assert d["essai"]["rappel_moyen_val"] == pytest.approx(1.0)
    assert d["resultats"]["rapport"]["classes"] == ["clair", "sombre"]
    assert d["metriques"] and d["metriques"][0]["epoque"] == 1.0
    assert d["test"] == {"scelle": True, "consultations": 0}
    assert d["essai"]["rappel_moyen_test"] is None  # scellé
    assert [e["id"] for e in client.get("/api/essais").json()] == [ident]


def test_le_journal_se_lit_par_morceaux(client: TestClient) -> None:
    ident = client.post("/api/essais", json=CONFIG).json()["id"]
    _attendre(client, ident)
    premier = client.get(f"/api/essais/{ident}/journal").json()
    assert "[essai] terminé" in premier["texte"] and premier["suivant"] > 0
    suite = client.get(f"/api/essais/{ident}/journal", params={"depuis": premier["suivant"]}).json()
    assert suite == {"texte": "", "suivant": premier["suivant"]}


def test_ouvrir_le_test_exige_une_confirmation_et_compte(client: TestClient) -> None:
    ident = client.post("/api/essais", json=CONFIG).json()["id"]
    _attendre(client, ident)
    sans = client.post(f"/api/essais/{ident}/ouvrir-test")
    assert sans.status_code == 428 and "engageante" in sans.json()["detail"]
    assert client.get(f"/api/essais/{ident}").json()["essai"]["consultations_test"] == 0
    ok = client.post(f"/api/essais/{ident}/ouvrir-test", json={"confirmer": True})
    assert ok.status_code == 200 and ok.json()["consultations"] == 1
    assert client.get(f"/api/essais/{ident}").json()["essai"]["rappel_moyen_test"] == pytest.approx(1.0)


def test_un_essai_refuse_a_la_creation_dit_pourquoi(client: TestClient) -> None:
    faute = {**CONFIG, "methode": {**CONFIG["methode"], "reglages": {"vitese": 1}}}
    r = client.post("/api/essais", json=faute)
    assert r.status_code == 422 and "réglages inconnus" in r.json()["erreur"]
    inconnue = {**CONFIG, "methode": {**CONFIG["methode"], "famille": "magie"}}
    assert client.post("/api/essais", json=inconnue).status_code == 422
    assert client.post("/api/essais", json={**CONFIG, "jeu": "absent"}).status_code == 422
    assert client.post("/api/essais", json={**CONFIG, "vitesse": "max"}).status_code == 422  # champ inventé
    assert client.get("/api/essais").json() == []  # rien n'est entré dans la file


def test_les_identifiants_dangereux_sont_refuses(client: TestClient) -> None:
    for mauvais in ("..", ".hidden", "a..b"):
        assert client.get(f"/api/essais/{mauvais}").status_code in (400, 404)
    assert client.get("/api/essais/E9999").status_code == 404


def test_comparer_deux_essais(client: TestClient) -> None:
    a = client.post("/api/essais", json=CONFIG).json()["id"]
    b = client.post("/api/essais", json={**CONFIG, "graine": 1}).json()["id"]
    _attendre(client, a), _attendre(client, b)
    r = client.get("/api/comparer", params={"ids": f"{a},{b}"}).json()
    assert [x["essai"]["id"] for x in r] == [a, b]
    assert client.get("/api/comparer", params={"ids": a}).status_code == 422


def test_arreter_un_essai_en_cours(client: TestClient) -> None:
    lent = {**CONFIG, "methode": {**CONFIG["methode"], "reglages": {"lenteur_s": 30}}}
    ident = client.post("/api/essais", json=lent).json()["id"]
    _attendre(client, ident, etats=("en_cours",))
    r = client.post(f"/api/essais/{ident}/arreter")
    assert r.status_code == 200 and r.json()["etat"] == "arrete"
    assert client.post(f"/api/essais/{ident}/arreter").status_code == 409  # déjà arrêté : transition refusée


def test_les_variantes_sont_listees_avec_leurs_effectifs(client: TestClient, racine: Racine) -> None:
    (racine.variantes / "cassee").mkdir()
    v = {x["id"]: x for x in client.get("/api/variantes").json()}
    assert v["v1"]["classes"] == ["clair", "sombre"] and v["v1"]["effectifs"]["train"] == {"clair": 12, "sombre": 12}
    assert v["v1"]["groupes"] == {"train": 2, "val": 1, "test": 1}
    assert "manifeste" in v["cassee"]["invalide"]


def test_l_etat_du_pod(client: TestClient) -> None:
    p = client.get("/api/pod").json()
    assert p["essais_en_cours"] == 0 and p["disque"]["libre_go"] >= 0 and p["battement_actif"] is False


def test_avec_un_jeton_tout_est_ferme_sauf_la_sante(racine: Racine) -> None:
    faire_variante(racine)
    with TestClient(creer_app(racine, jeton="secret", demarrer_travailleur=False)) as c:
        assert c.get("/sante").status_code == 200
        for chemin in ("/", "/api/essais", "/api/pod", "/web/index.html"):
            assert c.get(chemin).status_code == 401, chemin
        assert c.get("/api/essais", headers={"Authorization": "Bearer faux"}).status_code == 401
        assert c.get("/api/essais", headers={"Authorization": "Bearer secret"}).status_code == 200
        c.cookies.set("labo_jeton", "secret")
        assert c.get("/").status_code == 200
        assert c.get("/api/docs").status_code == 404  # pas de documentation interactive quand on est protégé


def test_le_service_refuse_de_demarrer_ouvert_sans_jeton(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("LABO_JETON", raising=False)
    assert main(["--racine", str(tmp_path), "--hote", "0.0.0.0"]) == 2
    assert est_boucle_locale("127.0.0.1") and est_boucle_locale("localhost") and not est_boucle_locale("0.0.0.0")
    assert not est_boucle_locale("10.233.1.2")


def test_le_service_lit_le_brut_indique_par_l_environnement(tmp_path, monkeypatch) -> None:
    """Régression : `python -m laboratoire` ignorait LABO_BRUT et cherchait le brut dans <racine>/donnees/brut."""
    import laboratoire.__main__ as principal

    pris = {}
    monkeypatch.setattr(principal.uvicorn, "run", lambda app, **kw: pris.update(racine=app.state.racine))
    monkeypatch.setenv("LABO_BRUT", str(tmp_path / "ailleurs"))
    assert principal.main(["--racine", str(tmp_path / "labo")]) == 0
    assert pris["racine"].brut == tmp_path / "ailleurs"
    monkeypatch.delenv("LABO_BRUT")
    assert principal.main(["--racine", str(tmp_path / "labo")]) == 0
    assert pris["racine"].brut == tmp_path / "labo" / "donnees" / "brut"
