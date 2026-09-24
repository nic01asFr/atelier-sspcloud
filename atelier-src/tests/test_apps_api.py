"""Les routes `/v1/apps` de l'Atelier et le renvoi des artefacts vers le second hôte.

Côté Atelier, rien de ce qu'un artefact sert ne passe : « ouvrir » ne rend
qu'un 302 vers l'hôte des applications, porteur d'un code d'usage unique
rattaché à la session owner. Ces tests suivent ce renvoi jusqu'au code, et
vérifient qu'il ne naît que d'une session de navigateur.

Les artefacts de ces tests ne lancent aucun processus (le serveur n'est pas
démarré) : rien ne dépend de la plateforme. Le cycle des processus est
éprouvé à part (`test_apps_superviseur.py`, `test_apps_hote.py`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier import artifacts as art
from mcp_gateway.atelier.api import build_app
from mcp_gateway.atelier.config import AtelierSettings

APPS = "https://apps.test"
INTERFACE = {"X-Atelier-Interface": "1"}
ICI = {**INTERFACE, "Sec-Fetch-Site": "same-origin"}


def preparer_projet(settings: AtelierSettings) -> Path:
    projet = settings.projects_dir / "demo"
    art_ = projet / "artifacts"
    (art_ / "site").mkdir(parents=True)
    (art_ / "site" / "index.html").write_text("<h1>site</h1>", encoding="utf-8")
    (art_ / "serveur").mkdir()
    (art_ / "serveur" / "artefact.json").write_text(
        json.dumps({"version": 1, "titre": "Le serveur", "commande": ["python3", "app.py", "--port", "{port}"]}),
        encoding="utf-8",
    )
    (art_ / "serveur" / "app.py").write_text("CLE = 'ne pas servir'", encoding="utf-8")
    (art_ / "casse").mkdir()
    (art_ / "casse" / "artefact.json").write_text(
        json.dumps({"version": 1, "commande": ["x"], "port": 80}), encoding="utf-8"
    )
    (art_ / "corpus").mkdir()
    (art_ / "page.html").write_text("<p>page</p>", encoding="utf-8")
    (art_ / "corpus" / ".corpus").write_text("", encoding="utf-8")
    (art_ / "corpus" / "a.md").write_text("# a", encoding="utf-8")
    return projet


def atelier_avec(tmp_path: Path, apps_public_url: str) -> Iterator[TestClient]:
    settings = AtelierSettings(
        work_dir=tmp_path / "work", apps_public_url=apps_public_url, public_url="https://testserver"
    )
    settings.ensure_dirs()
    preparer_projet(settings)
    with TestClient(build_app(settings=settings, use_fake=True), base_url="https://testserver") as client:
        yield client


@pytest.fixture()
def atelier_apps(tmp_path: Path) -> Iterator[TestClient]:
    yield from atelier_avec(tmp_path, APPS)


@pytest.fixture()
def atelier_seul(tmp_path: Path) -> Iterator[TestClient]:
    yield from atelier_avec(tmp_path, "")


def cle(client: TestClient) -> str:
    return client.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()


def porteur(client: TestClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {cle(client)}"}


def connecter(client: TestClient) -> str:
    r = client.post("/v1/auth/cookie", headers=porteur(client))
    assert r.status_code == 200
    return client.cookies.get("__Host-atelier_session")


def code_du_renvoi(client: TestClient, reponse) -> tuple[str, str]:
    """Le code porté par le 302, consommé comme le ferait l'hôte des applications."""
    assert reponse.status_code == 302, reponse.text
    vers = urlsplit(reponse.headers["location"])
    assert f"{vers.scheme}://{vers.netloc}" == APPS
    assert vers.path == "/_atelier/entree"
    assert reponse.headers["referrer-policy"] == "no-referrer"
    code = parse_qs(vers.query)["code"][0]
    trouve = client.app.state.apps.passage.consommer_code(code)
    assert trouve is not None
    return trouve.portee, trouve.destination


def test_la_liste_montre_les_artefacts_et_les_manifestes_fautifs(atelier_apps: TestClient) -> None:
    connecter(atelier_apps)
    r = atelier_apps.get("/v1/apps", params={"slug": "demo"}, headers=INTERFACE)
    assert r.status_code == 200
    corps = r.json()
    assert corps["expose"] is True and corps["origine"] == APPS
    fiches = {f["nom"]: f for f in corps["artefacts"]}
    assert fiches["site"]["mode"] == "autonome" and fiches["site"]["etat"] == "statique"
    assert fiches["site"]["url"] == f"{APPS}/demo/site/"
    assert fiches["serveur"]["mode"] == "serveur" and fiches["serveur"]["etat"] == "arrete"
    assert fiches["serveur"]["ouvrir"] == "/v1/apps/demo/serveur/ouvrir"
    assert fiches["casse"]["etat"] == "invalide" and "port" in fiches["casse"]["erreur"]
    # Sans en-tête d'interface, le cookie seul ne suffit pas.
    assert atelier_apps.get("/v1/apps").status_code == 401
    assert atelier_apps.get("/v1/apps/inconnu", headers=INTERFACE).status_code == 404


