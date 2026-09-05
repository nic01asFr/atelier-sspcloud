"""Une conversation peut demander l'autorisation, et l'attendre.

En `manual`, le CLI ne refuse plus : il pose la question à son hôte et attend.
Éprouvé sur le pod — trente-deux minutes sans réponse, processus vivant,
mémoire plate. L'Atelier est cet hôte, et ces tests tiennent les deux moitiés
du rendez-vous : le tour qui se bloque, et la requête HTTP qui le réveille.

Ce qui compte ici et qu'aucun test d'API ne verrait : deux fils se croisent.
Un `Event` mal posé et le tour attend pour toujours, ou repart avant qu'on ait
répondu — dans les deux cas, en silence.
"""

from __future__ import annotations

import json
import threading

from fastapi.testclient import TestClient

from mcp_gateway.atelier.decisions import (
    Demande,
    RegistreDesDecisions,
    reponse_autorisee,
    reponse_refusee,
)
from mcp_gateway.atelier.harness import demande_de_decision

LIGNE_REELLE = json.dumps(
    {
        "type": "control_request",
        "request_id": "22524a30",
        "request": {
            "subtype": "can_use_tool",
            "tool_name": "Write",
            "display_name": "Write",
            "input": {"file_path": "/home/onyxia/sonde.txt", "content": "bleu"},
            "description": "~/sonde.txt",
            "decision_reason": "Path is outside allowed working directories",
            "decision_reason_type": "workingDir",
            "permission_suggestions": [
                {"type": "setMode", "mode": "acceptEdits", "destination": "session"}
            ],
            "tool_use_id": "call_50eece",
        },
    }
)


def test_la_demande_se_lit_telle_que_le_cli_l_envoie() -> None:
    """Relevée sur le pod, pas inventée : c'est la ligne exacte reçue."""
    demande = demande_de_decision("sess", LIGNE_REELLE)
    assert demande is not None
    assert demande.outil == "Write"
    assert demande.arguments["content"] == "bleu"
    assert demande.raison_type == "workingDir"
    # Les suggestions sont les boutons de l'écran : on ne les invente pas.
    assert demande.suggestions[0]["mode"] == "acceptEdits"
    assert demande.tool_use_id == "call_50eece"


def test_le_reste_du_flux_n_est_pas_pris_pour_une_demande() -> None:
    """Le CLI mêle ses demandes à tout le reste ; on ne lit que le bon sous-type."""
    for ligne in (
        '{"type":"assistant","message":{"content":[]}}',
        '{"type":"result","subtype":"success"}',
        json.dumps({"type": "control_request", "request": {"subtype": "initialize"}}),
        "pas du json du tout",
        "",
    ):
        assert demande_de_decision("sess", ligne) is None


def _demande(request_id: str = "r1", session_id: str = "s1") -> Demande:
    return Demande(request_id=request_id, session_id=session_id, outil="Write")


def test_le_tour_attend_et_la_reponse_le_reveille(tmp_path) -> None:
    """Le cœur du canal : deux fils, un rendez-vous, aucun sondage."""
    registre = RegistreDesDecisions(tmp_path / "decisions")
    signal = registre.poser(_demande())

    reveille = threading.Event()

    def tour() -> None:
        signal.wait(timeout=5)
        reveille.set()

    fil = threading.Thread(target=tour, daemon=True)
    fil.start()
    assert not reveille.wait(timeout=0.2), "le tour est reparti sans réponse"

    assert registre.repondre("r1", reponse_autorisee({"a": 1})) is True
    assert reveille.wait(timeout=5), "le tour n'a pas été réveillé"
    assert registre.reponse("r1") == {"behavior": "allow", "updatedInput": {"a": 1}}


def test_repondre_a_une_question_que_personne_n_attend(tmp_path) -> None:
    registre = RegistreDesDecisions(tmp_path / "decisions")
    assert registre.repondre("inconnue", reponse_autorisee()) is False


def test_le_refus_porte_son_motif() -> None:
    """Le motif revient au modèle : mesuré, il le lit et change de route."""
    assert reponse_refusee("pas ici")["message"] == "pas ici"
    assert reponse_refusee()["behavior"] == "deny"


