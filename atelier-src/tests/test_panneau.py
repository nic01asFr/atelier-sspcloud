"""Le panneau, « Montrer », et le passage d'agent vers l'hôte des applications.

Le passage d'agent (décision J-h) est une garde de sécurité : ces tests en
prennent la portée au mot. Un code émis pour la conversation d'un projet
ouvre, sur l'hôte des applications, ce projet-là et lui seul ; la session qu'il
ouvre ne s'élargit jamais, et l'Atelier ne la reconnaît pas.
"""

from __future__ import annotations

import asyncio
import json
import queue
from pathlib import Path
from typing import Iterator
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier.api import build_app
from mcp_gateway.atelier.apps.passage import (
    COOKIE_APPS,
    DUREE_SESSION_AGENT_S,
    Passage,
)
from mcp_gateway.atelier.apps.serveur import construire_app_apps
from mcp_gateway.atelier.artifacts import secret_des_jetons
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.outils_conversation import CONVERSATION_APPELANTE, OutilsAtelier
from mcp_gateway.atelier.vscode_bridge import COOKIE_NAME

APPS = "https://apps.test"
ATELIER = "https://testserver"
INTERFACE = {"X-Atelier-Interface": "1", "Sec-Fetch-Site": "same-origin"}


# ── Montage ────────────────────────────────────────────────────────────


@pytest.fixture()
def atelier(tmp_path: Path) -> Iterator[TestClient]:
    settings = AtelierSettings(work_dir=tmp_path / "work", apps_public_url=APPS, public_url=ATELIER)
    settings.ensure_dirs()
    for slug, nom in (("demo", "site"), ("demo", "carte"), ("autre", "secret")):
        dossier = settings.projects_dir / slug / "artifacts" / nom
        dossier.mkdir(parents=True)
        (dossier / "index.html").write_text(f"<h1>{slug}/{nom}</h1>", encoding="utf-8")
    with TestClient(build_app(settings=settings, use_fake=True), base_url=ATELIER) as client:
        client.post("/v1/projects", json={"slug": "demo", "kind": "code"}, headers=porteur(client))
        client.post("/v1/projects", json={"slug": "autre", "kind": "code"}, headers=porteur(client))
        yield client


def porteur(client: TestClient) -> dict[str, str]:
    cle = client.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()
    return {"Authorization": f"Bearer {cle}"}


def conversation(client: TestClient, slug: str = "demo") -> str:
    r = client.post("/v1/sessions", json={"slug": slug, "kind": "code"}, headers=porteur(client))
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def outils(client: TestClient) -> OutilsAtelier:
    etat = client.app.state
    return OutilsAtelier(store=etat.store, projects=etat.projects, harness=etat.harness, apps=etat.apps)


def appeler(o: OutilsAtelier, outil: str, conv: str = "", **arguments):
    jeton = CONVERSATION_APPELANTE.set(conv)
    try:
        reponse = asyncio.run(o.appeler(outil, arguments))
    finally:
        CONVERSATION_APPELANTE.reset(jeton)
    assert reponse is not None, outil
    return json.loads(reponse["content"][0]["text"]), bool(reponse.get("isError"))


def hote(client: TestClient) -> TestClient:
    """L'hôte des applications de ce même Atelier, sous son propre nom."""
    etat = client.app.state
    app = construire_app_apps(
        etat.apps, origine_atelier=lambda: ATELIER, secret_artefacts=lambda: secret_des_jetons("x")
    )
    return TestClient(app, base_url=APPS)


def entrer(h: TestClient, adresse: str) -> str:
    """Ce que fait le navigateur de l'agent : ouvrir l'adresse, garder le cookie."""
    vers = urlsplit(adresse)
    r = h.get(f"{vers.path}?{vers.query}", follow_redirects=False)
    assert r.status_code == 302, r.text
    for valeur in r.headers.get_list("set-cookie"):
        if valeur.startswith(COOKIE_APPS + "="):
            return valeur.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError("pas de cookie d'applications")


# ── Le passage d'agent : portée ────────────────────────────────────────