def test_ouvrir_renvoie_vers_l_hote_avec_un_code(atelier_apps: TestClient) -> None:
    connecter(atelier_apps)
    r = atelier_apps.get("/v1/apps/demo/site/ouvrir", follow_redirects=False)
    assert code_du_renvoi(atelier_apps, r) == ("demo", "/demo/site/")


def test_ouvrir_exige_une_session_de_navigateur(atelier_apps: TestClient) -> None:
    r = atelier_apps.get("/v1/apps/demo/site/ouvrir", headers=porteur(atelier_apps), follow_redirects=False)
    assert r.status_code == 400
    assert atelier_apps.get("/v1/apps/demo/site/ouvrir", follow_redirects=False).status_code == 401


def test_sans_second_hote(atelier_seul: TestClient) -> None:
    connecter(atelier_seul)
    # Un artefact autonome s'ouvre sur l'adresse de secours ; un serveur, non.
    r = atelier_seul.get("/v1/apps/demo/site/ouvrir", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/v1/artifacts/demo/site/"
    assert atelier_seul.get("/v1/apps/demo/serveur/ouvrir", follow_redirects=False).status_code == 409
    corps = atelier_seul.get("/v1/apps", params={"slug": "demo"}, headers=INTERFACE).json()
    assert corps["expose"] is False
    fiches = {f["nom"]: f for f in corps["artefacts"]}
    assert fiches["serveur"]["ouvrir"] == ""
    assert fiches["site"]["url"] == "/v1/artifacts/demo/site/"


def test_un_serveur_n_est_jamais_servi_comme_des_fichiers(atelier_seul: TestClient) -> None:
    connecter(atelier_seul)
    r = atelier_seul.get("/v1/artifacts/demo/serveur/app.py", headers=porteur(atelier_seul))
    assert r.status_code == 409
    assert "ne pas servir" not in r.text
    r = atelier_seul.get("/v1/artifacts/demo/serveur/artefact.json", headers=porteur(atelier_seul))
    assert r.status_code in (404, 409)


def test_l_entree_valide_la_destination(atelier_apps: TestClient) -> None:
    connecter(atelier_apps)
    r = atelier_apps.get("/v1/apps/entree", params={"suite": "/demo/site/x?y=1"}, follow_redirects=False)
    assert code_du_renvoi(atelier_apps, r) == ("demo", "/demo/site/x?y=1")
    for suite in ("//evil.test/demo/site/", "https://evil.test/", "/_atelier/entree", "/../x/y", "/demo/site/\\x"):
        r = atelier_apps.get("/v1/apps/entree", params={"suite": suite}, follow_redirects=False)
        assert r.status_code == 400, suite


def test_fermer_la_session_ferme_celles_des_applications(atelier_apps: TestClient) -> None:
    connecter(atelier_apps)
    passage = atelier_apps.app.state.apps.passage
    r = atelier_apps.get("/v1/apps/demo/site/ouvrir", follow_redirects=False)
    code = parse_qs(urlsplit(r.headers["location"]).query)["code"][0]
    session = passage.ouvrir(passage.consommer_code(code))
    assert passage.session(session.id) is not None
    atelier_apps.delete("/v1/auth/cookie", headers={"Sec-Fetch-Site": "same-origin"})
    assert passage.session(session.id) is None


def test_faire_tourner_la_cle_ferme_les_sessions_des_applications(atelier_apps: TestClient) -> None:
    connecter(atelier_apps)
    passage = atelier_apps.app.state.apps.passage
    r = atelier_apps.get("/v1/apps/demo/site/ouvrir", follow_redirects=False)
    code = parse_qs(urlsplit(r.headers["location"]).query)["code"][0]
    session = passage.ouvrir(passage.consommer_code(code))
    r = atelier_apps.post("/v1/auth/rotate", headers=porteur(atelier_apps))
    assert r.status_code == 200
    assert passage.session(session.id) is None


def test_creer_un_artefact_sans_conflit(atelier_apps: TestClient) -> None:
    r = atelier_apps.post(
        "/v1/apps/demo/carte/creer", params={"mode": "serveur", "auteur": "conv-a"}, headers=porteur(atelier_apps)
    )
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "serveur" and r.json()["auteur"] == "conv-a"
    dossier = atelier_apps.app.state.settings.projects_dir / "demo" / "artifacts" / "carte"
    assert json.loads((dossier / "artefact.json").read_text(encoding="utf-8"))["commande"][-1] == "{port}"
    # Le même nom, une seconde fois : refusé, rien n'est écrasé.
    r = atelier_apps.post(
        "/v1/apps/demo/carte/creer", params={"mode": "autonome", "auteur": "conv-b"}, headers=porteur(atelier_apps)
    )
    assert r.status_code == 409
    assert (dossier / ".auteur").read_text(encoding="utf-8").strip() == "conv-a"
    for nom in ("Carte", "_atelier", "a.b"):
        assert atelier_apps.post(f"/v1/apps/demo/{nom}/creer", headers=porteur(atelier_apps)).status_code in (400, 404)


def test_un_agent_n_arrete_pas_l_artefact_d_un_autre(atelier_apps: TestClient) -> None:
    atelier_apps.post("/v1/apps/demo/carte/creer", params={"auteur": "conv-a"}, headers=porteur(atelier_apps))
    base = "/v1/apps/demo/carte"
    r = atelier_apps.post(f"{base}/arreter", params={"auteur": "conv-b"}, headers=porteur(atelier_apps))
    assert r.status_code == 409 and "conv-a" in r.json()["detail"]
    r = atelier_apps.post(f"{base}/arreter", params={"auteur": "conv-b", "forcer": "true"}, headers=porteur(atelier_apps))
    assert r.status_code == 200
    r = atelier_apps.post(f"{base}/arreter", params={"auteur": "conv-a"}, headers=porteur(atelier_apps))
    assert r.status_code == 200
    # L'interface agit pour le propriétaire, sans cette règle.
    connecter(atelier_apps)
    assert atelier_apps.post(f"{base}/arreter", headers=ICI).status_code == 200


def test_demarrer_un_artefact_autonome_ne_lance_rien(atelier_apps: TestClient) -> None:
    connecter(atelier_apps)
    r = atelier_apps.post("/v1/apps/demo/site/demarrer", headers=ICI)
    assert r.status_code == 200 and r.json()["etat"] == "statique"
    assert atelier_apps.app.state.apps.superviseur.lister() == []
    assert atelier_apps.post("/v1/apps/demo/casse/demarrer", headers=ICI).status_code == 422
    # Venue d'un voisin du même site, l'écriture est refusée avant la route.
    r = atelier_apps.post("/v1/apps/demo/site/demarrer", headers={**INTERFACE, "Sec-Fetch-Site": "same-site"})
    assert r.status_code == 403


def test_le_journal_est_du_texte(atelier_apps: TestClient) -> None:
    connecter(atelier_apps)
    journal = atelier_apps.app.state.settings.work_dir / "logs" / "apps" / "demo"
    journal.mkdir(parents=True)
    (journal / "serveur.log").write_text("<script>alert(1)</script>\nligne 2\n", encoding="utf-8")
    r = atelier_apps.get("/v1/apps/demo/serveur/journal", params={"lignes": 1}, headers=INTERFACE)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.text == "ligne 2"


def test_les_artefacts_partent_vers_l_hote_des_applications(atelier_apps: TestClient) -> None:
    connecter(atelier_apps)
    r = atelier_apps.get("/v1/artifacts/demo/page.html", follow_redirects=False)
    assert code_du_renvoi(atelier_apps, r) == ("demo", "/demo/page.html")
    r = atelier_apps.get("/v1/artifacts/demo", follow_redirects=False)
    assert code_du_renvoi(atelier_apps, r) == ("demo", "/demo/")
    # Hors navigateur, la clé au porteur lit encore ici.
    r = atelier_apps.get("/v1/artifacts/demo/page.html", headers=porteur(atelier_apps), cookies={})
    assert r.status_code == 200
    assert "allow-downloads" in r.headers["content-security-policy"]


def test_une_page_n_ecrit_plus_sur_l_atelier(atelier_apps: TestClient) -> None:
    secret = art.secret_des_jetons(cle(atelier_apps))
    jeton = art.signer_jeton(secret, "demo", "corpus")
    r = atelier_apps.put(f"/v1/artifacts/demo/@{jeton}/corpus/b.md", content=b"# b")
    assert r.status_code == 410


def test_sans_second_hote_les_artefacts_restent_servis_ici(atelier_seul: TestClient) -> None:
    connecter(atelier_seul)
    r = atelier_seul.get("/v1/artifacts/demo/page.html", follow_redirects=False)
    assert r.status_code == 200
    assert "sandbox" in r.headers["content-security-policy"]


def test_l_hote_des_applications_refuse_un_hote_etranger(atelier_apps: TestClient) -> None:
    hote = TestClient(atelier_apps.app.state.app_apps, base_url="https://testserver")
    assert hote.get("/demo/site/").status_code == 421
    assert hote.get("/_sante").status_code == 200
    # Rien de l'Atelier n'y répond, même sous le bon hôte.
    bon = TestClient(atelier_apps.app.state.app_apps, base_url=APPS)
    assert bon.get("/v1/health").status_code in (401, 404)
    assert bon.get("/v1/meta").status_code in (401, 404)
