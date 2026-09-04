"""Chaque conversation choisit comment elle travaille.

Le harnais imposait `bypassPermissions` à tous les tours : tout passait, sans
qu'on puisse demander à un agent de réfléchir avant d'éditer. Le CLI accepte
pourtant six modes et cinq niveaux d'effort.

`manual` n'est pas proposé, et c'est mesuré : il demande une approbation à
chaque édition, or un tour en `-p` n'a personne à qui la demander — l'appel est
refusé, pas mis en attente. Un mode qui refuse tout serait pire que pas de mode.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from mcp_gateway.atelier.harness import (
    MODES_PERMISSION,
    MODE_PERMISSION_DEFAUT,
    effort_valide,
    mode_permission_valide,
)


def test_manual_n_est_pas_propose() -> None:
    """Il finirait en refus, faute d'interlocuteur dans un tour headless."""
    assert "manual" not in MODES_PERMISSION
    assert mode_permission_valide("manual") == MODE_PERMISSION_DEFAUT


def test_les_modes_utiles_sont_acceptes() -> None:
    for mode in ("plan", "acceptEdits", "auto", "dontAsk", "bypassPermissions"):
        assert mode_permission_valide(mode) == mode


def test_un_mode_inconnu_retombe_sur_le_defaut() -> None:
    """Mieux vaut travailler comme avant que refuser le tour."""
    for absurde in ("", "   ", "PLAN", "n'importe quoi", None):
        assert mode_permission_valide(absurde) == MODE_PERMISSION_DEFAUT


def test_les_niveaux_d_effort() -> None:
    for niveau in ("low", "medium", "high", "xhigh", "max"):
        assert effort_valide(niveau) == niveau
    assert effort_valide("HIGH") == "high"
    # Rien de reconnu : on ne passe pas l'option, le CLI décide.
    for absurde in ("", "enorme", None):
        assert effort_valide(absurde) == ""


def _cle(atelier: TestClient) -> str:
    return atelier.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()


def test_le_mode_se_pose_sur_une_conversation(atelier: TestClient) -> None:
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    sid = atelier.post(
        "/v1/sessions", headers=entete, json={"slug": "essai", "title": "Mode"}
    ).json()["session_id"]

    r = atelier.patch(
        f"/v1/sessions/{sid}", headers=entete, json={"permission_mode": "plan", "effort": "high"}
    )
    assert r.status_code == 200
    apres = atelier.get(f"/v1/sessions/{sid}", headers=entete).json()
    assert apres["permission_mode"] == "plan"
    assert apres["effort"] == "high"


def test_une_valeur_vide_rend_au_reglage_du_service(atelier: TestClient) -> None:
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    sid = atelier.post(
        "/v1/sessions", headers=entete, json={"slug": "essai", "title": "Retour"}
    ).json()["session_id"]
    atelier.patch(f"/v1/sessions/{sid}", headers=entete, json={"permission_mode": "plan"})
    atelier.patch(f"/v1/sessions/{sid}", headers=entete, json={"permission_mode": ""})
    assert atelier.get(f"/v1/sessions/{sid}", headers=entete).json()["permission_mode"] == ""


def test_une_conversation_ancienne_n_a_pas_de_mode(atelier: TestClient) -> None:
    """Les fiches écrites avant ce réglage doivent se relire sans broncher."""
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    sid = atelier.post(
        "/v1/sessions", headers=entete, json={"slug": "essai", "title": "Ancienne"}
    ).json()["session_id"]
    fiche = atelier.app.state.settings.sessions_dir / f"{sid}.json"
    import json

    donnees = json.loads(fiche.read_text(encoding="utf-8"))
    donnees.pop("permission_mode", None)
    donnees.pop("effort", None)
    fiche.write_text(json.dumps(donnees), encoding="utf-8")

    lue = atelier.get(f"/v1/sessions/{sid}", headers=entete)
    assert lue.status_code == 200
    assert lue.json()["permission_mode"] == ""
