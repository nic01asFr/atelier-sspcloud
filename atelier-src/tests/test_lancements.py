"""Les agents lancés passent par l'Atelier (lot D) : identité, profil, mode, plafonds.

Tout se joue par les vraies portes : la route interne `POST /v1/lancements`
(celle de wikichat et des gardiens), la commande `atelier_lancer_agent` (celle
d'un modèle), le vrai catalogue, le vrai magasin de conversations. Seul le
harnais est factice ; il retient ce qu'il a reçu pour chaque tour.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier.api import build_app
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.lancements import ENTETE_CLE, lire_la_cle
from mcp_gateway.atelier.vscode_bridge import COOKIE_NAME

ORIGINE = "https://testserver"


def _client(reglages: AtelierSettings) -> TestClient:
    return TestClient(build_app(settings=reglages, use_fake=True), base_url=ORIGINE)


def _projet(reglages: AtelierSettings, slug: str, mode: str = "") -> Path:
    dossier = reglages.projects_dir / slug
    dossier.mkdir(parents=True, exist_ok=True)
    if mode:
        (dossier / ".claude").mkdir(exist_ok=True)
        (dossier / ".claude" / "settings.local.json").write_text(
            json.dumps({"permissions": {"defaultMode": mode}}), encoding="utf-8"
        )
    return dossier


def _cle(client: TestClient) -> dict[str, str]:
    return {ENTETE_CLE: lire_la_cle(client.app.state.settings)}  # type: ignore[attr-defined]


def _lancer(client: TestClient, **corps: Any) -> Any:
    corps.setdefault("origine", "wikichat:trigger:essai")
    corps.setdefault("plafonds", {"duree_s": 120})
    corps.setdefault("message", "Relève ton courrier et réponds.")
    return client.post("/v1/lancements", headers=_cle(client), json=corps)


def _fin(client: TestClient, identifiant: str) -> dict[str, Any]:
    lanceur = client.app.state.lancements  # type: ignore[attr-defined]
    lanceur.attendre(identifiant, 10)
    return lanceur.lire(identifiant).en_dict()


def _lance(client: TestClient, **corps: Any) -> Any:
    """Lance et attend la fin : les plafonds de simultanéité ne gênent pas le test."""
    r = _lancer(client, **corps)
    if r.status_code == 202:
        _fin(client, r.json()["lancement"]["id"])
    return r


def _personne(client: TestClient) -> dict[str, str]:
    sid = client.app.state.auth.ouvrir_session()  # type: ignore[attr-defined]
    return {"Cookie": f"{COOKIE_NAME}={sid}", "X-Atelier-Interface": "1", "Origin": ORIGINE}


# ── La route interne ─────────────────────────────────────────────────────────


def test_la_route_n_ouvre_qu_a_la_cle_du_lanceur(reglages: AtelierSettings, cle_du_proprietaire: str) -> None:
    _projet(reglages, "alpha")
    with _client(reglages) as client:
        corps = {"projet": "alpha", "message": "x", "origine": "wikichat:t", "plafonds": {"duree_s": 60}}
        assert client.post("/v1/lancements", json=corps).status_code == 401
        proprio = {"Authorization": f"Bearer {client.app.state.settings.owner_key_path.read_text().strip()}"}
        assert client.post("/v1/lancements", headers=proprio, json=corps).status_code == 401
        assert client.post("/v1/lancements", headers={ENTETE_CLE: "fausse"}, json=corps).status_code == 401
        assert client.post("/v1/lancements", headers=_personne(client), json=corps).status_code == 401
        # La clé est un fichier à part, en 0600 là où les droits existent.
        chemin = reglages.secrets_dir / "atelier_lanceur_key"
        assert chemin.is_file() and chemin.read_text().strip() != cle_du_proprietaire
        assert client.app.state.lancements.tous() == []


def test_lancement_par_l_atelier_avec_profil_mode_et_plafonds(reglages: AtelierSettings) -> None:
    _projet(reglages, "alpha", mode="plan")
    with _client(reglages) as client:
        r = _lancer(client, projet="alpha", nom="Librarian", plafonds={"duree_s": 90, "jetons": 50000})
        assert r.status_code == 202, r.text
        lancement = r.json()["lancement"]
        fin = _fin(client, lancement["id"])
        assert fin["etat"] == "fini", fin
        assert fin["texte"].startswith("echo:")

        # Une fiche, donc une identité, visible dans l'interface.
        fiche = client.app.state.store.get(fin["conversation"])
        assert fiche is not None and fiche.slug == "alpha" and fiche.kind == "code"
        assert fiche.lance_par == "wikichat:trigger:essai"
        assert fiche.title == "Librarian"
        liste = client.get("/v1/sessions", headers=_personne(client)).json()
        assert any(s.get("session_id") == fin["conversation"] for s in (liste if isinstance(liste, list) else liste.get("sessions", [])))

        # Ce que le tour a reçu : le mode du projet, la durée plafonnée, personne
        # pour répondre, le nom de l'agent pour wikichat, le dossier du projet.
        appel = client.app.state.harness.appels[-1]
        assert appel["permission_mode"] == "plan"
        assert appel["timeout_s"] == 90
        assert appel["peut_attendre"] is False
        assert appel["agent_name"] == "Librarian"
        assert Path(appel["cwd"]).resolve() == (reglages.projects_dir / "alpha").resolve()

        # Le profil `code` : le serveur `atelier` le déduit de la fiche, même si
        # l'appel annonce `assistant`.
        from mcp_gateway.atelier.commandes.profils import profil_effectif

        assert profil_effectif("assistant", fiche.session_id, client.app.state.store) == "code"

        # Lu par la route, par wikichat (clé du lanceur) comme par la personne.
        assert client.get(f"/v1/lancements/{lancement['id']}", headers=_cle(client)).json()["lancement"]["etat"] == "fini"
        assert client.get("/v1/lancements", headers=_personne(client)).json()["nombre"] == 1

        # Au journal unique : le lancement et sa fin, sous l'acteur de l'automate.
        evenements = client.app.state.journal_unique.lire(source="automate", limite=10)
        assert {e["resultat"] for e in evenements} >= {"lance", "fini"}
        assert all(e["acteur"] == "automate:wikichat:trigger:essai" for e in evenements)


def test_la_reprise_garde_la_meme_conversation(reglages: AtelierSettings) -> None:
    _projet(reglages, "alpha")
    with _client(reglages) as client:
        premier = _fin(client, _lancer(client, projet="alpha", nom="Sentinel").json()["lancement"]["id"])
        second = _lancer(client, projet="alpha", nom="Sentinel", conversation=premier["conversation"])
        assert second.status_code == 202, second.text
        fin = _fin(client, second.json()["lancement"]["id"])
        assert fin["conversation"] == premier["conversation"]
        assert len(client.app.state.store.list_sessions("alpha")) == 1


def test_un_agent_lance_n_obtient_pas_bypass_en_le_demandant(reglages: AtelierSettings) -> None:
    _projet(reglages, "alpha")
    _projet(reglages, "libre", mode="bypassPermissions")
    with _client(reglages) as client:
        # Demandé par un appel ad hoc : le mode du projet (ici celui du service).
        r = _lance(client, projet="alpha", mode="bypassPermissions")
        assert r.json()["lancement"]["mode"] == "acceptEdits"
        assert "bypassPermissions non accordé" in r.json()["lancement"]["avertissements"][0]
        # Sans demande, un projet que la personne a mis sans garde-fou le reste :
        # c'est le mode du projet, le même dans VS Code et au terminal.
        assert _lance(client, projet="libre").json()["lancement"]["mode"] == "bypassPermissions"
        # Demandé par une définition, mais le projet ne l'accorde pas.
        r = _lance(client, projet="alpha", mode="bypassPermissions", mode_de_la_definition=True)
        assert r.json()["lancement"]["mode"] == "acceptEdits"
        # Une définition, et un projet qui l'accorde : oui.
        r = _lance(client, projet="libre", mode="bypassPermissions", mode_de_la_definition=True)
        assert r.json()["lancement"]["mode"] == "bypassPermissions"
        # Le mode d'une routine (`plan`) est transmis tel quel.
        r = _lance(client, projet="alpha", mode="plan")
        assert r.json()["lancement"]["mode"] == "plan"


def test_les_plafonds_tiennent(reglages: AtelierSettings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_LANCEMENTS_SIMULTANES", "2")
    monkeypatch.setenv("ATELIER_LANCEMENTS_PAR_ORIGINE", "3")
    monkeypatch.setenv("ATELIER_LANCEMENTS_DUREE_MAX_S", "600")
    _projet(reglages, "alpha")
    with _client(reglages) as client:
        # Sans durée déclarée : refusé (J-b, budget obligatoire).
        r = client.post(
            "/v1/lancements", headers=_cle(client),
            json={"projet": "alpha", "message": "x", "origine": "wikichat:t"},
        )
        assert r.status_code == 403 and "duree_s" in r.json()["erreur"]

        # Deux tours qui travaillent : le troisième attend son tour, refusé.
        libre = threading.Event()
        client.app.state.harness.pendant_le_tour = lambda **_: libre.wait(10)
        a = _lancer(client, projet="alpha", plafonds={"duree_s": 5000})
        b = _lancer(client, projet="alpha", origine="wikichat:autre")
        assert a.status_code == b.status_code == 202
        assert a.json()["lancement"]["plafonds"]["duree_s"] == 600, "durée ramenée au plafond"
        c = _lancer(client, projet="alpha", origine="wikichat:troisieme")
        assert c.status_code == 403 and "à la fois" in c.json()["erreur"]
        libre.set()
        for r in (a, b):
            _fin(client, r.json()["lancement"]["id"])
        client.app.state.harness.pendant_le_tour = None

        # Par origine et par jour : la troisième du même trigger passe, la quatrième non.
        for _ in range(2):
            r = _lancer(client, projet="alpha")
            assert r.status_code == 202, r.text
            _fin(client, r.json()["lancement"]["id"])
        r = _lancer(client, projet="alpha")
        assert r.status_code == 403 and "wikichat:trigger:essai" in r.json()["erreur"]
        # Rien n'a été créé pour les refus.
        assert len(client.app.state.lancements.tous()) == 4


def test_projet_inconnu_ou_assistant_refuses(reglages: AtelierSettings) -> None:
    with _client(reglages) as client:
        assert _lancer(client, projet="fantome").status_code == 403
        r = _lancer(client, projet=reglages.assistant_slug)
        assert r.status_code == 403 and "profil code" in r.json()["erreur"]


# ── La commande, appelée par un modèle ──────────────────────────────────────


def test_un_modele_recoit_un_apercu_puis_lance_apres_le_oui(reglages: AtelierSettings, cle_du_proprietaire: str) -> None:
    _projet(reglages, "alpha")
    with _client(reglages) as client:
        porteur = {"Authorization": f"Bearer {cle_du_proprietaire}"}
        r = client.post(
            "/v1/commandes/atelier_lancer_agent", headers=porteur,
            json={"arguments": {"projet": "alpha", "message": "Corrige le test", "duree_min": 10}},
        )
        assert r.status_code == 200 and r.json()["statut"] == "apercu"
        apercu = r.json()["resultat"]
        assert apercu["apercu"]["projet"] == "alpha" and apercu["apercu"]["duree_s"] == 600
        assert client.app.state.lancements.tous() == [], "rien ne part avant le « Oui »"

        r = client.post(
            "/v1/commandes/atelier_lancer_agent", headers=porteur,
            json={"arguments": {"projet": "alpha", "message": "Corrige le test", "duree_min": 10},
                  "confirmation": apercu["confirmation"]},
        )
        assert r.status_code == 200 and r.json()["statut"] == "fait", r.text
        lance = r.json()["resultat"]["lancement"]
        assert lance["acteur"] == "cle-proprietaire"
        _fin(client, lance["id"])


def test_la_commande_n_est_pas_au_profil_code(reglages: AtelierSettings, cle_du_proprietaire: str) -> None:
    _projet(reglages, "alpha")
    with _client(reglages) as client:
        fiche = client.app.state.store.create(slug="alpha")
        entetes = {
            "Authorization": f"Bearer {cle_du_proprietaire}",
            "X-Atelier-Conversation": fiche.session_id,
            "X-Atelier-Profil": "code",
        }
        noms = {c["nom"] for c in client.get("/v1/commandes", headers=entetes).json()["commandes"]}
        assert "atelier_lancer_agent" not in noms
        r = client.post(
            "/v1/commandes/atelier_lancer_agent", headers=entetes,
            json={"arguments": {"projet": "alpha", "message": "x"}},
        )
        assert r.status_code == 403


# ── Le contexte d'un agent lancé ────────────────────────────────────────────


def test_le_contexte_de_l_agent_lance_est_celui_du_projet(reglages: AtelierSettings) -> None:
    dossier = _projet(reglages, "alpha")
    (dossier / "CLAUDE.md").write_text("@.atelier/contexte.md\n\n# Alpha\n", encoding="utf-8")
    with _client(reglages) as client:
        _fin(client, _lancer(client, projet="alpha").json()["lancement"]["id"])
    contexte = (dossier / ".atelier" / "contexte.md").read_text(encoding="utf-8")
    from mcp_gateway.atelier.project_context import contexte_attendu

    assert contexte == contexte_attendu(reglages, dossier, "alpha")[1] + "\n"


def test_le_dossier_de_travail_d_un_agent_est_une_cible_valable(reglages: AtelierSettings) -> None:
    # Cas du pod (26/09) : les agents planifiés de l'Atelier travaillent dans un
    # dossier marqué `.atelier-agent`, absent de la liste des projets de Code ;
    # leurs lancements étaient refusés comme « projet inconnu ».
    from mcp_gateway.atelier.projects import MARQUEUR_AGENT

    dossier = _projet(reglages, "memoire-des-projets")
    (dossier / MARQUEUR_AGENT).write_text("agent\n", encoding="utf-8")
    with _client(reglages) as client:
        r = _lance(client, dossier=str(dossier))
        assert r.status_code == 202, r.text
        # Un projet qui n'existe pas, lui, reste refusé.
        refus = _lancer(client, projet="n-existe-pas")
        assert refus.status_code == 403


def test_un_dossier_hors_des_projets_lance_l_agent_sans_projet_dans_un_sous_dossier(reglages: AtelierSettings, tmp_path) -> None:
    # Constaté le 24/10 : un déclencheur donnait le dossier de l'Assistant ; l'agent
    # atterrissait en silence dans le projet « default » (sans nom). Sans projet, il
    # travaille comme l'Assistant : dans un sous-dossier à lui.
    _projet(reglages, "alpha")
    ailleurs = tmp_path / "hors-projets"
    ailleurs.mkdir()
    with _client(reglages) as client:
        r = _lance(client, dossier=str(ailleurs))
        assert r.status_code == 202, r.text
        lancement = r.json()["lancement"]
        assert lancement["projet"] == reglages.assistant_slug != reglages.default_slug
        # Une branche suppose un projet git : sans projet elle est ignorée, avec un avertissement.
        avec_branche = _lance(client, dossier=str(ailleurs), branche="agent/x")
        assert avec_branche.status_code == 202, avec_branche.text
        l2 = avec_branche.json()["lancement"]
        assert not l2.get("branche") and any("branche" in a for a in l2["avertissements"])


# ── La supervision : le lanceur répond, dans le périmètre du projet ─────────


def test_un_lancement_supervise_pose_ses_demandes_au_lieu_de_les_refuser(reglages: AtelierSettings) -> None:
    _projet(reglages, "alpha")
    with _client(reglages) as client:
        r = _lancer(client, projet="alpha", supervise=True)
        assert r.status_code == 202, r.text
        lancement = r.json()["lancement"]
        assert lancement["supervise"] is True
        fin = _fin(client, lancement["id"])
        assert client.app.state.harness.appels[-1]["peut_attendre"] is True
        assert client.app.state.store.get(fin["conversation"]).supervise is True

        sans = _lancer(client, projet="alpha")
        assert sans.json()["lancement"]["supervise"] is False
        _fin(client, sans.json()["lancement"]["id"])
        assert client.app.state.harness.appels[-1]["peut_attendre"] is False


def test_une_reparation_de_gardien_n_est_jamais_supervisee(reglages: AtelierSettings) -> None:
    from mcp_gateway.atelier.lancements import Lanceur

    assert Lanceur._supervise({"supervise": True}, "gardien:controle") is False
    assert Lanceur._supervise({"supervise": True}, "conversation:abc") is True
    assert Lanceur._supervise({}, "conversation:abc") is False
    # Un client sans schéma envoie « true » en texte ; « false » reste faux.
    assert Lanceur._supervise({"supervise": "true"}, "conversation:abc") is True
    assert Lanceur._supervise({"supervise": "false"}, "conversation:abc") is False
    assert Lanceur._supervise({"supervise": 0}, "conversation:abc") is False


def test_l_apercu_dit_quand_l_agent_travaille_sans_branche(reglages: AtelierSettings) -> None:
    _projet(reglages, "alpha")
    with _client(reglages) as client:
        lanceur = client.app.state.lancements
        sans = lanceur.apercu({"projet": "alpha", "message": "x", "mode": "acceptEdits", "supervise": True}, "conversation:a")
        assert sans["supervise"] is True
        assert any("sans branche" in a for a in sans["avertissements"])
        lecture = lanceur.apercu({"projet": "alpha", "message": "x", "mode": "plan"}, "conversation:a")
        assert not any("sans branche" in a for a in lecture["avertissements"])


def test_un_lancement_sur_une_conversation_occupee_n_est_pas_fini(reglages: AtelierSettings) -> None:
    """Relecture du 03/10 : le message partait en file, rien ne tournait, et le lancement passait « fini »."""
    _projet(reglages, "alpha")
    with _client(reglages) as client:
        premier = _fin(client, _lancer(client, projet="alpha", nom="Sentinel").json()["lancement"]["id"])
        store = client.app.state.store
        store._reservees.add(premier["conversation"])  # un tour travaille déjà dessus
        try:
            second = _lancer(client, projet="alpha", nom="Sentinel", conversation=premier["conversation"])
            assert second.status_code == 202, second.text
            fin = _fin(client, second.json()["lancement"]["id"])
        finally:
            store._reservees.discard(premier["conversation"])
        assert fin["etat"] == "echec", fin
        assert "travaillait déjà" in fin["erreur"]


def test_un_lancement_confirme_par_la_personne_retient_la_conversation_qui_l_a_demande(reglages: AtelierSettings) -> None:
    """L'Assistant propose, la personne dit « Oui » : l'origine est la personne, le lanceur reste l'Assistant."""
    import asyncio

    from mcp_gateway.atelier.commandes.catalogue import contexte_interface
    from mcp_gateway.atelier.commandes.modele import ORIGINE_MCP, Contexte

    _projet(reglages, "alpha")
    with _client(reglages) as client:
        catalogue = client.app.state.commandes
        modele = Contexte(acteur="conversation:assistant-1", origine=ORIGINE_MCP)
        arguments = {"projet": "alpha", "message": "Corrige le test", "supervise": True, "duree_min": 5}
        apercu = asyncio.run(catalogue.executer("atelier_lancer_agent", arguments, modele))
        reponse = asyncio.run(catalogue.confirmer(apercu.charge["confirmation"], contexte_interface()))
        lance = reponse.charge["lancement"]
        assert lance["origine"] == "personne" and lance["lanceur"] == "assistant-1"
        assert lance["supervise"] is True
        _fin(client, lance["id"])


