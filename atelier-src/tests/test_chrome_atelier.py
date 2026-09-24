"""Le navigateur de l'Atelier : contrat, connecteur, bureau.

Contrat (docs/ATELIER-SPEC.md du fork `chrome-devtools-mcp`) : la
conversation passe par l'en-tête `X-Atelier-Conversation`, le jeton du
service par `Authorization`, toujours par référence dans les fichiers. Le
navigateur se reconnaît à son identifiant seul. Le bureau est servi par le
service et relayé ici, derrière la session de l'Atelier et son `Origin`.

Les tests de relais parlent à un vrai serveur HTTP/WebSocket (faux_service_ws).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from mcp_gateway.atelier.api import build_app
from mcp_gateway.atelier.chrome_ensure import TRACE_PROPOSE, ensure_chrome_mcp_connector
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.gateway_tools import GROUPE_NAVIGATEUR, nature_service
from mcp_gateway.atelier.mcp_secrets import variables_des_services
from mcp_gateway.atelier.mcp_sync import (
    SERVICE_CHROME,
    declaration_chrome,
    integrer_le_navigateur,
    pour_le_home,
    resoudre_les_variables,
)
from mcp_gateway.atelier.navigateur import declaration_du_pool, variable_du_jeton
from mcp_gateway.atelier.vscode_bridge import COOKIE_NAME

from faux_service_ws import FauxService  # noqa: E402 — dossier des tests, sur sys.path

JETON = "jeton-du-service-navigateur-0123456789abcdef"
ORIGINE = "https://testserver"


def _reglages(tmp_path: Path, url: str = "http://127.0.0.1:3100/mcp") -> AtelierSettings:
    # L'adresse publique, comme en production : c'est elle que l'Origin
    # d'une page de l'Atelier doit porter.
    s = AtelierSettings(work_dir=tmp_path / "work", chrome_mcp_url=url, public_url=ORIGINE)
    s.ensure_dirs()
    s.chrome_mcp_token_path.write_text(JETON, encoding="utf-8")
    return s


# --- le contrat, dans les fichiers --------------------------------------------


def test_la_declaration_porte_conversation_et_jeton_par_reference(tmp_path: Path) -> None:
    d = declaration_chrome(_reglages(tmp_path))
    assert d["url"] == "http://127.0.0.1:3100/mcp"
    assert "?" not in d["url"]
    assert d["headers"]["X-Atelier-Conversation"] == "${ATELIER_SESSION}"
    assert d["headers"]["Authorization"] == f"Bearer ${{{variable_du_jeton()}}}"
    assert JETON not in json.dumps(d)


def test_le_fichier_effectif_resout_la_conversation_pas_le_jeton(tmp_path: Path) -> None:
    d = resoudre_les_variables(declaration_chrome(_reglages(tmp_path)), session="0f1e-conv", agent="a")
    assert d["headers"]["X-Atelier-Conversation"] == "0f1e-conv"
    assert d["headers"]["Authorization"].startswith("Bearer ${ATELIER_MCP_")


def test_hors_conversation_la_variable_a_un_repli(tmp_path: Path) -> None:
    """VS Code lit le HOME sans ATELIER_SESSION : il partage la conversation « poste »."""
    home = pour_le_home({SERVICE_CHROME: declaration_chrome(_reglages(tmp_path))})
    assert home[SERVICE_CHROME]["headers"]["X-Atelier-Conversation"] == "${ATELIER_SESSION:-poste}"
    assert JETON not in json.dumps(home)


def test_le_jeton_arrive_par_l_environnement_depuis_le_pool(tmp_path: Path) -> None:
    variables = variables_des_services({SERVICE_CHROME: declaration_du_pool(_reglages(tmp_path))})
    assert variables == {variable_du_jeton(): JETON}


def test_un_connecteur_tiers_qui_parle_de_chrome_n_est_pas_reecrit(tmp_path: Path) -> None:
    tiers = {
        "mon-chrome": {"type": "http", "url": "http://127.0.0.1:9222/chrome-devtools/mcp"},
        "chrome-perso": {
            "type": "http",
            "url": "https://x.user.lab.sspcloud.fr/mcp",
            "headers": {"Authorization": "Bearer ${MA_VARIABLE}"},
        },
        SERVICE_CHROME: {"type": "http", "url": "https://ancien-ingress/mcp?session=x"},
    }
    sortie = integrer_le_navigateur(tiers, _reglages(tmp_path))
    assert sortie["mon-chrome"] == tiers["mon-chrome"]
    assert sortie["chrome-perso"] == tiers["chrome-perso"]
    assert sortie[SERVICE_CHROME]["url"] == "http://127.0.0.1:3100/mcp"
    for nom in ("mon-chrome", "chrome-perso"):
        nature = nature_service(tiers[nom], "http://127.0.0.1:3777/sse", nom=nom)
        assert nature["group"] != GROUPE_NAVIGATEUR


def test_c_est_du_socle_pas_un_connecteur_detachable(tmp_path: Path) -> None:
    nature = nature_service(
        declaration_chrome(_reglages(tmp_path)), "http://127.0.0.1:3777/sse", nom=SERVICE_CHROME
    )
    assert nature["system"] is True
    assert nature["group"] == GROUPE_NAVIGATEUR


def test_sans_url_configuree_rien_n_est_declare(tmp_path: Path) -> None:
    s = AtelierSettings(work_dir=tmp_path / "work")
    s.ensure_dirs()
    s.chrome_mcp_token_path.write_text(JETON, encoding="utf-8")
    assert ensure_chrome_mcp_connector(s) is None
    entree = {SERVICE_CHROME: {"type": "http", "url": "http://ailleurs/mcp"}}
    assert integrer_le_navigateur(entree, s) == entree


# --- le connecteur, dans le pool ----------------------------------------------


def _pool(s: AtelierSettings) -> dict:
    from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
    from mcp_gateway.db import connect

    conn = connect(s.gateway_db_path)
    try:
        return IntegratedMcpStore(conn).list_servers()
    finally:
        conn.close()


def _pool_faire(s: AtelierSettings, action: str) -> None:
    from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
    from mcp_gateway.db import connect

    conn = connect(s.gateway_db_path)
    try:
        store = IntegratedMcpStore(conn)
        if action == "desactiver":
            store.set_enabled(SERVICE_CHROME, False)
        elif action == "supprimer":
            store.delete(SERVICE_CHROME)
    finally:
        conn.close()


def test_ensure_cree_puis_respecte_une_desactivation(tmp_path: Path) -> None:
    s = _reglages(tmp_path)
    assert ensure_chrome_mcp_connector(s) is not None
    assert _pool(s)[SERVICE_CHROME]["enabled"] is True
    _pool_faire(s, "desactiver")
    ensure_chrome_mcp_connector(s)
    assert _pool(s)[SERVICE_CHROME]["enabled"] is False


def test_ensure_ne_recree_pas_un_connecteur_supprime(tmp_path: Path) -> None:
    s = _reglages(tmp_path)
    ensure_chrome_mcp_connector(s)
    _pool_faire(s, "supprimer")
    assert ensure_chrome_mcp_connector(s) is None
    assert SERVICE_CHROME not in _pool(s)
    # La trace effacée, il est reproposé.
    (s.mcp_dir / TRACE_PROPOSE).unlink()
    assert ensure_chrome_mcp_connector(s) is not None


def test_ensure_sans_jeton_ne_declare_rien(tmp_path: Path) -> None:
    s = _reglages(tmp_path)
    s.chrome_mcp_token_path.unlink()
    assert ensure_chrome_mcp_connector(s) is None
    assert SERVICE_CHROME not in _pool(s)


def test_la_config_materialisee_ne_porte_pas_le_jeton(tmp_path: Path) -> None:
    s = _reglages(tmp_path)
    ensure_chrome_mcp_connector(s)
    ecrit = s.mcp_config_path.read_text(encoding="utf-8")
    assert JETON not in ecrit
    assert "X-Atelier-Conversation" in ecrit


# --- le bureau, relayé --------------------------------------------------------


def _routes(bureau: bool, vus: list[str]) -> dict:
    def sante(entetes: dict[str, str]) -> tuple[int, str, bytes]:
        vus.append(entetes.get("authorization", ""))
        if entetes.get("authorization") != f"Bearer {JETON}":
            return 200, "application/json", b'{"status":"ok"}'
        corps = {"status": "ok", "bureau": bureau, "conversations": 1, "maxConversations": 3}
        return 200, "application/json", json.dumps(corps).encode()

    def vue(entetes: dict[str, str]) -> tuple[int, str, bytes]:
        if entetes.get("authorization") != f"Bearer {JETON}":
            return 401, "application/json", b"{}"
        return 200, "text/html; charset=utf-8", b"<html>page du service</html>"

    def rfb(entetes: dict[str, str]) -> tuple[int, str, bytes]:
        return 200, "text/javascript", b"export default class RFB {}"

    return {"/health": sante, "/view": vue, "/novnc/core/rfb.js": rfb}


@pytest.fixture()
def service_avec_bureau() -> Iterator[tuple[FauxService, list[str]]]:
    vus: list[str] = []
    with FauxService(_routes(True, vus)) as s:
        yield s, vus


def _atelier(tmp_path: Path, url: str) -> TestClient:
    s = _reglages(tmp_path, url)
    return TestClient(build_app(settings=s, use_fake=True), base_url=ORIGINE)


def _cookie(client: TestClient) -> dict[str, str]:
    sid = client.app.state.auth.ouvrir_session()  # type: ignore[attr-defined]
    return {"Cookie": f"{COOKIE_NAME}={sid}"}


def test_health_sans_configuration_ne_casse_pas(tmp_path: Path) -> None:
    s = AtelierSettings(work_dir=tmp_path / "work")
    with TestClient(build_app(settings=s, use_fake=True), base_url=ORIGINE) as client:
        r = client.get("/chrome/health", headers=_cookie(client))
        assert r.status_code == 200
        assert r.json()["bureau"] is False
        assert r.json()["configure"] is False
        vue = client.get("/chrome/view", headers=_cookie(client))
        assert vue.status_code == 503
        assert "/chrome/vnc" not in vue.text


def test_health_service_injoignable_ou_bavard(tmp_path: Path) -> None:
    with _atelier(tmp_path, "http://127.0.0.1:1/mcp") as client:
        r = client.get("/chrome/health", headers=_cookie(client))
        assert r.status_code == 200
        assert r.json()["joignable"] is False
    with FauxService({"/health": lambda e: (500, "text/html", b"<h1>boum</h1>")}) as s:
        with _atelier(tmp_path / "b", f"http://127.0.0.1:{s.port}/mcp") as client:
            r = client.get("/chrome/health", headers=_cookie(client))
            assert r.status_code == 200
            assert r.json()["bureau"] is False


def test_health_dit_le_bureau_et_pose_le_jeton(tmp_path: Path, service_avec_bureau) -> None:
    s, vus = service_avec_bureau
    with _atelier(tmp_path, f"http://127.0.0.1:{s.port}/mcp") as client:
        assert client.get("/chrome/health").status_code == 401
        r = client.get("/chrome/health", headers=_cookie(client))
        assert r.json()["bureau"] is True
        assert vus[-1] == f"Bearer {JETON}"
        # Le jeton ne revient jamais vers le navigateur.
        assert JETON not in r.text


def test_sans_bureau_la_vue_n_est_pas_une_page_morte(tmp_path: Path) -> None:
    with FauxService(_routes(False, [])) as s:
        with _atelier(tmp_path, f"http://127.0.0.1:{s.port}/mcp") as client:
            r = client.get("/chrome/view", headers=_cookie(client))
            assert r.status_code == 503
            assert "pas disponible" in r.text


def test_la_vue_et_novnc_viennent_du_service(tmp_path: Path, service_avec_bureau) -> None:
    s, _ = service_avec_bureau
    with _atelier(tmp_path, f"http://127.0.0.1:{s.port}/mcp") as client:
        assert client.get("/chrome/view").status_code == 401
        r = client.get("/chrome/view", headers=_cookie(client))
        assert r.status_code == 200
        assert "page du service" in r.text
        js = client.get("/chrome/novnc/core/rfb.js", headers=_cookie(client))
        assert js.status_code == 200 and "RFB" in js.text
        assert client.get("/chrome/novnc/%2e%2e/health", headers=_cookie(client)).status_code == 404


def _entetes_ws(client: TestClient, origine: str | None = ORIGINE) -> dict[str, str]:
    h = _cookie(client)
    if origine is not None:
        h["Origin"] = origine
    return h


@pytest.mark.parametrize(
    "origine", ["https://evil.user.lab.sspcloud.fr", "http://testserver", "null", None]
)
def test_vnc_refuse_une_origine_etrangere(tmp_path: Path, service_avec_bureau, origine) -> None:
    s, _ = service_avec_bureau
    with _atelier(tmp_path, f"http://127.0.0.1:{s.port}/mcp") as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/chrome/vnc", headers=_entetes_ws(client, origine)):
                pass
        assert exc.value.code == 4403
    assert s.vu.connexions == []


def test_vnc_relaie_avec_le_jeton_sans_la_requete(tmp_path: Path, service_avec_bureau) -> None:
    s, _ = service_avec_bureau
    with _atelier(tmp_path, f"http://127.0.0.1:{s.port}/mcp") as client:
        with client.websocket_connect(
            "/chrome/vnc?password=x&token=y", headers=_entetes_ws(client), subprotocols=["binary"]
        ) as ws:
            assert ws.accepted_subprotocol == "binary"
            ws.send_bytes(b"\x01\x02")
            assert ws.receive_bytes() == b"\x01\x02"
        chemin, entetes = [r for r in s.vu.requetes if r[0].startswith("/vnc")][-1]
        assert chemin == "/vnc"
        assert entetes["authorization"] == f"Bearer {JETON}"
        assert COOKIE_NAME not in entetes.get("cookie", "")


def test_vnc_fermeture_amont_propagee(tmp_path: Path, service_avec_bureau) -> None:
    s, _ = service_avec_bureau
    with _atelier(tmp_path, f"http://127.0.0.1:{s.port}/mcp") as client:
        with client.websocket_connect("/chrome/vnc", headers=_entetes_ws(client), subprotocols=["binary"]) as ws:
            ws.send_bytes(b"x")
            ws.receive_bytes()
            debut = time.monotonic()
            s.fermer_cote_amont(4001, "fin amont")
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_bytes()
            assert exc.value.code == 4001
            assert time.monotonic() - debut < 1.0


def test_vnc_fermeture_client_propagee(tmp_path: Path, service_avec_bureau) -> None:
    s, _ = service_avec_bureau
    with _atelier(tmp_path, f"http://127.0.0.1:{s.port}/mcp") as client:
        with client.websocket_connect("/chrome/vnc", headers=_entetes_ws(client), subprotocols=["binary"]) as ws:
            ws.send_bytes(b"x")
            ws.receive_bytes()
            debut = time.monotonic()
            ws.close(code=4002)
        assert s.vu.ferme.wait(1.0)
        assert time.monotonic() - debut < 1.0
        assert s.vu.fermetures[-1] == 4002
