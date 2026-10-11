"""Attendre sans refuser : la veille, et la reprise qui suit la réponse.

Une question à la personne n'est jamais un refus. Quand personne ne répond à
temps — ou que personne ne peut —, le tour ne reçoit **rien** : le processus
est rendu, la question reste posée, la conversation dort. La réponse, quand
elle vient, relance le travail avec un message de l'Atelier.

Ce que ces tests tiennent, et qu'aucun test d'API ne verrait seul :
- le tour s'arrête **sans erreur** et sans refus rendu au modèle ;
- la question survit (disque, redémarrage) et reste répondable ;
- la réponse relance un tour, et « pour cette fois » ne devient jamais durable.
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier import harness as module
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.decisions import (
    Demande,
    RegistreDesDecisions,
    Regle,
    message_de_reprise,
    resume_de_l_action,
)
from mcp_gateway.atelier.harness import ClaudeHarness

FAUX = Path(__file__).parent / "faux_claude.py"


# -- le message de reprise ------------------------------------------------


def _demande(**kw) -> Demande:
    base = dict(
        request_id="r1",
        session_id="s1",
        outil="Bash",
        arguments={"command": "pip install torch"},
        description="pip install torch",
    )
    base.update(kw)
    return Demande(**base)


def test_le_resume_de_l_action_dit_la_commande_pas_un_dictionnaire() -> None:
    assert resume_de_l_action(_demande()) == "Bash — pip install torch"
    ecriture = _demande(outil="Write", arguments={"file_path": "/tmp/x.txt", "content": "a"})
    assert resume_de_l_action(ecriture) == "Write — /tmp/x.txt"


def test_le_resume_est_borne_et_sur_une_ligne() -> None:
    long = _demande(arguments={"command": "echo " + "a\n" * 400})
    resume = resume_de_l_action(long)
    assert "\n" not in resume
    assert len(resume) < 260 and resume.endswith("…")


def test_la_reprise_apres_accord_demande_de_relancer_l_action() -> None:
    texte = message_de_reprise(_demande(), "allow")
    assert texte.startswith("[Atelier]"), "la marque dit d'où vient le message"
    assert "pip install torch" in texte
    assert "accordé" in texte and "Relance exactement cette action" in texte


def test_la_reprise_apres_refus_dit_de_ne_pas_relancer_et_pourquoi() -> None:
    texte = message_de_reprise(_demande(), "deny", motif="pas sur ce pod")
    assert "refusé (pas sur ce pod)" in texte
    assert "Ne relance pas" in texte
    assert "Relance exactement" not in texte


def test_la_reprise_d_une_question_rend_les_reponses_de_la_personne() -> None:
    question = _demande(
        outil="AskUserQuestion",
        genre="question",
        arguments={"questions": [{"header": "Pod", "question": "Lequel ?", "options": []}]},
    )
    texte = message_de_reprise(question, "deny", reponses=[["le GPU"]])
    assert "Pod : le GPU" in texte
    assert "Relance" not in texte, "une réponse n'est pas une permission à rejouer"
    vide = message_de_reprise(question, "deny", reponses=[])
    assert "n'a pas répondu" in vide


# -- le registre ---------------------------------------------------------


def test_mettre_en_veille_garde_la_question_et_rend_la_main(tmp_path) -> None:
    registre = RegistreDesDecisions(tmp_path / "decisions")
    registre.poser(_demande())
    en_veille = registre.mettre_en_veille("r1")
    assert en_veille is not None and en_veille.veille is True
    assert registre.en_attente() == [], "plus de processus qui attende"
    relue = registre.demande_tracee("r1")
    assert relue is not None and relue.veille is True and relue.vive is False
    assert registre.repondre("r1", {"behavior": "allow"}) is False, "personne à réveiller"


def test_les_traces_du_service_precedent_deviennent_des_veilles(tmp_path) -> None:
    dossier = tmp_path / "decisions"
    RegistreDesDecisions(dossier).poser(_demande())
    apres = RegistreDesDecisions(dossier)  # redémarrage
    assert apres.reveiller_les_traces() == 1
    (restante,) = apres.orphelines()
    assert restante.veille is True
    assert apres.reveiller_les_traces() == 0, "une seule fois"


def test_une_trace_tres_ancienne_n_est_pas_reveillee(tmp_path) -> None:
    dossier = tmp_path / "decisions"
    vieille = _demande(posee_le=(datetime.now(timezone.utc) - timedelta(days=30)).isoformat())
    RegistreDesDecisions(dossier).poser(vieille)
    apres = RegistreDesDecisions(dossier)
    assert apres.reveiller_les_traces() == 0
    assert apres.orphelines()[0].veille is False


def test_pour_cette_fois_couvre_cette_action_et_rien_d_autre(tmp_path) -> None:
    registre = RegistreDesDecisions(tmp_path / "decisions")
    demande = _demande()
    regle = registre.accorder_une_fois(demande)

    assert regle.portee == "une_fois"
    assert registre.regle_qui_couvre(_demande(request_id="r2")) is not None
    autre = _demande(request_id="r3", arguments={"command": "rm -rf /"})
    assert registre.regle_qui_couvre(autre) is None, "autres arguments : on redemande"
    assert registre.regle_qui_couvre(_demande(outil="Write")) is None
    assert registre.regle_qui_couvre(_demande(session_id="autre")) is None


def test_pour_cette_fois_n_est_jamais_passe_au_cli(tmp_path) -> None:
    """Le CLI l'appliquerait à toute la durée du processus : ce ne serait plus « une fois »."""
    from mcp_gateway.atelier.decisions import reglages_cli

    registre = RegistreDesDecisions(tmp_path / "decisions")
    registre.accorder_une_fois(_demande())
    assert reglages_cli(registre.regles("s1")) == {}


