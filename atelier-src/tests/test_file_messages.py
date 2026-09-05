"""Écrire pendant qu'un tour travaille, sans le bousculer.

Le composeur se désactivait tant qu'un tour tournait, et la route acceptait
pourtant un second envoi — deux processus se seraient alors disputé le même
identifiant de session.

Le CLI, lui, tient déjà la file : un message écrit sur son entrée pendant
qu'il travaille est gardé, puis traité, dans le même processus et la même
session. Mesuré sur le pod, en glissant un message à la troisième seconde
d'un tour : la première réponse est allée au bout, la seconde a suivi.

On pourrait donc écrire aussitôt. On diffère, pour trois raisons que ces
tests tiennent : un tour qui tombe emporterait ce qui attend dans son entrée ;
un message déjà parti ne s'annule plus ; et seul le fil du tour doit écrire
dans cette entrée, faute de quoi deux écritures pourraient couper une ligne
JSON en deux.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from mcp_gateway.atelier.harness import FileDesMessages

from test_canal_decision import _cle


def test_les_messages_partent_dans_l_ordre_ou_ils_arrivent() -> None:
    file = FileDesMessages()
    file.deposer("s1", "premier")
    file.deposer("s1", "second")

    assert file.retirer("s1")["texte"] == "premier"
    assert file.retirer("s1")["texte"] == "second"
    assert file.retirer("s1") is None


def test_une_file_ne_deborde_pas_sur_une_autre_conversation() -> None:
    file = FileDesMessages()
    file.deposer("s1", "pour un")
    file.deposer("s2", "pour deux")

    assert file.retirer("s1")["texte"] == "pour un"
    assert file.retirer("s1") is None
    assert file.retirer("s2")["texte"] == "pour deux"


def test_un_message_s_annule_tant_qu_il_n_est_pas_parti() -> None:
    """C'est la raison d'être de la file : parti, il ne se reprend plus."""
    file = FileDesMessages()
    file.deposer("s1", "à garder")
    regrette = file.deposer("s1", "à retirer")

    assert file.annuler("s1", regrette) is True
    assert file.annuler("s1", regrette) is False, "on ne l'annule pas deux fois"
    assert [m["texte"] for m in file.en_attente("s1")] == ["à garder"]


def test_un_tour_qui_s_arrete_ne_laisse_pas_de_message_orphelin() -> None:
    """Sinon on croirait qu'ils partiront, alors que plus rien ne les porte."""
    file = FileDesMessages()
    file.deposer("s1", "un")
    file.deposer("s1", "deux")

    assert file.vider("s1") == 2
    assert file.en_attente("s1") == []


def test_ecrire_pendant_un_tour_met_en_file_au_lieu_de_lancer(
    atelier: TestClient,
) -> None:
    """Deux tours sur le même identifiant de session se marcheraient dessus."""
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    sid = atelier.post(
        "/v1/sessions", headers=entete, json={"slug": "essai", "title": "File"}
    ).json()["session_id"]

    # On place la conversation dans l'état qu'aurait un tour en cours.
    fiche = atelier.app.state.settings.sessions_dir / f"{sid}.json"
    import json

    donnees = json.loads(fiche.read_text(encoding="utf-8"))
    donnees["state"] = "running"
    fiche.write_text(json.dumps(donnees), encoding="utf-8")

    r = atelier.post(
        f"/v1/sessions/{sid}/messages", headers=entete, json={"message": "en retard"}
    )
    assert r.status_code == 200

    attente = atelier.get(f"/v1/sessions/{sid}/file", headers=entete).json()["messages"]
    assert [m["texte"] for m in attente] == ["en retard"]


def test_la_file_se_lit_et_se_defait_par_l_api(atelier: TestClient) -> None:
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    sid = atelier.post(
        "/v1/sessions", headers=entete, json={"slug": "essai", "title": "File deux"}
    ).json()["session_id"]
    identifiant = atelier.app.state.harness.messages.deposer(sid, "à retirer")

    assert (
        atelier.delete(f"/v1/sessions/{sid}/file/{identifiant}", headers=entete).status_code
        == 200
    )
    assert atelier.get(f"/v1/sessions/{sid}/file", headers=entete).json()["messages"] == []
    # Un message déjà retiré n'existe plus : on le dit, on ne fait pas semblant.
    assert (
        atelier.delete(f"/v1/sessions/{sid}/file/{identifiant}", headers=entete).status_code
        == 404
    )


def test_la_file_n_est_pas_publique(atelier: TestClient) -> None:
    assert atelier.get("/v1/sessions/x/file").status_code == 401
    assert atelier.delete("/v1/sessions/x/file/y").status_code == 401


def test_supprimer_une_conversation_emporte_sa_configuration_mcp(
    atelier: TestClient,
) -> None:
    """Elle est refaite à chaque tour ; celle d'un fil disparu ne sert plus.

    Soixante et une traînaient sur le pod pour quatorze conversations.
    """
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    sid = atelier.post(
        "/v1/sessions", headers=entete, json={"slug": "essai", "title": "Config"}
    ).json()["session_id"]
    reglages = atelier.app.state.settings
    reglages.mcp_effective_dir.mkdir(parents=True, exist_ok=True)
    trace = reglages.mcp_effective_dir / f"{sid}.json"
    trace.write_text("{}", encoding="utf-8")

    atelier.delete(f"/v1/sessions/{sid}", headers=entete)
    assert not trace.exists()
