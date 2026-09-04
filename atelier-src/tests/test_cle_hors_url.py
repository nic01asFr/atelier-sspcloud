"""La clé propriétaire ne voyage plus dans une adresse.

`EventSource` ne sait pas poser d'en-tête, d'où la tentation de mettre la clé
dans l'URL — ce que l'interface faisait à chaque message envoyé. Observé en
conditions réelles : la clé s'est retrouvée en clair dans le journal du
service, dans l'historique du navigateur, et jusque dans le transcript d'une
conversation.

Une URL traverse trop d'endroits. Le cookie de session, lui, part de lui-même
en même origine et ne porte qu'un identifiant révocable.

Ce que ces tests tiennent : que le paramètre ne soit plus accepté — le laisser
« au cas où » reviendrait à garder la fuite ouverte — et que le cookie suffise.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

CHEMIN = "/v1/sessions/inexistante/events"


def _cle(atelier: TestClient) -> str:
    return atelier.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()


def test_une_cle_dans_l_adresse_ne_vaut_plus_rien(atelier: TestClient) -> None:
    """Même la vraie clé, mise là, doit être refusée."""
    r = atelier.get(f"{CHEMIN}?token={_cle(atelier)}&message=bonjour")
    assert r.status_code == 401


def test_l_en_tete_reste_accepte(atelier: TestClient) -> None:
    """Ce qui vaut pour un navigateur ne doit pas casser un appel direct.

    404 et non 401 : l'authentification est passée, c'est la session qui
    n'existe pas.
    """
    r = atelier.get(
        f"{CHEMIN}?message=bonjour",
        headers={"Authorization": f"Bearer {_cle(atelier)}"},
    )
    assert r.status_code == 404


def test_le_cookie_de_session_suffit(atelier: TestClient) -> None:
    ouverture = atelier.post(
        "/v1/auth/cookie", headers={"Authorization": f"Bearer {_cle(atelier)}"}
    )
    assert ouverture.status_code == 200
    r = atelier.get(f"{CHEMIN}?message=bonjour")
    assert r.status_code == 404


def test_sans_rien_du_tout_c_est_refuse(atelier: TestClient) -> None:
    assert atelier.get(f"{CHEMIN}?message=bonjour").status_code == 401


def test_le_front_n_ecrit_plus_la_cle_dans_l_adresse() -> None:
    """La garde côté service ne suffit pas : l'interface ne doit plus l'écrire.

    Sans cela une page encore ouverte continuerait de la répandre dans les
    journaux, même si le serveur la refuse.
    """
    from pathlib import Path

    api_js = (
        Path(__file__).resolve().parent.parent
        / "mcp_gateway/atelier/web/js/api.js"
    ).read_text(encoding="utf-8")
    debut = api_js.index("export function streamEvents")
    corps = api_js[debut : debut + 900]
    assert "token" not in corps