def test_une_consigne_longue_arrive_entiere_a_l_agent(reglages: AtelierSettings) -> None:
    """Le plafond annoncé est 60 000 caractères : la fiche en garde un extrait, le tour reçoit tout."""
    _projet(reglages, "alpha")
    longue = "Étape. " * 1200 + "FIN-DE-LA-CONSIGNE"
    assert len(longue) > 2000
    with _client(reglages) as client:
        r = _lance(client, projet="alpha", message=longue)
        assert r.status_code == 202, r.text
        appel = client.app.state.harness.appels[-1]
        assert appel["message"].startswith("Étape.") and appel["message"].endswith("FIN-DE-LA-CONSIGNE")
        fiche = r.json()["lancement"]
        assert len(fiche["message"]) <= 2000, "la fiche reste lisible : un extrait"


def test_un_agent_supervise_par_un_agent_sait_ce_que_son_lanceur_peut_lui_repondre(reglages: AtelierSettings) -> None:
    import asyncio

    from mcp_gateway.atelier.commandes.catalogue import contexte_interface
    from mcp_gateway.atelier.commandes.modele import ORIGINE_MCP, Contexte

    _projet(reglages, "alpha")
    with _client(reglages) as client:
        catalogue = client.app.state.commandes
        modele = Contexte(acteur="conversation:assistant-1", origine=ORIGINE_MCP)
        arguments = {"projet": "alpha", "message": "Corrige le test", "supervise": True, "duree_min": 5}
        apercu = asyncio.run(catalogue.executer("atelier_lancer_agent", arguments, modele))
        reponse = asyncio.run(catalogue.confirmer(apercu.charge["confirmation"], contexte_interface()))
        _fin(client, reponse.charge["lancement"]["id"])
        recu = client.app.state.harness.appels[-1]["message"]
        assert recu.startswith("Corrige le test")  # la tâche d'abord, intacte
        assert "[Atelier]" in recu and "supervision" in recu
        assert "atelier_demander_au_lanceur" in recu and "python -c" in recu

    # Sans lanceur agent (une personne, wikichat) : le texte de l'agent ne change pas.
    with _client(reglages) as client:
        r = _lance(client, projet="alpha", message="Relève ton courrier.", supervise=True)
        assert client.app.state.harness.appels[-1]["message"] == "Relève ton courrier."