def test_la_trace_est_ecrite_des_la_question_et_effacee_a_la_reponse(tmp_path) -> None:
    """C'est elle qui rend tenable « une décision en attente peut le rester »."""
    dossier = tmp_path / "decisions"
    registre = RegistreDesDecisions(dossier)
    registre.poser(_demande())
    trace = dossier / "r1.json"
    assert trace.exists()
    assert json.loads(trace.read_text(encoding="utf-8"))["outil"] == "Write"

    registre.clore("r1")
    assert not trace.exists()
    assert registre.en_attente() == []


def test_une_question_survit_au_redemarrage_mais_se_dit_morte(tmp_path) -> None:
    """Après un redémarrage, plus personne n'attend — la question reste lisible."""
    dossier = tmp_path / "decisions"
    RegistreDesDecisions(dossier).poser(_demande())

    apres = RegistreDesDecisions(dossier)  # le service a redémarré
    assert apres.en_attente() == []
    orphelines = apres.orphelines()
    assert len(orphelines) == 1
    assert orphelines[0].outil == "Write"
    assert orphelines[0].vive is False


def test_abandonner_ne_touche_que_la_conversation_visee(tmp_path) -> None:
    registre = RegistreDesDecisions(tmp_path / "decisions")
    registre.poser(_demande("r1", "s1"))
    registre.poser(_demande("r2", "s1"))
    registre.poser(_demande("r3", "s2"))

    assert registre.abandonner("s1") == 2
    restantes = registre.en_attente()
    assert [d.request_id for d in restantes] == ["r3"]


def _cle(atelier: TestClient) -> str:
    return atelier.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()


def test_repondre_a_une_question_qui_n_existe_pas(atelier: TestClient) -> None:
    """404 : ni trace, ni tour — il n'y a rien à décider."""
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    r = atelier.post("/v1/decisions/inconnue", headers=entete, json={"decision": "allow"})
    assert r.status_code == 404


def test_on_repond_encore_a_une_question_relachee(atelier: TestClient) -> None:
    """La décision n'expire pas ; seule l'attente vive expire.

    Le tour a été relâché — sa mémoire rendue — mais la trace reste. Y
    répondre ne reprend pas ce tour-là, et la réponse le dit franchement.
    Ce qu'on accorde, en revanche, est retenu pour la suite.
    """
    registre = atelier.app.state.harness.decisions
    demande = Demande(
        request_id="rel",
        session_id="s11",
        outil="Write",
        suggestions=[{"type": "addDirectories", "directories": ["/home/onyxia"]}],
    )
    registre.poser(demande)
    registre.relacher("rel")  # le processus garé a été rendu
    assert registre.en_attente("s11") == []

    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    r = atelier.post(
        "/v1/decisions/rel",
        headers=entete,
        json={"decision": "allow", "portee": "toujours"},
    )
    assert r.status_code == 200
    corps = r.json()
    assert corps["reprise"] is False, "ce tour-là ne reprend pas, et on le dit"
    assert corps["regle"]["valeur"] == "/home/onyxia"
    assert [x.valeur for x in registre.regles("s11")] == ["/home/onyxia"]
    registre.oublier_les_regles("s11")


def test_la_route_n_accepte_que_deux_reponses(atelier: TestClient) -> None:
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    r = atelier.post("/v1/decisions/x", headers=entete, json={"decision": "peut-etre"})
    assert r.status_code == 400


def test_la_route_reveille_le_tour(atelier: TestClient) -> None:
    registre = atelier.app.state.harness.decisions
    signal = registre.poser(_demande("attendue", "s1"))
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}

    r = atelier.post(
        "/v1/decisions/attendue",
        headers=entete,
        json={"decision": "deny", "motif": "pas ce fichier"},
    )
    assert r.status_code == 200
    assert signal.is_set()
    assert registre.reponse("attendue")["message"] == "pas ce fichier"
    registre.clore("attendue")