def test_le_code_d_agent_n_ouvre_que_le_projet_de_la_conversation(atelier: TestClient) -> None:
    conv = conversation(atelier, "demo")
    charge, erreur = appeler(outils(atelier), "atelier_navigateur_ouvrir", conv, chemin="site/")
    assert not erreur, charge
    assert charge["adresse"].startswith(f"{APPS}/_atelier/entree?code=")
    assert charge["portee"] == "demo"

    h = hote(atelier)
    cookie = entrer(h, charge["adresse"])
    session = atelier.app.state.apps.passage.session(cookie)
    assert session is not None and session.acteur == f"agent:{conv}"
    assert session.portees == frozenset({"demo"})

    h.cookies.set(COOKIE_APPS, cookie, domain="apps.test")
    assert h.get("/demo/site/", follow_redirects=True).text == "<h1>demo/site</h1>"
    # Un autre projet : l'hôte renvoie vers l'Atelier, rien n'est servi.
    r = h.get("/autre/secret/", follow_redirects=False, headers={"Accept": "text/html"})
    assert r.status_code == 302 and r.headers["location"].startswith(f"{ATELIER}/v1/apps/entree")
    assert "autre/secret" not in h.get("/autre/secret/index.html", follow_redirects=False).text


def test_l_outil_refuse_un_autre_projet_et_une_conversation_anonyme(atelier: TestClient) -> None:
    conv = conversation(atelier, "demo")
    o = outils(atelier)
    charge, erreur = appeler(o, "atelier_navigateur_ouvrir", conv, projet="autre")
    assert erreur and "projet refusé" in charge["erreur"]
    charge, erreur = appeler(o, "atelier_navigateur_ouvrir", "", projet="demo")
    assert erreur and "X-Atelier-Conversation" in charge["erreur"]
    charge, erreur = appeler(o, "atelier_navigateur_ouvrir", conv, chemin="../autre/secret/")
    assert erreur


def test_le_cookie_d_agent_n_ouvre_pas_l_atelier(atelier: TestClient) -> None:
    conv = conversation(atelier, "demo")
    charge, _ = appeler(outils(atelier), "atelier_navigateur_ouvrir", conv)
    cookie = entrer(hote(atelier), charge["adresse"])
    atelier.cookies.clear()
    # Ni sous son nom, ni glissé sous celui de la session de l'Atelier.
    for nom in (COOKIE_APPS, COOKIE_NAME):
        atelier.cookies.set(nom, cookie, domain="testserver")
        for chemin in ("/v1/meta", "/v1/sessions", "/v1/apps"):
            assert atelier.get(chemin, headers=INTERFACE).status_code == 401, (nom, chemin)
        # Ni émettre un code owner pour un projet.
        r = atelier.get("/v1/apps/autre/secret/ouvrir", follow_redirects=False)
        assert r.status_code == 401, r.text
        atelier.cookies.clear()


def test_une_session_d_agent_ne_s_elargit_jamais(tmp_path: Path) -> None:
    from mcp_gateway.auth import migrate_auth_schema, open_owner_session
    from mcp_gateway.db import connect

    base = tmp_path / "gw.db"
    p = Passage(base)
    conn = connect(base)
    migrate_auth_schema(conn)
    sid_owner = open_owner_session(conn, 3600)
    conn.close()

    agent = p.ouvrir(p.consommer_code(p.emettre_code_agent("agent:c1", "demo", "/demo/")))
    # Un code owner présenté avec le cookie de l'agent : une session neuve, owner.
    owner = p.ouvrir(p.consommer_code(p.emettre_code(sid_owner, "autre", "/autre/")), agent.id)
    assert owner.id != agent.id and not owner.est_agent
    assert p.session(agent.id).portees == frozenset({"demo"})
    # Un second code d'agent, même avec le cookie : une autre session, pas une portée de plus.
    second = p.ouvrir(p.consommer_code(p.emettre_code_agent("agent:c1", "demo", "/demo/")), agent.id)
    assert second.id != agent.id
    # Et la destination reste sous la portée.
    with pytest.raises(ValueError):
        p.emettre_code_agent("agent:c1", "demo", "/autre/x/")
    with pytest.raises(ValueError):
        p.emettre_code_agent("proprietaire", "demo", "/demo/")


