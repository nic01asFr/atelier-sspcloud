"""Une fin de tour dit ce qui s'est passé : en erreur, ce n'est pas « au repos ».

Registre des défauts D-10 : une conversation morte sur `autocompact_thrashing`
restait « idle ». Le processus du CLI est gardé entre deux tours et rend un code
0 même quand son résultat est une erreur : se fier au code revenait à ne jamais
voir ces erreurs.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from mcp_gateway.atelier.events import AtelierEvent
from mcp_gateway.atelier.harness import TurnResult


def _cle(atelier: TestClient) -> str:
    return atelier.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()


def _conversation(atelier: TestClient) -> str:
    r = atelier.post(
        "/v1/sessions", headers={"Authorization": f"Bearer {_cle(atelier)}"}, json={"slug": "essai-fin"}
    )
    return r.json()["session_id"]


def _tour(sid: str, evenements: list[AtelierEvent], code: int = 0, texte: str = "") -> TurnResult:
    return TurnResult(
        session_id=sid, exit_code=code, events=evenements, log_path="", transcript_path="", text=texte
    )


def _jouer(atelier: TestClient, evenements: list[AtelierEvent], code: int = 0):
    sid = _conversation(atelier)
    atelier.app.state.harness.run_turn = lambda *a, **k: _tour(sid, evenements, code)  # type: ignore[method-assign]
    atelier.app.state.store.send(sid, "vas-y", peut_attendre=True)
    return atelier.app.state.store.get(sid)


def _erreur(sid_inutile: str = "", cause: str = "x", raw_type: str = "result") -> AtelierEvent:
    return AtelierEvent(kind="erreur", session_id=sid_inutile, cause=cause, raw_type=raw_type)


def test_un_resultat_en_erreur_rend_la_conversation_en_echec_meme_avec_un_code_zero(atelier: TestClient) -> None:
    fiche = _jouer(atelier, [_erreur(cause="Autocompact is thrashing: the context refilled to the limit")])
    assert fiche.state == "failed", "un processus qui vit encore rend 0 : le code ne dit pas la fin"
    assert "thrashing" in fiche.cause


def test_une_erreur_de_stderr_sans_resultat_ne_condamne_pas_le_tour(atelier: TestClient) -> None:
    """Un connecteur qui journalise « Error: » pendant qu'un tour réussit n'est pas un échec."""
    fiche = _jouer(atelier, [_erreur(cause="Error: un MCP bavard", raw_type="")])
    assert fiche.state == "idle" and fiche.cause == ""


def test_un_tour_sans_erreur_reste_au_repos(atelier: TestClient) -> None:
    fiche = _jouer(atelier, [])
    assert fiche.state == "idle"


def test_la_cause_garde_la_premiere_erreur_du_resultat(atelier: TestClient) -> None:
    fiche = _jouer(atelier, [_erreur(cause="première"), _erreur(cause="seconde")])
    assert fiche.cause == "première"


def test_un_agent_lance_dont_le_tour_finit_en_erreur_n_est_pas_fini(reglages) -> None:
    from mcp_gateway.atelier.api import build_app
    from mcp_gateway.atelier.lancements import ENTETE_CLE, lire_la_cle

    (reglages.projects_dir / "alpha").mkdir(parents=True, exist_ok=True)
    with TestClient(build_app(settings=reglages, use_fake=True), base_url="https://testserver") as client:
        client.app.state.harness.run_turn = lambda sid, *a, **k: _tour(  # type: ignore[method-assign]
            sid, [_erreur(cause="rapid_refill_breaker")]
        )
        r = client.post(
            "/v1/lancements",
            headers={ENTETE_CLE: lire_la_cle(client.app.state.settings)},
            json={"projet": "alpha", "message": "Fais-le.", "origine": "wikichat:trigger:essai",
                  "plafonds": {"duree_s": 60}},
        )
        identifiant = r.json()["lancement"]["id"]
        client.app.state.lancements.attendre(identifiant, 10)
        lancement = client.app.state.lancements.lire(identifiant)
        assert lancement.etat == "echec", "« fini » mentirait : le tour s'est arrêté sur une erreur"
        assert "rapid_refill_breaker" in lancement.erreur


# -- interrompre -------------------------------------------------------------


def test_interrompre_une_conversation_au_repos_ne_la_marque_pas_interrompue(atelier: TestClient) -> None:
    """Registre D-11 : « fait » 95 s après la fin, et un état qui contredit le lancement."""
    sid = _conversation(atelier)
    store = atelier.app.state.store
    fiche, tournait = store.interrompre(sid)
    assert tournait is False
    assert fiche.state != "interrupted"
    assert store.get(sid).state != "interrupted"


def test_interrompre_un_tour_qui_tourne_le_marque_interrompu(atelier: TestClient) -> None:
    sid = _conversation(atelier)
    atelier.app.state.harness._running[sid] = True
    fiche, tournait = atelier.app.state.store.interrompre(sid)
    assert tournait is True and fiche.state == "interrupted"


def test_interrompre_une_conversation_qui_dort_abandonne_sa_question(atelier: TestClient) -> None:
    from mcp_gateway.atelier.decisions import Demande

    sid = _conversation(atelier)
    store = atelier.app.state.store
    registre = atelier.app.state.harness.decisions
    registre.deposer_en_veille(Demande(request_id="dort1", session_id=sid, outil="Bash"))
    fiche = store.get(sid)
    fiche.en_attente_de = "dort1"
    store.save(fiche)

    rec, tournait = store.interrompre(sid)

    assert tournait is False and rec.en_attente_de == ""
    assert rec.state != "interrupted"
    assert [d for d in registre.orphelines() if d.session_id == sid] == []


def test_la_route_dit_ce_qu_elle_a_fait(atelier: TestClient) -> None:
    sid = _conversation(atelier)
    r = atelier.post(f"/v1/sessions/{sid}/interrupt", headers={"Authorization": f"Bearer {_cle(atelier)}"})
    assert r.status_code == 200
    assert r.json()["state"] != "interrupted"


# -- « arrêté » dit pourquoi ------------------------------------------------


def _lancer_qui_dort_longtemps(reglages):
    """Un lancement dont le tour ne finit pas tout seul : l'arrêt vient de dehors."""
    import threading

    from mcp_gateway.atelier.api import build_app
    from mcp_gateway.atelier.lancements import ENTETE_CLE, lire_la_cle

    (reglages.projects_dir / "alpha").mkdir(parents=True, exist_ok=True)
    client = TestClient(build_app(settings=reglages, use_fake=True), base_url="https://testserver")
    client.__enter__()
    libere = threading.Event()
    harnais = client.app.state.harness

    def long(sid, *a, **k):
        libere.wait(10)
        return _tour(sid, [])

    harnais.run_turn = long  # type: ignore[method-assign]
    r = client.post(
        "/v1/lancements",
        headers={ENTETE_CLE: lire_la_cle(client.app.state.settings)},
        json={"projet": "alpha", "message": "Longtemps.", "origine": "wikichat:trigger:essai",
              "plafonds": {"duree_s": 60}},
    )
    return client, r.json()["lancement"]["id"], libere