def test_la_liste_montre_les_questions_de_partout(atelier: TestClient) -> None:
    """Sans vue d'ensemble, une question posée ailleurs resterait invisible."""
    registre = atelier.app.state.harness.decisions
    registre.poser(_demande("v1", "s1"))
    registre.poser(_demande("v2", "s2"))
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}

    tout = atelier.get("/v1/decisions", headers=entete).json()
    assert {d["request_id"] for d in tout["vives"]} == {"v1", "v2"}

    une = atelier.get("/v1/decisions?session_id=s2", headers=entete).json()
    assert [d["request_id"] for d in une["vives"]] == ["v2"]

    registre.abandonner("s1")
    registre.abandonner("s2")


def test_les_decisions_ne_sont_pas_publiques(atelier: TestClient) -> None:
    """Répondre, c'est exercer le mode : la porte est la même que le reste."""
    assert atelier.get("/v1/decisions").status_code == 401
    assert atelier.post("/v1/decisions/x", json={"decision": "allow"}).status_code == 401


class _FauxProcessus:
    """Un CLI qui vit et note ce qu'on lui écrit sur son entrée."""

    def __init__(self) -> None:
        self.recu: list[str] = []
        self.stdin = self
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def write(self, texte: str) -> None:
        self.recu.append(texte)

    def flush(self) -> None:
        pass

    def poll(self) -> None:
        return None


def test_un_tour_que_personne_ne_regarde_refuse_au_lieu_d_attendre(tmp_path) -> None:
    """Le garde-fou : sans lui, un agent resterait figé pour toujours.

    Les agents et les scripts passent par la route bloquante, qui ne sait rien
    montrer. Le canal y transformerait chaque refus d'autrefois en attente
    sans fin. On refuse donc d'office — exactement ce que faisait le CLI avant
    que ce canal existe — et le motif part au modèle.
    """
    from mcp_gateway.atelier.config import AtelierSettings
    from mcp_gateway.atelier.harness import SANS_INTERLOCUTEUR, ClaudeHarness

    harnais = ClaudeHarness(AtelierSettings(work_dir=tmp_path / "work"))
    proc = _FauxProcessus()
    vus: list[str] = []

    attendu = harnais._attendre_la_decision(
        _demande("r9", "s9"), proc, lambda ev: vus.append(ev.cause) or ev, False
    )

    assert attendu == 0.0, "on n'a pas attendu, donc rien à rendre à l'échéance"
    assert harnais.decisions.en_attente() == [], "aucune question ne doit rester posée"
    assert vus == ["refus_automatique"]
    envoye = json.loads(proc.recu[0])
    assert envoye["response"]["response"]["behavior"] == "deny"
    assert SANS_INTERLOCUTEUR in envoye["response"]["response"]["message"]


def test_un_tour_suivi_par_l_interface_attend_bel_et_bien(tmp_path) -> None:
    """Le pendant du garde-fou : quand quelqu'un peut répondre, on attend."""
    from mcp_gateway.atelier.config import AtelierSettings
    from mcp_gateway.atelier.harness import ClaudeHarness

    harnais = ClaudeHarness(AtelierSettings(work_dir=tmp_path / "work"))
    proc = _FauxProcessus()
    pose = threading.Event()

    def tour() -> None:
        harnais._attendre_la_decision(
            _demande("r10", "s10"), proc, lambda ev: pose.set() or ev, True
        )

    fil = threading.Thread(target=tour, daemon=True)
    fil.start()
    assert pose.wait(timeout=5), "la question n'a pas été posée"
    assert [d.request_id for d in harnais.decisions.en_attente()] == ["r10"]

    fil_vivant_avant = fil.is_alive()
    harnais.decisions.repondre("r10", reponse_autorisee())
    fil.join(timeout=5)
    assert fil_vivant_avant, "le tour serait reparti sans attendre"
    assert not fil.is_alive(), "le tour n'est pas reparti après la réponse"