def test_consommer_retire_la_regle_du_disque_aussi(tmp_path) -> None:
    dossier = tmp_path / "decisions"
    registre = RegistreDesDecisions(dossier)
    regle = registre.accorder_une_fois(_demande())
    registre.consommer(regle)
    assert registre.regles("s1") == []
    # Et un service redémarré ne la retrouve pas.
    assert RegistreDesDecisions(dossier).regles("s1") == []


# -- le harnais, avec un faux CLI qui pose vraiment une demande ---------


@pytest.fixture()
def harnais(reglages: AtelierSettings, monkeypatch: pytest.MonkeyPatch) -> ClaudeHarness:
    reglages.cli_inactivite_s = 600
    reglages.cli_processus_max = 3
    reglages.veille_apres_s = 1
    vrai_popen = subprocess.Popen

    def popen(cmd: list[str], **kw: object) -> subprocess.Popen:
        return vrai_popen([sys.executable, str(FAUX)], **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(module.subprocess, "Popen", popen)
    monkeypatch.setattr(ClaudeHarness, "_resolve_claude_bin", lambda self: FAUX)
    monkeypatch.setattr(ClaudeHarness, "BATTEMENT_ATTENTE", 0.1)
    h = ClaudeHarness(reglages)
    yield h
    for sid in list(h.processus_vivants()):
        h.interrupt(sid)


def _tour(h: ClaudeHarness, sid: str, message: str, **kw: object):
    base = h.settings.work_dir
    return h.run_turn(
        sid,
        message,
        cwd=base / "projets" / sid,
        model=None,
        resume=False,
        transcript_path=base / "t" / f"{sid}.jsonl",
        log_path=base / "l" / f"{sid}.log",
        timeout_s=30,
        permission_mode="default",
        **kw,  # type: ignore[arg-type]
    )


def test_sans_reponse_le_tour_s_endort_sans_erreur_ni_refus(harnais: ClaudeHarness) -> None:
    debut = time.monotonic()
    resultat = _tour(harnais, "veille1", "demande Bash pip install torch", peut_attendre=True)

    assert time.monotonic() - debut < 15, "le tour doit rendre la main, pas attendre une heure"
    assert resultat.exit_code == 0
    genres = [e.kind for e in resultat.events]
    assert "erreur" not in genres, "s'endormir n'est pas une erreur"
    fins = [e.cause for e in resultat.events if e.kind == "fin"]
    assert fins == ["veille"], "le tour se referme pour les écrans, sans prétendre avoir fini"
    assert not any(e.kind == "decision_rendue" for e in resultat.events), "rien n'a été rendu au CLI"
    (veille,) = [e for e in resultat.events if e.kind == "systeme" and e.cause == "veille"]
    assert veille.tool == "Bash"

    assert "veille1" not in harnais.processus_vivants(), "le processus garé est rendu"
    (gardee,) = harnais.decisions.orphelines()
    assert gardee.veille is True and gardee.arguments["command"] == "pip install torch"


def test_un_tour_sans_interlocuteur_s_endort_tout_de_suite(harnais: ClaudeHarness) -> None:
    harnais.settings.veille_apres_s = 3600  # le délai ne joue pas : personne ne regarde
    debut = time.monotonic()
    resultat = _tour(harnais, "veille2", "demande Bash curl exemple.org", peut_attendre=False)
    assert time.monotonic() - debut < 15
    assert any(e.kind == "systeme" and e.cause == "veille" for e in resultat.events)
    assert "erreur" not in [e.kind for e in resultat.events]
    assert [d.veille for d in harnais.decisions.orphelines()] == [True]


def test_une_reponse_dans_le_delai_n_endort_personne(harnais: ClaudeHarness) -> None:
    import threading

    harnais.settings.veille_apres_s = 30
    resultat_final: list = []

    def tour() -> None:
        resultat_final.append(
            _tour(harnais, "veille3", "demande Bash ls", peut_attendre=True)
        )

    fil = threading.Thread(target=tour, daemon=True)
    fil.start()
    fin = time.monotonic() + 10
    while not harnais.decisions.en_attente() and time.monotonic() < fin:
        time.sleep(0.05)
    (vive,) = harnais.decisions.en_attente()
    from mcp_gateway.atelier.decisions import reponse_autorisee

    harnais.decisions.repondre(vive.request_id, reponse_autorisee(vive.arguments))
    fil.join(timeout=15)
    (resultat,) = resultat_final
    assert not any(e.kind == "systeme" and e.cause == "veille" for e in resultat.events)
    assert "fait:ls" in resultat.text, "le CLI a bien reçu l'accord, en direct"


def test_la_regle_pour_cette_fois_laisse_passer_et_se_consomme(harnais: ClaudeHarness) -> None:
    demande = Demande(
        request_id="rx",
        session_id="veille4",
        outil="Bash",
        arguments={"command": "pip install torch"},
    )
    harnais.decisions.accorder_une_fois(demande)
    resultat = _tour(harnais, "veille4", "demande Bash pip install torch", peut_attendre=True)
    assert "fait:pip install torch" in resultat.text, "l'action relancée passe sans question"
    assert harnais.decisions.regles("veille4") == [], "et la règle est consommée"
    assert harnais.decisions.orphelines() == []
    # Une seconde fois : on redemande.
    second = _tour(harnais, "veille4", "demande Bash pip install torch", peut_attendre=False)
    assert any(e.kind == "systeme" and e.cause == "veille" for e in second.events)


def test_l_avis_part_quand_la_question_se_pose_puis_s_endort(harnais: ClaudeHarness) -> None:
    vus: list[tuple[str, str]] = []
    harnais.avis = lambda quoi, demande: vus.append((quoi, demande.outil))
    _tour(harnais, "veille5", "demande Bash ls", peut_attendre=True)
    assert vus == [("attendue", "Bash"), ("veille", "Bash")]


def test_un_avis_qui_echoue_ne_fait_pas_echouer_le_tour(harnais: ClaudeHarness) -> None:
    def casse(quoi: str, demande: Demande) -> None:
        raise RuntimeError("push injoignable")

    harnais.avis = casse
    resultat = _tour(harnais, "veille6", "demande Bash ls", peut_attendre=False)
    assert any(e.kind == "systeme" and e.cause == "veille" for e in resultat.events)
    assert "erreur" not in [e.kind for e in resultat.events]


# -- la conversation et la route -----------------------------------------


def _cle(atelier: TestClient) -> str:
    return atelier.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()


def _conversation(atelier: TestClient) -> str:
    r = atelier.post(
        "/v1/sessions",
        headers={"Authorization": f"Bearer {_cle(atelier)}"},
        json={"slug": "essai-veille"},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["session_id"]


def _en_veille(atelier: TestClient, session_id: str, **kw) -> Demande:
    demande = _demande(session_id=session_id, **kw)
    atelier.app.state.harness.decisions.deposer_en_veille(demande)
    return demande


def _restantes(atelier: TestClient, session_id: str) -> list[Demande]:
    """Les questions de CETTE conversation : le dossier factice est partagé entre tests."""
    registre = atelier.app.state.harness.decisions
    return [d for d in registre.orphelines() if d.session_id == session_id]


def _attendre(condition, delai: float = 10.0) -> bool:
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return True
        time.sleep(0.05)
    return False


def test_repondre_a_une_veille_relance_le_travail(atelier: TestClient) -> None:
    sid = _conversation(atelier)
    _en_veille(atelier, sid)
    harnais = atelier.app.state.harness
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}

    r = atelier.post("/v1/decisions/r1", headers=entete, json={"decision": "allow"})

    assert r.status_code == 200
    assert r.json()["reprise"] is True
    assert _attendre(lambda: len(harnais.appels) >= 1), "aucun tour n'est reparti"
    message = harnais.appels[-1]["message"]
    assert message.startswith("[Atelier]")
    assert "pip install torch" in message and "Relance exactement" in message
    assert _restantes(atelier, sid) == [], "la question est réglée"
    # « Pour cette fois » : une règle à usage unique, jamais durable.
    assert [r.portee for r in harnais.decisions.regles(sid)] == ["une_fois"]


def test_refuser_une_veille_relance_aussi_mais_sans_rien_accorder(atelier: TestClient) -> None:
    sid = _conversation(atelier)
    _en_veille(atelier, sid)
    harnais = atelier.app.state.harness
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}

    r = atelier.post(
        "/v1/decisions/r1", headers=entete, json={"decision": "deny", "motif": "pas ici"}
    )

    assert r.json()["reprise"] is True
    assert _attendre(lambda: len(harnais.appels) >= 1)
    assert "refusé (pas ici)" in harnais.appels[-1]["message"]
    assert harnais.decisions.regles(sid) == []