def test_une_session_d_agent_vit_une_heure_sans_session_owner(tmp_path: Path) -> None:
    maintenant = [1000.0]
    p = Passage(tmp_path / "gw.db", horloge=lambda: maintenant[0])
    code = p.emettre_code_agent("agent:c1", "demo", "/demo/")
    maintenant[0] += 121
    assert p.consommer_code(code) is None, "un code d'agent expire en deux minutes"
    s = p.ouvrir(p.consommer_code(p.emettre_code_agent("agent:c1", "demo", "/demo/")))
    assert p.session(s.id) is not None
    maintenant[0] += DUREE_SESSION_AGENT_S + 1
    assert p.session(s.id) is None
    # Faire tourner la clé ferme aussi les sessions d'agents.
    s = p.ouvrir(p.consommer_code(p.emettre_code_agent("agent:c1", "demo", "/demo/")))
    p.fermer_tout()
    assert p.session(s.id) is None


# ── Montrer ────────────────────────────────────────────────────────────


def test_montrer_epingle_a_la_conversation_et_previent_les_onglets(atelier: TestClient) -> None:
    conv = conversation(atelier, "demo")
    etat = atelier.app.state
    publies: list = []
    etat.panneau.publier = lambda sid, vue, cause: publies.append((sid, vue, cause))

    charge, erreur = appeler(outils(atelier), "atelier_montrer", conv, nom="site", titre="Le site")
    assert not erreur, charge
    vue = charge["vue"]
    assert vue["projet"] == "demo" and vue["nom"] == "site" and vue["epingle"] == "conversation"
    assert vue["par"] == "agent" and vue["titre"] == "Le site"
    assert publies == [(conv, vue, "panneau_montrer")]

    # Rouvrir la conversation retrouve l'onglet ; montrer deux fois ne le double pas.
    appeler(outils(atelier), "atelier_montrer", conv, nom="site")
    r = atelier.get(f"/v1/panneau/{conv}", headers=porteur(atelier))
    assert [v["id"] for v in r.json()["vues"]] == [vue["id"]]


def test_montrer_refuse_ce_qui_n_existe_pas_ou_n_est_pas_du_projet(atelier: TestClient) -> None:
    conv = conversation(atelier, "demo")
    o = outils(atelier)
    charge, erreur = appeler(o, "atelier_montrer", conv, nom="inexistante")
    assert erreur and "inexistante" in charge["erreur"]
    charge, erreur = appeler(o, "atelier_montrer", conv, nom="secret", projet="autre")
    assert erreur and "projet refusé" in charge["erreur"]
    charge, erreur = appeler(o, "atelier_montrer", "", nom="site")
    assert erreur


def test_montrer_arrive_sur_le_flux_en_direct(atelier: TestClient) -> None:
    """Ce qu'écoute l'onglet ouvert sur la conversation (`/live`)."""
    conv = conversation(atelier, "demo")
    etat = atelier.app.state
    publie = etat.panneau.publier
    vu: "queue.Queue" = queue.Queue()
    etat.panneau.publier = lambda sid, vue, cause: (publie(sid, vue, cause), vu.put((sid, cause)))
    appeler(outils(atelier), "atelier_montrer", conv, nom="carte")
    assert vu.get_nowait() == (conv, "panneau_montrer")


def test_epingler_au_projet_ecrit_projet_json_sans_toucher_au_reste(atelier: TestClient) -> None:
    conv = conversation(atelier, "demo")
    autre_conv = conversation(atelier, "demo")
    racine = atelier.app.state.settings.projects_dir / "demo"
    (racine / ".atelier").mkdir(exist_ok=True)
    (racine / ".atelier" / "projet.json").write_text(json.dumps({"titre": "Démo", "version": 1}), encoding="utf-8")

    r = atelier.put(
        f"/v1/panneau/{conv}/vues",
        json={"nom": "carte", "titre": "Carte", "epingle": "projet"},
        headers=porteur(atelier),
    )
    assert r.status_code == 200, r.text
    donnees = json.loads((racine / ".atelier" / "projet.json").read_text(encoding="utf-8"))
    assert donnees["titre"] == "Démo" and donnees["version"] == 1
    assert donnees["vues_epinglees"] == [{"nom": "carte", "chemin": "", "titre": "Carte"}]
    # Visible depuis toutes les conversations du projet.
    vues = atelier.get(f"/v1/panneau/{autre_conv}", headers=porteur(atelier)).json()["vues"]
    assert [v["nom"] for v in vues] == ["carte"] and vues[0]["epingle"] == "projet"
    # Fermer l'onglet le retire du projet.
    vid = vues[0]["id"]
    assert atelier.delete(f"/v1/panneau/{conv}/vues/{vid}", headers=porteur(atelier)).json()["retiree"]
    assert atelier.get(f"/v1/panneau/{autre_conv}", headers=porteur(atelier)).json()["vues"] == []