def test_un_agent_arrete_dit_qui_l_a_arrete(reglages) -> None:
    client, identifiant, libere = _lancer_qui_dort_longtemps(reglages)
    try:
        lanceur = client.app.state.lancements
        arrete = lanceur.arreter(identifiant, par="la personne")
        assert arrete.etat == "arrete" and arrete.erreur == "arrêté par la personne"
        libere.set()
        lanceur.attendre(identifiant, 10)
        fin = lanceur.lire(identifiant)
        assert fin.etat == "arrete" and fin.erreur == "arrêté par la personne", "la fin du tour n'efface pas le motif"
    finally:
        libere.set()
        client.__exit__(None, None, None)


def test_une_duree_depassee_n_est_pas_un_arret_sans_motif(reglages) -> None:
    client, identifiant, libere = _lancer_qui_dort_longtemps(reglages)
    try:
        lanceur = client.app.state.lancements
        lanceur._couper(identifiant)
        libere.set()
        lanceur.attendre(identifiant, 10)
        fin = lanceur.lire(identifiant)
        assert fin.etat == "delai" and "durée dépassée" in fin.erreur
    finally:
        libere.set()
        client.__exit__(None, None, None)


# -- les identifiants courts ------------------------------------------------


def test_un_identifiant_court_suffit_comme_pour_la_fiche(atelier: TestClient) -> None:
    """Registre D-35 : « conversation inconnue » pour un identifiant que l'Atelier lui-même donne."""
    sid = _conversation(atelier)
    store = atelier.app.state.store
    assert store.resoudre(sid) == sid
    assert store.resoudre(sid[:8]) == sid
    assert store.resoudre(sid[:5]) == sid[:5], "trop court : on ne devine pas"
    assert store.resoudre("inconnu-xyz") == "inconnu-xyz"
    assert store.resoudre("") == ""


def test_un_prefixe_ambigu_ne_devine_pas(atelier: TestClient, monkeypatch) -> None:
    from types import SimpleNamespace

    store = atelier.app.state.store
    monkeypatch.setattr(
        store,
        "list_sessions",
        lambda *a, **k: [SimpleNamespace(session_id="abcd1234-aaaa"), SimpleNamespace(session_id="abcd1234-bbbb")],
    )
    assert store.resoudre("abcd1234") == "abcd1234", "deux conversations commencent ainsi"
    assert store.resoudre("abcd1234-b") == "abcd1234-bbbb"
