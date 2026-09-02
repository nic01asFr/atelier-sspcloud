"""Le point d'entrée interne ne s'ouvre qu'au porteur du secret partagé.

Il était gardé par l'adresse d'origine, ce qui ne gardait rien : derrière
l'ingress, le serveur voit celle du contrôleur. La requête venue d'Internet
passait la garde. Ces tests fixent ce qui doit rester vrai.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

CHEMIN = "/v1/internal/vscode-password"


def test_refuse_sans_secret(atelier: TestClient) -> None:
    """Sans secret posé, l'appel ne peut pas aboutir — même bien formé."""
    r = atelier.put(CHEMIN, headers={"X-Code-Server-Password": "quelconque"})
    assert r.status_code == 503


def test_refuse_un_secret_faux(atelier: TestClient) -> None:
    settings = atelier.app.state.settings
    settings.internal_secret_path.parent.mkdir(parents=True, exist_ok=True)
    settings.internal_secret_path.write_text("le-vrai-secret", encoding="utf-8")

    r = atelier.put(
        CHEMIN,
        headers={
            "X-Code-Server-Password": "quelconque",
            "X-Atelier-Internal-Secret": "un-autre-secret",
        },
    )
    assert r.status_code == 403


def test_accepte_le_bon_secret(atelier: TestClient) -> None:
    settings = atelier.app.state.settings
    settings.internal_secret_path.parent.mkdir(parents=True, exist_ok=True)
    settings.internal_secret_path.write_text("le-vrai-secret", encoding="utf-8")

    r = atelier.put(
        CHEMIN,
        headers={
            "X-Code-Server-Password": "mot-de-passe-code-server",
            "X-Atelier-Internal-Secret": "le-vrai-secret",
        },
    )
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_un_mot_de_passe_vide_reste_refuse(atelier: TestClient) -> None:
    """Le secret ouvre la porte, il ne dispense pas d'apporter quelque chose."""
    settings = atelier.app.state.settings
    settings.internal_secret_path.parent.mkdir(parents=True, exist_ok=True)
    settings.internal_secret_path.write_text("le-vrai-secret", encoding="utf-8")

    r = atelier.put(
        CHEMIN,
        headers={
            "X-Code-Server-Password": "   ",
            "X-Atelier-Internal-Secret": "le-vrai-secret",
        },
    )
    assert r.status_code == 400
