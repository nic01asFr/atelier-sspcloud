"""Le consentement OAuth ne se donne pas depuis un pod voisin.

`*.user.lab.sspcloud.fr` est un seul site : le cookie de session de l'écran
de consentement (`SameSite=Lax`) partait avec le formulaire qu'une page
voisine postait. Elle enregistrait son propre client, puis consentait en
silence au nom du propriétaire, et repartait avec un code, donc un jeton.

Ce que ces tests tiennent :

- un consentement posté d'ailleurs (`Sec-Fetch-Site` voisin, ou `Origin`
  différent) est refusé, clé ou pas ;
- la session ne dispense de la clé que pour un formulaire posté d'ici ;
- le cookie est un `__Host-`, et l'ancien nom est migré.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier.api import build_app
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.oauth import COOKIE_ANCIEN, COOKIE_NAME

RETOUR = "https://claude.ai/api/mcp/auth_callback"


@pytest.fixture()
def atelier(tmp_path: Path) -> Iterator[TestClient]:
    settings = AtelierSettings(work_dir=tmp_path / "work", public_url="https://testserver")
    with TestClient(build_app(settings=settings, use_fake=True), base_url="https://testserver") as client:
        yield client


def _defi() -> str:
    verifieur = secrets.token_urlsafe(48)
    return base64.urlsafe_b64encode(hashlib.sha256(verifieur.encode()).digest()).decode().rstrip("=")


def _cle(client: TestClient) -> str:
    return client.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()


def _enregistrer(client: TestClient) -> str:
    r = client.post("/register", json={"client_name": "x", "redirect_uris": [RETOUR]})
    assert r.status_code == 201
    return r.json()["client_id"]


def _consentir(client: TestClient, client_id: str, *, cle: str = "", **entetes: str):
    return client.post(
        "/authorize/confirm",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": RETOUR,
            "state": "s",
            "code_challenge": _defi(),
            "code_challenge_method": "S256",
        },
        data={"owner_key": cle},
        headers=entetes,
        follow_redirects=False,
    )


def _ouvrir_session(client: TestClient) -> str:
    r = _consentir(client, _enregistrer(client), cle=_cle(client), **{"Sec-Fetch-Site": "same-origin"})
    assert r.status_code in (302, 307), r.text
    pose = [v for v in r.headers.get_list("set-cookie") if v.startswith(COOKIE_NAME + "=")]
    assert pose and "Secure" in pose[0] and "Path=/" in pose[0] and "Domain" not in pose[0]
    return client.cookies.get(COOKIE_NAME)


def test_le_cookie_est_un_host() -> None:
    assert COOKIE_NAME.startswith("__Host-")


def test_un_voisin_ne_consent_pas_avec_la_session(atelier: TestClient) -> None:
    _ouvrir_session(atelier)
    client_du_voisin = _enregistrer(atelier)
    for entetes in (
        {"Sec-Fetch-Site": "same-site"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Origin": "https://voisin.user.lab.sspcloud.fr"},
    ):
        r = _consentir(atelier, client_du_voisin, **entetes)
        assert r.status_code == 403, entetes
        # La clé ne change rien à un formulaire posté d'ailleurs.
        r = _consentir(atelier, client_du_voisin, cle=_cle(atelier), **entetes)
        assert r.status_code == 403, entetes


def test_la_session_ne_dispense_de_la_cle_qu_ici(atelier: TestClient) -> None:
    _ouvrir_session(atelier)
    client_id = _enregistrer(atelier)
    # Sans en-têtes de provenance : pas un navigateur récent, la clé est exigée.
    assert _consentir(atelier, client_id).status_code == 401
    assert _consentir(atelier, client_id, **{"Sec-Fetch-Site": "same-origin"}).status_code in (302, 307)
    autre = _enregistrer(atelier)
    assert _consentir(atelier, autre, Origin="https://testserver").status_code in (302, 307)


def test_l_ancien_cookie_est_migre(atelier: TestClient) -> None:
    sid = _ouvrir_session(atelier)
    atelier.cookies.clear()
    r = _consentir(
        atelier, _enregistrer(atelier), **{"Sec-Fetch-Site": "same-origin", "Cookie": f"{COOKIE_ANCIEN}={sid}"}
    )
    assert r.status_code in (302, 307), r.text
    poses = r.headers.get_list("set-cookie")
    assert any(p.startswith(f"{COOKIE_NAME}={sid}") for p in poses)
    assert any(p.startswith(f"{COOKIE_ANCIEN}=") and "Max-Age=0" in p for p in poses)