def test_classer_une_veille_ne_relance_rien(atelier: TestClient) -> None:
    """« Classer » retire la demande : réveiller l'agent pour lui dire non serait absurde."""
    sid = _conversation(atelier)
    _en_veille(atelier, sid)
    harnais = atelier.app.state.harness
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}

    r = atelier.post(
        "/v1/decisions/r1",
        headers=entete,
        json={"decision": "deny", "motif": "classée sans réponse", "reprendre": False},
    )

    assert r.status_code == 200 and r.json()["reprise"] is False
    time.sleep(0.3)
    assert harnais.appels == []
    assert _restantes(atelier, sid) == []


def test_toujours_sur_une_veille_retient_la_regle_et_relance(atelier: TestClient) -> None:
    sid = _conversation(atelier)
    _en_veille(
        atelier,
        sid,
        suggestions=[
            {"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "pip install:*"}]}
        ],
    )
    harnais = atelier.app.state.harness
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}

    r = atelier.post(
        "/v1/decisions/r1", headers=entete, json={"decision": "allow", "portee": "toujours"}
    )

    assert r.json()["reprise"] is True
    assert _attendre(lambda: len(harnais.appels) >= 1)
    portees = [x.portee for x in harnais.decisions.regles(sid)]
    assert "commande" in portees and "une_fois" not in portees, (
        "« toujours » est la règle du CLI, pas une règle à usage unique"
    )


