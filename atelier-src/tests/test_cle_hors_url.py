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
MEME_ORIGINE = {"Sec-Fetch-Site": "same-origin"}


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
    # Comme l'`EventSource` de l'interface : même origine. Ce GET lance un
    # tour ; venu d'ailleurs, il est refusé (voir `GardeDesCookies`).
    r = atelier.get(f"{CHEMIN}?message=bonjour", headers=MEME_ORIGINE)
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


def test_une_image_de_la_page_ne_lance_pas_de_tour(atelier: TestClient) -> None:
    """Relecture du 03/10 : `![](/v1/sessions/<id>/events?message=…)` dans une bulle.

    Le navigateur charge l'image seul, avec le cookie et `Sec-Fetch-Site:
    same-origin` : sans garde sur la destination, cela lançait un tour au nom du
    propriétaire. Seul un `EventSource` (destination `empty`) ou une navigation
    visible (`document`) a le droit d'agir.
    """
    atelier.post("/v1/auth/cookie", headers={"Authorization": f"Bearer {_cle(atelier)}"})
    for destination in ("image", "script", "style", "iframe", "embed", "object", "audio", "video", "track", "font"):
        r = atelier.get(f"{CHEMIN}?message=piege", headers={**MEME_ORIGINE, "Sec-Fetch-Dest": destination})
        assert r.status_code == 403, destination
    for destination in ("empty", "document"):
        r = atelier.get(f"{CHEMIN}?message=bonjour", headers={**MEME_ORIGINE, "Sec-Fetch-Dest": destination})
        assert r.status_code == 404, destination  # passe la garde : la session n'existe pas


def test_la_garde_decide_sur_la_destination() -> None:
    from mcp_gateway.atelier.auth import raison_du_refus

    entetes = {"sec-fetch-site": "same-origin"}
    chemin = "/v1/sessions/abc/events"
    assert raison_du_refus("GET", chemin, {**entetes, "sec-fetch-dest": "image"}, set())
    assert raison_du_refus("GET", chemin, {**entetes, "sec-fetch-dest": "empty"}, set()) is None
    # Un client sans l'en-tête (non navigateur, ou ancien) reste jugé sur le site.
    assert raison_du_refus("GET", chemin, entetes, set()) is None
    # Les GET qui n'agissent pas ne sont pas concernés.
    assert raison_du_refus("GET", "/v1/sessions", {**entetes, "sec-fetch-dest": "image"}, set()) is None
