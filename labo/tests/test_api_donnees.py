"""Les routes des données : aperçu sans écriture, construction, explorateur sûr, corrections qui ne touchent pas au brut."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from laboratoire.api import creer_app
from laboratoire.projet import Racine

RECETTE = {"cote": "droite", "tache": "nombre", "reequilibrage": {"actif": False}}


@pytest.fixture()
def client(racine: Racine):
    for g in range(12):
        for n in (0, 1, 2):
            for k in range(6):
                f = racine.brut / f"V/g{g}/x/droite/{n}/i{k}.jpeg"
                f.parent.mkdir(parents=True, exist_ok=True)
                im = Image.new("RGB", (36, 24), (n * 80, 90, 90))
                im.paste((g * 20, k * 40, 7), (0, 0, 16, 16))  # une image distincte : deux images identiques seraient une fuite (contrôle fuite_contenu)
                im.save(f)
    with TestClient(creer_app(racine, demarrer_travailleur=False)) as c:
        yield c


def _construire(client: TestClient, recette=RECETTE) -> str:
    r = client.post("/api/variantes", json=recette)
    assert r.status_code == 202
    ident = r.json()["id"]
    fin = time.monotonic() + 30
    while time.monotonic() < fin:
        d = client.get(f"/api/variantes/{ident}").json()
        if "classes" in d:
            return ident
        assert "erreur" not in d.get("construction", {}), d
        time.sleep(0.05)
    raise AssertionError("construction trop longue")


def test_le_brut_est_resume(client: TestClient) -> None:
    d = client.get("/api/brut").json()
    assert d["resume"]["images"] == 12 * 3 * 6 and d["resume"]["collections"] == 12 and d["anomalies"] == []


def test_l_apercu_n_ecrit_rien(client: TestClient, racine: Racine) -> None:
    d = client.post("/api/variantes/apercu", json=RECETTE).json()
    assert d["classes"] == ["0", "1", "2"] and d["constructible"] is True and d["existe"] is False
    assert sum(d["groupes"].values()) == 12
    assert not any(racine.variantes.iterdir())


def test_une_recette_inconnue_est_refusee(client: TestClient) -> None:
    assert client.post("/api/variantes/apercu", json={**RECETTE, "pirate": 1}).status_code == 422
    assert client.post("/api/variantes/apercu", json={"cote": "haut", "tache": "nombre"}).status_code == 422


def test_construire_puis_explorer_comparer(client: TestClient) -> None:
    ident = _construire(client)
    assert client.post("/api/variantes", json=RECETTE).json().get("deja_construite") is True  # même recette, même variante
    d = client.get(f"/api/variantes/{ident}").json()
    assert d["recette"]["cote"] == "droite" and d["classes"] == ["0", "1", "2"]
    assert [v["id"] for v in client.get("/api/variantes").json()] == [ident]
    page = client.get(f"/api/variantes/{ident}/images", params={"jeu": "train", "classe": "1", "limite": 5}).json()
    assert len(page["images"]) == 5 and page["total"] > 5 and all(i["classe"] == "1" for i in page["images"])
    vignette = client.get(f"/api/variantes/{ident}/image", params={"fichier": page["images"][0]["fichier"], "largeur": 16})
    assert vignette.status_code == 200 and vignette.headers["content-type"] == "image/jpeg"
    autre = _construire(client, {**RECETTE, "preparation": "masque"})
    cmp = client.get("/api/comparer-variantes", params={"a": ident, "b": autre}).json()
    assert cmp["differences"] == {"preparation": ["rognage", "masque"]}


def test_l_explorateur_ne_sort_pas_de_la_variante(client: TestClient, racine: Racine) -> None:
    ident = _construire(client)
    (racine.chemin / "secret.png").write_bytes(b"x")
    for mauvais in ("../../../secret.png", "/etc/passwd", "manifeste.csv", "../" + ident + "/manifeste.csv"):
        assert client.get(f"/api/variantes/{ident}/image", params={"fichier": mauvais}).status_code == 404
    assert client.get("/api/variantes/..%2F..%2Fx/images").status_code in (400, 404)
    assert client.get(f"/api/variantes/{ident}/images", params={"jeu": "pirate"}).status_code == 422


def test_une_correction_s_ecrit_a_cote_du_brut_et_change_la_variante_suivante(client: TestClient, racine: Racine) -> None:
    avant = sorted(p.read_bytes() for p in racine.brut.rglob("*.jpeg"))[:3]
    chemin = "V/g0/x/droite/0/i0.jpeg"
    assert client.post("/api/corrections", json={"chemin": chemin, "decision": "douteuse", "note": "flou"}).status_code == 201
    assert client.post("/api/corrections", json={"chemin": "V/inconnue.jpeg", "decision": "1"}).status_code == 404
    assert client.post("/api/corrections", json={"chemin": chemin, "decision": "1\nX"}).status_code == 422
    assert client.get("/api/corrections").json() == [{"chemin": chemin, "decision": "douteuse", "note": "flou"}]
    assert sorted(p.read_bytes() for p in racine.brut.rglob("*.jpeg"))[:3] == avant  # le brut n'a pas bougé
    d = client.post("/api/variantes/apercu", json=RECETTE).json()
    assert d["ecartes"] == {"étiquette douteuse écartée": 1}
    sans = client.post("/api/variantes/apercu", json={**RECETTE, "corrections": False}).json()
    assert sans["ecartes"] == {} and sans["id"] != d["id"]


def test_les_routes_de_donnees_exigent_le_jeton(racine: Racine) -> None:
    with TestClient(creer_app(racine, jeton="s", demarrer_travailleur=False)) as c:
        assert c.get("/api/brut").status_code == 401
        assert c.get("/api/brut", headers={"Authorization": "Bearer s"}).status_code == 200