def test_une_veille_dont_la_conversation_n_existe_plus_se_ferme_sans_reprise(
    atelier: TestClient,
) -> None:
    _en_veille(atelier, "disparue")
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    r = atelier.post("/v1/decisions/r1", headers=entete, json={"decision": "allow"})
    assert r.status_code == 200 and r.json()["reprise"] is False
    assert _restantes(atelier, "disparue") == []


def test_la_fiche_dit_en_attente_de_vous_apres_une_veille(atelier: TestClient) -> None:
    """La conversation n'est ni en échec ni terminée : elle attend la personne."""
    from mcp_gateway.atelier.events import AtelierEvent
    from mcp_gateway.atelier.harness import TurnResult

    sid = _conversation(atelier)
    harnais = atelier.app.state.harness
    store = atelier.app.state.store

    def tour_endormi(*args, **kw):
        ev = AtelierEvent(
            kind="systeme", session_id=sid, cause="veille", tool="Bash", tool_id="rq"
        )
        return TurnResult(
            session_id=sid, exit_code=0, events=[ev], log_path="", transcript_path="", text=""
        )

    harnais.run_turn = tour_endormi  # type: ignore[method-assign]
    store.send(sid, "fais-le", peut_attendre=True)

    fiche = store.get(sid)
    assert fiche.state == "idle" and fiche.cause == ""
    assert fiche.en_attente_de == "rq"
    # Un nouveau tour part : la veille est terminée.
    harnais.run_turn = lambda *a, **k: TurnResult(  # type: ignore[method-assign]
        session_id=sid, exit_code=0, events=[], log_path="", transcript_path="", text="ok"
    )
    store.send(sid, "[Atelier] reprise", peut_attendre=True)
    assert store.get(sid).en_attente_de == ""


# -- les agents lancés ---------------------------------------------------


