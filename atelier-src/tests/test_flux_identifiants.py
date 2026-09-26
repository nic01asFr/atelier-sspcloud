"""Un événement du flux porte l'identité de ce qu'il rapporte.

Un tour lancé depuis un onglet lui revient par deux flux : celui de l'envoi et
le flux en direct. Essai du 26/09 : la réponse s'affichait deux fois. L'onglet
reconnaît désormais le sien à ses identifiants — l'envoi, le `message.id` du
modèle, le `uuid` de la ligne du CLI — et non à son texte ni à l'heure.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from mcp_gateway.atelier.events import parse_stream_json_line


def test_un_bloc_complet_porte_son_message_et_sa_ligne() -> None:
    ligne = json.dumps(
        {
            "type": "assistant",
            "uuid": "ligne-1",
            "message": {
                "id": "msg_01",
                "content": [
                    {"type": "thinking", "thinking": "Je lis."},
                    {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "ls"}},
                ],
            },
        }
    )
    evs = parse_stream_json_line("s1", ligne)
    assert [e.kind for e in evs] == ["texte", "outil_debut"]
    assert {e.message_id for e in evs} == {"msg_01"}
    assert {e.uuid for e in evs} == {"ligne-1"}


def test_un_fragment_porte_sa_ligne_et_l_ouverture_son_message() -> None:
    fragment = json.dumps(
        {
            "type": "stream_event",
            "uuid": "ligne-2",
            "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Vo"}},
        }
    )
    (ev,) = parse_stream_json_line("s1", fragment)
    assert ev.uuid == "ligne-2"
    assert ev.message_id == ""

    resultat = json.dumps({"type": "result", "subtype": "success", "result": "Voilà.", "uuid": "ligne-3"})
    evs = parse_stream_json_line("s1", resultat)
    assert [e.kind for e in evs] == ["texte", "fin"]
    assert {e.uuid for e in evs} == {"ligne-3"}


def test_l_identite_voyage_dans_le_sse() -> None:
    (ev,) = parse_stream_json_line(
        "s1",
        json.dumps({"type": "assistant", "uuid": "u", "message": {"id": "m", "content": [{"type": "text", "text": "x"}]}}),
    )
    ev.envoi = "e1"
    donnees = json.loads(ev.as_sse().split("data: ", 1)[1])
    assert (donnees["message_id"], donnees["uuid"], donnees["envoi"]) == ("m", "u", "e1")


def test_la_route_pose_l_envoi_sur_chaque_evenement_du_tour(atelier: TestClient) -> None:
    """Le même objet part dans le flux de l'envoi et dans le flux en direct :
    l'identifiant posé ici est celui que l'onglet retrouve des deux côtés."""
    cle = atelier.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()
    entete = {"Authorization": f"Bearer {cle}"}
    sid = atelier.post("/v1/sessions", headers=entete, json={"slug": "essai", "title": "Doublon"}).json()[
        "session_id"
    ]
    r = atelier.get(f"/v1/sessions/{sid}/events?message=bonjour&envoi=envoi-26-09", headers=entete)
    assert r.status_code == 200
    donnees = [
        json.loads(ligne[len("data: "):])
        for ligne in r.text.splitlines()
        if ligne.startswith("data: ")
    ]
    assert donnees, "le tour factice rend au moins un événement"
    assert all(d.get("envoi") == "envoi-26-09" for d in donnees)
