"""`/vscode` : garde des WebSockets, routes proxy de code-server fermées, relais.

`sspcloud.fr` n'est pas dans la Public Suffix List : une page de n'importe quel
pod `*.user.lab.sspcloud.fr` est « même site » que l'Atelier, et son navigateur
joint le cookie `SameSite=Lax` à un WebSocket vers `/vscode`. Sans contrôle
d'`Origin`, elle ouvrait un terminal code-server. Et `/vscode/proxy/<port>/`
menait, derrière la porte de l'Atelier, à tout service local du pod.

Le relais parle à un vrai serveur WebSocket (faux_service_ws).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from mcp_gateway.atelier.api import build_app
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.vscode_bridge import COOKIE_NAME
from mcp_gateway.atelier.vscode_proxy import VscodeUpstream, chemin_de_proxy_interdit

from faux_service_ws import FauxService  # noqa: E402 — dossier des tests, sur sys.path

ORIGINE = "https://testserver"


@pytest.fixture()
def amont() -> Iterator[FauxService]:
    with FauxService({"/": lambda e: (200, "text/html", b"code-server")}, sous_protocoles=()) as s:
        yield s


@pytest.fixture()
def client(tmp_path: Path, amont: FauxService) -> Iterator[TestClient]:
    reglages = AtelierSettings(work_dir=tmp_path / "work", public_url=ORIGINE)
    with TestClient(build_app(settings=reglages, use_fake=True), base_url=ORIGINE) as c:
        up = VscodeUpstream(f"http://127.0.0.1:{amont.port}")
        up._ready = True  # le faux amont n'a pas de page de connexion à sonder
        up._auth_none = True
        c.app.state.vscode_upstream = up  # type: ignore[attr-defined]
        yield c


def _cookie(c: TestClient) -> dict[str, str]:
    return {"Cookie": f"{COOKIE_NAME}={c.app.state.auth.ouvrir_session()}"}  # type: ignore[attr-defined]


def _cle(c: TestClient) -> str:
    return c.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()  # type: ignore[attr-defined]


# --- routes proxy de code-server ---------------------------------------------


@pytest.mark.parametrize(
    "chemin",
    [
        "proxy/18765/",
        "PROXY/18765/",
        "/proxy/18765",
        ".//proxy/18765",
        "./proxy/18765",
        "a/../proxy/18765",
        "%2Fproxy/18765",
        "%70roxy/18765",
        "%252Fproxy%252F18765",
        "absproxy/18765/",
        "AbsProxy/18765",
        "\\proxy\\18765",
    ],
)
def test_les_variantes_du_chemin_proxy_sont_reconnues(chemin: str) -> None:
    assert chemin_de_proxy_interdit(chemin)


@pytest.mark.parametrize("chemin", ["", "static/proxy/x", "proxyfoo/1", "stable-abc/out/proxy.js"])
def test_le_reste_passe(chemin: str) -> None:
    assert not chemin_de_proxy_interdit(chemin)


@pytest.mark.parametrize(
    "url",
    [
        "/vscode/proxy/18765/",
        "/vscode/PROXY/18765/api",
        "/vscode//proxy/18765/",
        "/vscode/%2Fproxy/18765/",
        "/vscode/%70roxy/18765/",
        "/vscode/absproxy/18765/",
    ],
)
def test_http_proxy_rend_404(client: TestClient, amont: FauxService, url: str) -> None:
    avant = len(amont.vu.requetes)
    r = client.get(url, headers=_cookie(client))
    assert r.status_code == 404
    assert len(amont.vu.requetes) == avant, "rien ne doit partir vers code-server"


def test_http_ordinaire_passe(client: TestClient) -> None:
    r = client.get("/vscode/", headers=_cookie(client))
    assert r.status_code == 200
    assert r.text == "code-server"


@pytest.mark.parametrize("url", ["/vscode/proxy/18765/", "/vscode/%2Fproxy/18765", "/vscode/AbsProxy/1"])
def test_ws_proxy_refuse(client: TestClient, amont: FauxService, url: str) -> None:
    h = {**_cookie(client), "Origin": ORIGINE}
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(url, headers=h):
            pass
    assert exc.value.code == 4404
    assert amont.vu.connexions == []


# --- Origin -------------------------------------------------------------------


@pytest.mark.parametrize(
    "origine",
    ["https://evil.user.lab.sspcloud.fr", "https://testserver.evil.fr", "http://testserver", "null"],
)
def test_ws_origine_etrangere_4403(client: TestClient, amont: FauxService, origine: str) -> None:
    h = {**_cookie(client), "Origin": origine}
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/vscode/stable", headers=h):
            pass
    assert exc.value.code == 4403
    assert amont.vu.connexions == [], "aucune connexion amont avant la garde"


def test_ws_sans_origine_le_cookie_ne_suffit_pas(client: TestClient, amont: FauxService) -> None:
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/vscode/stable", headers=_cookie(client)):
            pass
    assert exc.value.code == 4403
    assert amont.vu.connexions == []


def test_ws_sans_origine_la_cle_suffit(client: TestClient, amont: FauxService) -> None:
    h = {"Authorization": f"Bearer {_cle(client)}"}
    with client.websocket_connect("/vscode/stable", headers=h) as ws:
        ws.send_text("bonjour")
        assert ws.receive_text() == "bonjour"


def test_ws_bonne_origine_sans_session_4401(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/vscode/stable", headers={"Origin": ORIGINE}):
            pass
    assert exc.value.code == 4401


# --- relais -------------------------------------------------------------------


def test_ws_relaie_et_garde_la_requete_de_code_server(client: TestClient, amont: FauxService) -> None:
    h = {**_cookie(client), "Origin": ORIGINE}
    with client.websocket_connect("/vscode/stable?reconnectionToken=abc&skipWebSocketFrames=false", headers=h) as ws:
        ws.send_bytes(b"\x00\x01")
        assert ws.receive_bytes() == b"\x00\x01"
    chemin, entetes = [r for r in amont.vu.requetes if r[0].startswith("/stable")][-1]
    assert chemin == "/stable?reconnectionToken=abc&skipWebSocketFrames=false"
    assert "authorization" not in entetes
    assert COOKIE_NAME not in entetes.get("cookie", "")


def test_ws_fermeture_amont_propagee(client: TestClient, amont: FauxService) -> None:
    h = {**_cookie(client), "Origin": ORIGINE}
    with client.websocket_connect("/vscode/stable", headers=h) as ws:
        ws.send_text("x")
        ws.receive_text()
        debut = time.monotonic()
        amont.fermer_cote_amont(4001, "fin")
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 4001
        assert time.monotonic() - debut < 1.0


def test_ws_fermeture_client_propagee(client: TestClient, amont: FauxService) -> None:
    h = {**_cookie(client), "Origin": ORIGINE}
    with client.websocket_connect("/vscode/stable", headers=h) as ws:
        ws.send_text("x")
        ws.receive_text()
        debut = time.monotonic()
        ws.close(code=4002)
    assert amont.vu.ferme.wait(1.0)
    assert time.monotonic() - debut < 1.0
    assert amont.vu.fermetures[-1] == 4002


def test_ws_amont_injoignable_ferme_proprement(client: TestClient) -> None:
    up = VscodeUpstream("http://127.0.0.1:1")
    up._ready = True
    up._auth_none = True
    client.app.state.vscode_upstream = up  # type: ignore[attr-defined]
    h = {**_cookie(client), "Origin": ORIGINE}
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/vscode/stable", headers=h):
            pass
    assert exc.value.code == 1011