def test_une_vue_ne_sort_pas_de_son_projet(atelier: TestClient) -> None:
    conv = conversation(atelier, "demo")
    for corps in (
        {"projet": "autre", "nom": "secret"},
        {"nom": "site", "chemin": "../../autre/secret/"},
        {"nom": "site", "chemin": "//ailleurs.test/"},
        {"nom": "../x"},
    ):
        r = atelier.put(f"/v1/panneau/{conv}/vues", json=corps, headers=porteur(atelier))
        assert r.status_code == 400, corps


def test_ouvrir_avec_un_chemin_reste_sous_la_creation(atelier: TestClient) -> None:
    atelier.post("/v1/auth/cookie", headers=porteur(atelier))
    r = atelier.get("/v1/apps/demo/site/ouvrir", params={"chemin": "page.html"}, follow_redirects=False)
    assert r.status_code == 302
    code = parse_qs(urlsplit(r.headers["location"]).query)["code"][0]
    assert atelier.app.state.apps.passage.consommer_code(code).destination == "/demo/site/page.html"
    for chemin in ("../../autre/secret/", "%2e%2e/%2e%2e/autre/", "a/../../../autre/"):
        r = atelier.get("/v1/apps/demo/site/ouvrir", params={"chemin": chemin}, follow_redirects=False)
        assert r.status_code == 400, chemin


# ── Les fils wikichat d'une conversation ───────────────────────────────


def test_les_fils_suivent_le_contrat_de_wikichat(atelier: TestClient, monkeypatch) -> None:
    conv = conversation(atelier, "demo")
    vus: list[str] = []

    def repondre(requete: httpx.Request) -> httpx.Response:
        vus.append(str(requete.url))
        assert requete.url.path == "/api/fils"
        if requete.url.params["session"] != conv:
            return httpx.Response(404, json={"error": "agent ou session inconnus"})
        return httpx.Response(
            200,
            json={
                "agent": "demo-abc123",
                "fils": [{"id": "f-1a2b3c", "participants": ["demo-abc123", "gardien"], "sujet": "parité",
                          "statut": "ouvert", "attend": ["demo-abc123"], "echeance": None,
                          "messages": [], "en_retard": False}],
            },
        )

    vrai = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **k: vrai(transport=httpx.MockTransport(repondre), **{
            c: v for c, v in k.items() if c != "transport"})
    )
    r = atelier.get(f"/v1/sessions/{conv}/fils", headers=porteur(atelier))
    assert r.status_code == 200, r.text
    assert r.json()["fils"][0]["id"] == "f-1a2b3c"
    assert all("127.0.0.1:3777" in u for u in vus)


def test_sans_wikichat_les_fils_sont_vides_et_le_disent(atelier: TestClient, monkeypatch) -> None:
    conv = conversation(atelier, "demo")

    def tomber(requete: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refus", request=requete)

    vrai = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **k: vrai(transport=httpx.MockTransport(tomber), **{
            c: v for c, v in k.items() if c != "transport"})
    )
    r = atelier.get(f"/v1/sessions/{conv}/fils", headers=porteur(atelier))
    assert r.status_code == 200 and r.json() == {"agent": None, "fils": [], "indisponible": True}


def test_l_application_sait_que_c_est_un_agent_qui_entre() -> None:
    from mcp_gateway.atelier.apps import proxy as px

    def acces(acteur: str) -> dict[str, str]:
        return dict(px.entetes_vers_amont(
            [("X-Atelier-Acces", "proprietaire")], prefixe="/demo/a", hote_public="apps.test",
            client_ip="1.2.3.4", acteur=acteur,
        ))

    assert acces("")["X-Atelier-Acces"] == "proprietaire"
    agent = acces("agent:c1")
    assert agent["X-Atelier-Acces"] == "agent" and agent["X-Atelier-Utilisateur"] == "agent:c1"
