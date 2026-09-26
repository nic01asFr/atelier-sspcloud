"""Le mode par défaut est `acceptEdits`, pour tous les tours, regardés ou non.

Un tour sans interlocuteur — agent piloté, script — recevait `bypassPermissions`
faute de choix : l'app ne donnait pas le même mode que VS Code et le terminal.
Désormais la règle est la même partout (`modes_permission.mode_resolu`) : le
choix de la conversation, sinon le défaut du projet, sinon celui du service.
Un bypass se choisit ; il ne se reçoit plus par défaut.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.harness import (
    MODE_PERMISSION_DEFAUT,
    MODE_SANS_INTERLOCUTEUR,
    mode_permission_valide,
)

from test_canal_decision import _cle


def test_le_defaut_du_service_est_accept_edits() -> None:
    assert AtelierSettings().permission_mode == "acceptEdits"
    assert MODE_PERMISSION_DEFAUT == "acceptEdits"
    assert mode_permission_valide("") == "acceptEdits"


def _modes_vus(atelier: TestClient, monkeypatch) -> list[str]:
    vus: list[str] = []
    harnais = atelier.app.state.harness
    vrai = harnais.run_turn

    def espion(session_id, message, **kw):
        vus.append(kw.get("permission_mode", ""))
        return vrai(session_id, message, **kw)

    monkeypatch.setattr(harnais, "run_turn", espion)
    return vus


def test_avec_interlocuteur_le_defaut_du_service(atelier: TestClient, monkeypatch) -> None:
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    sid = atelier.post("/v1/sessions", headers=entete, json={"slug": "essai"}).json()["session_id"]
    vus = _modes_vus(atelier, monkeypatch)
    atelier.app.state.store.send(sid, "bonjour", peut_attendre=True)
    assert vus == ["acceptEdits"]


def test_sans_interlocuteur_et_sans_choix_le_tour_ne_refuse_pas_tout(
    atelier: TestClient, monkeypatch
) -> None:
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    sid = atelier.post("/v1/sessions", headers=entete, json={"slug": "essai"}).json()["session_id"]
    vus = _modes_vus(atelier, monkeypatch)
    atelier.app.state.store.send(sid, "bonjour", peut_attendre=False)
    assert vus == [MODE_SANS_INTERLOCUTEUR]


def test_le_choix_de_la_conversation_prime_meme_sans_interlocuteur(
    atelier: TestClient, monkeypatch
) -> None:
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    sid = atelier.post("/v1/sessions", headers=entete, json={"slug": "essai"}).json()["session_id"]
    assert atelier.patch(
        f"/v1/sessions/{sid}", headers=entete, json={"permission_mode": "plan"}
    ).status_code == 200
    vus = _modes_vus(atelier, monkeypatch)
    atelier.app.state.store.send(sid, "bonjour", peut_attendre=False)
    assert vus == ["plan"], "ce que la conversation a choisi, elle le garde"