def _lancer_un_agent_qui_dort(reglages: AtelierSettings):
    """Un client dont le harnais factice endort le premier tour de l'agent lancé."""
    from mcp_gateway.atelier.api import build_app
    from mcp_gateway.atelier.events import AtelierEvent
    from mcp_gateway.atelier.harness import TurnResult
    from mcp_gateway.atelier.lancements import ENTETE_CLE, lire_la_cle

    projet = reglages.projects_dir / "alpha"
    projet.mkdir(parents=True, exist_ok=True)
    client = TestClient(build_app(settings=reglages, use_fake=True), base_url="https://testserver")
    client.__enter__()
    harnais = client.app.state.harness
    messages: list[str] = []

    def endormi(session_id, message, **kw):
        messages.append(message)
        if len(messages) == 1:
            ev = AtelierEvent(
                kind="systeme", session_id=session_id, cause="veille", tool="Bash", tool_id="rq1"
            )
            harnais.decisions.deposer_en_veille(
                Demande(
                    request_id="rq1",
                    session_id=session_id,
                    outil="Bash",
                    arguments={"command": "pip install torch"},
                )
            )
            return TurnResult(session_id=session_id, exit_code=0, events=[ev],
                              log_path="", transcript_path="", text="")
        return TurnResult(session_id=session_id, exit_code=0, events=[],
                          log_path="", transcript_path="", text="installé")

    harnais.run_turn = endormi  # type: ignore[method-assign]
    r = client.post(
        "/v1/lancements",
        headers={ENTETE_CLE: lire_la_cle(client.app.state.settings)},
        json={
            "projet": "alpha",
            "message": "Installe torch.",
            "origine": "wikichat:trigger:essai",
            "plafonds": {"duree_s": 120},
        },
    )
    assert r.status_code == 202, r.text
    return client, r.json()["lancement"]["id"], messages


def test_un_agent_lance_qui_attend_la_personne_n_est_pas_fini(reglages: AtelierSettings) -> None:
    client, identifiant, _ = _lancer_un_agent_qui_dort(reglages)
    try:
        lanceur = client.app.state.lancements
        lanceur.attendre(identifiant, 10)
        lancement = lanceur.lire(identifiant)
        assert lancement.etat == "en_attente", "« fini » mentirait : rien n'est livré"
        assert lancement.attend == "rq1" and lancement.fini_le == ""
        assert lancement.erreur == ""
    finally:
        client.__exit__(None, None, None)


def test_la_reponse_relance_le_meme_lancement_jusqu_a_sa_fin(reglages: AtelierSettings) -> None:
    client, identifiant, messages = _lancer_un_agent_qui_dort(reglages)
    try:
        lanceur = client.app.state.lancements
        lanceur.attendre(identifiant, 10)
        entete = {"Authorization": f"Bearer {_cle(client)}"}

        r = client.post("/v1/decisions/rq1", headers=entete, json={"decision": "allow"})
        assert r.json()["reprise"] is True

        assert _attendre(lambda: lanceur.lire(identifiant).etat == "fini"), lanceur.lire(identifiant).en_dict()
        fin = lanceur.lire(identifiant)
        assert fin.texte == "installé" and fin.fini_le
        assert messages[1].startswith("[Atelier]") and "pip install torch" in messages[1]
    finally:
        client.__exit__(None, None, None)


def test_arreter_un_agent_qui_dort_ferme_sa_question(reglages: AtelierSettings) -> None:
    client, identifiant, _ = _lancer_un_agent_qui_dort(reglages)
    try:
        lanceur = client.app.state.lancements
        lanceur.attendre(identifiant, 10)
        arrete = lanceur.arreter(identifiant)
        assert arrete.etat == "arrete" and arrete.fini_le
        conversation = arrete.conversation
        restantes = [
            d
            for d in client.app.state.harness.decisions.orphelines()
            if d.session_id == conversation
        ]
        assert restantes == [], "la question d'un agent arrêté n'a plus d'objet"
    finally:
        client.__exit__(None, None, None)


def test_le_message_de_reprise_n_est_pas_pris_pour_un_mot_de_la_personne() -> None:
    """Registre D-14 : la mémoire et les compteurs lisent `isSynthetic`."""
    import json

    from mcp_gateway.atelier.harness import enregistrement_utilisateur

    de_l_atelier = json.loads(enregistrement_utilisateur("[Atelier] Tu attendais…", "s", "t"))
    de_la_personne = json.loads(enregistrement_utilisateur("Bonjour", "s", "t"))
    assert de_l_atelier["isSynthetic"] is True
    assert "isSynthetic" not in de_la_personne