def test_la_lecture_rend_la_main_pour_que_l_echeance_existe() -> None:
    """Sans cela, un CLI silencieux rendait l'échéance du tour inatteignable.

    Constaté sur le pod : douze minutes écoulées pour une échéance de dix, la
    boucle bloquée dans `readline` faute de ligne à lire. Là où `select` ne
    sait pas écouter le flux, on retombe sur la lecture bloquante — c'est ce
    que vérifie ce test, qui tourne aussi bien sous Windows.
    """
    import io as _io

    from mcp_gateway.atelier.harness import ligne_disponible

    flux = _io.StringIO("une ligne\nune autre\n")
    assert ligne_disponible(flux, 0.01) == "une ligne\n"
    assert ligne_disponible(flux, 0.01) == "une autre\n"
    assert ligne_disponible(flux, 0.01) == ""


def test_relacher_rend_le_processus_sans_perdre_la_question(tmp_path) -> None:
    """La mémoire du tour garé est rendue ; la décision, elle, reste à prendre.

    Un tour garé coûte environ 130 Mo qu'aucun échange ne récupère — mesuré
    sur ce pod, qui n'a pas de zone d'échange. Au bout d'un long silence on
    rend cette mémoire, et la trace prend le relais.
    """
    dossier = tmp_path / "decisions"
    registre = RegistreDesDecisions(dossier)
    registre.poser(_demande("rl", "s1"))

    registre.relacher("rl")
    assert registre.en_attente() == [], "plus personne n'attend"
    assert (dossier / "rl.json").exists(), "la question doit rester lisible"
    relue = registre.demande_tracee("rl")
    assert relue is not None and relue.vive is False
    # Et plus aucun signal : répondre ne réveillerait personne.
    assert registre.repondre("rl", reponse_autorisee()) is False


def test_l_entree_se_ferme_quand_le_tour_est_fini() -> None:
    """Sans quoi le CLI attend d'autres messages et ne sort jamais.

    Constaté après coup : chaque tour s'achevait à l'échéance murale, dix
    minutes plus tard, marqué `timeout` — et la conversation suivante refusait
    de repartir, l'identifiant de session étant « déjà utilisé ». L'entrée
    ouverte est ce qui permet de répondre aux questions ; la fermer est le
    signal de fin.
    """
    from mcp_gateway.atelier.harness import ClaudeHarness

    proc = _FauxProcessus()
    assert proc.stdin.closed is False
    ClaudeHarness._fermer_entree(proc)
    assert proc.stdin.closed is True
    # Deux fois de suite ne doit pas lever : la boucle peut y repasser.
    ClaudeHarness._fermer_entree(proc)


def test_supprimer_une_conversation_efface_jusqu_aux_questions_relachees(
    atelier: TestClient,
) -> None:
    """Sinon une question resterait affichable pour un fil qui n'existe plus.

    `abandonner` ne referme que les attentes vives ; une question relâchée
    n'est plus vive, et rien ne la retirait.
    """
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    sid = atelier.post(
        "/v1/sessions", headers=entete, json={"slug": "essai", "title": "Traces"}
    ).json()["session_id"]
    registre = atelier.app.state.harness.decisions
    registre.poser(_demande("q1", sid))
    registre.relacher("q1")  # plus vive, mais toujours tracée
    assert any(d.request_id == "q1" for d in registre.orphelines())

    atelier.delete(f"/v1/sessions/{sid}", headers=entete)
    assert not any(d.request_id == "q1" for d in registre.orphelines())


def test_on_peut_regarder_un_tour_sans_le_declencher(atelier: TestClient) -> None:
    """Deux écrans sur la même conversation doivent voir la même chose.

    Le flux d'un tour est attaché à l'adresse qui le lance — elle porte le
    message. S'y brancher pour observer relancerait le tour ; il fallait donc
    une porte qui ne fasse qu'écouter.
    """
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    sid = atelier.post(
        "/v1/sessions", headers=entete, json={"slug": "essai", "title": "Regard"}
    ).json()["session_id"]

    # La porte existe et se garde comme le reste.
    assert atelier.get(f"/v1/sessions/{sid}/live").status_code == 401
    assert atelier.get("/v1/sessions/inconnue/live", headers=entete).status_code == 404
