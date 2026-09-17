"""Ranger un projet ne doit pas vouloir dire le perdre.

Relevé le 17 septembre 2026 sur le pod : dix-sept projets existaient, cinq
s'affichaient ; douze étaient rangés, avec cinq conversations, et l'interface
n'offrait aucun moyen de les revoir ni de les ressortir. Le service doit donc
dire d'un projet qu'il est rangé, et savoir rendre ce qui l'est quand on le
demande.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from test_canal_decision import _cle


def _projets(atelier: TestClient, entete: dict, **params) -> dict[str, dict]:
    liste = atelier.get("/v1/projects", headers=entete, params=params).json()["projects"]
    return {p["slug"]: p for p in liste}


def test_un_projet_dit_s_il_est_range(atelier: TestClient) -> None:
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    atelier.post(
        "/v1/projects", headers=entete, json={"slug": "tiroir", "kind": "code", "title": "Tiroir"}
    )
    assert _projets(atelier, entete)["tiroir"]["archived"] is False

    atelier.patch("/v1/projects/tiroir", headers=entete, json={"archived": True})
    assert "tiroir" not in _projets(atelier, entete)
    range = _projets(atelier, entete, include_archived="true")["tiroir"]
    assert range["archived"] is True, "rangé, mais toujours là et reconnaissable"
    assert range["title"] == "Tiroir", "il garde son nom"


def test_les_conversations_suivent_leur_projet(atelier: TestClient) -> None:
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    atelier.post(
        "/v1/projects", headers=entete, json={"slug": "tiroir2", "kind": "code", "title": "Tiroir 2"}
    )
    sid = atelier.post(
        "/v1/sessions", headers=entete, json={"slug": "tiroir2", "title": "Dedans"}
    ).json()["session_id"]

    def visible(**params) -> bool:
        liste = atelier.get("/v1/sessions", headers=entete, params=params).json()["sessions"]
        return any(s["session_id"] == sid for s in liste)

    assert visible()
    atelier.patch("/v1/projects/tiroir2", headers=entete, json={"archived": True})
    assert not visible(), "rangée avec son projet"
    assert visible(include_archived="true"), "et retrouvable quand on demande à voir"
    atelier.patch("/v1/projects/tiroir2", headers=entete, json={"archived": False})
    assert visible(), "ressortie avec lui"
    atelier.delete(f"/v1/sessions/{sid}", headers=entete)
