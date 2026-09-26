"""Les services du namespace relayés par l'hôte des applications (J-d, panneau P4).

Éprouvé avec un vrai serveur de l'hôte et un vrai service « du namespace »,
chacun dans son fil, sur un port de la machine. Le service factice fait ce que
font Blender et QGIS : un noVNC (`vnc.html` et son WebSocket `websockify`),
une page sous jeton, et, pour éprouver le relais, les pires réponses qu'un
service puisse rendre : son jeton dans le corps (coupé entre deux morceaux),
dans un `Set-Cookie`, dans un `Location` ; un `X-Frame-Options` ; aucun
en-tête du tout (l'éditeur n8n, mesure A6) ; une réponse compressée.

Ce qui est vérifié est ce qu'un navigateur verrait : le jeton n'arrive
jamais de son côté, le cadrage est celui de l'Atelier, une session ouverte
pour un connecteur n'ouvre ni un projet ni un autre connecteur, et le
WebSocket du bureau est relayé avec le jeton posé côté serveur.

Seule entorse au service réel : l'amont écoute sur 127.0.0.1, ce que le
relais refuse en service (`boucle_locale`, réservé aux essais).
"""

from __future__ import annotations

import asyncio
import gzip
import json
import socket
import threading
import time
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, quote, urlsplit

import httpx
import pytest
import uvicorn
import websockets
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from mcp_gateway.atelier.apps.bureaux import (
    Bureaux,
    DeclarationInvalide,
    caviarder,
    lire_vue,
    motifs_du_jeton,
    poser_jeton,
    vues_du_pool,
)
from mcp_gateway.atelier.apps.passage import (
    COOKIE_APPS,
    Passage,
    connecteur_de_portee,
    destination_valide,
    portee_connecteur,
    portee_du_chemin,
    portee_valide,
)
from mcp_gateway.atelier.apps.serveur import construire_app_apps
from mcp_gateway.atelier.apps.service import ServiceApps
from mcp_gateway.atelier.artifacts import secret_des_jetons
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
from mcp_gateway.auth import migrate_auth_schema, open_owner_session
from mcp_gateway.db import connect

ATELIER = "https://atelier.test"
JETON = "jeton-du-service-0123456789abcdef"
COOKIE_SERVICE = "jeton_service"


def port_libre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Serveur:
    """Une application ASGI servie dans son fil, sur un port de la machine."""

    def __init__(self, app: Any, port: int) -> None:
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        self.boucle = asyncio.new_event_loop()
        self.serveur = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off", log_level="warning", proxy_headers=False)
        )
        self.fil = threading.Thread(target=self._tourner, daemon=True)
        self.fil.start()
        fin = time.time() + 10
        while not self.serveur.started:
            if time.time() > fin:
                raise RuntimeError("le serveur n'a pas démarré")
            time.sleep(0.05)

    def _tourner(self) -> None:
        asyncio.set_event_loop(self.boucle)
        self.boucle.run_until_complete(self.serveur.serve())

    def fermer(self) -> None:
        self.serveur.should_exit = True
        self.fil.join(10)


# ── Le service factice du namespace ────────────────────────────────────


def service_du_namespace() -> Starlette:
    def jeton_recu(request: Request | WebSocket) -> bool:
        return request.cookies.get(COOKIE_SERVICE) == JETON

    async def vnc(request: Request) -> Response:
        # Comme websockify : la page de noVNC, sans aucun en-tête de cadrage.
        return Response("<!DOCTYPE html><title>noVNC</title>", media_type="text/html")

    async def page(request: Request) -> Response:
        if not jeton_recu(request):
            return Response("jeton requis", status_code=401)
        corps = (
            f'<script>var jeton = "{JETON}"; var url = "/stream?token={quote(JETON, safe="")}";</script>'
            "<p>bureau</p>"
        )
        r = Response(corps, media_type="text/html")
        r.headers["X-Echo"] = f"porteur {JETON}"
        r.set_cookie(COOKIE_SERVICE, JETON, path="/")
        r.set_cookie("preference", "sombre", path="/")
        return r

    async def entetes(request: Request) -> Response:
        return JSONResponse(
            {
                "jeton_recu": jeton_recu(request),
                "cookie": request.headers.get("cookie", ""),
                "chemin": request.url.path,
                "requete": request.url.query,
                "entetes": [[k, v] for k, v in request.headers.items()],
            }
        )

    async def coupe(request: Request) -> Response:
        async def flux():
            yield b"debut-" + JETON[:7].encode()
            await asyncio.sleep(0.05)
            yield JETON[7:20].encode()
            await asyncio.sleep(0.05)
            yield JETON[20:].encode() + b"-fin"

        return StreamingResponse(flux(), media_type="text/plain")

    async def redirige(request: Request) -> Response:
        return Response(status_code=302, headers={"Location": f"http://{request.headers['host']}/page?token={JETON}"})

    async def redirige_propre(request: Request) -> Response:
        return Response(status_code=302, headers={"Location": "/vnc.html"})

    async def cadre(request: Request) -> Response:
        return Response(
            "cadre",
            headers={
                "X-Frame-Options": "SAMEORIGIN",
                "Content-Security-Policy": "frame-ancestors *; default-src 'self'",
            },
        )

    async def nu(request: Request) -> Response:
        return Response("nu")

    async def compresse(request: Request) -> Response:
        return Response(gzip.compress(JETON.encode()), headers={"Content-Encoding": "gzip"})

    async def websockify(websocket: WebSocket) -> None:
        if not jeton_recu(websocket):
            await websocket.close(code=4401)
            return
        demandes = websocket.scope.get("subprotocols") or []
        await websocket.accept(subprotocol="binary" if "binary" in demandes else None)
        try:
            while True:
                donnees = await websocket.receive_bytes()
                await websocket.send_bytes(b"rfb:" + donnees)
        except WebSocketDisconnect:
            return

    async def websockify_libre(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_bytes(b"RFB 003.008\n")
        await websocket.close()

    return Starlette(
        routes=[
            Route("/vnc.html", vnc),
            Route("/page", page),
            Route("/entetes", entetes, methods=["GET", "POST"]),
            Route("/coupe", coupe),
            Route("/redirige", redirige),
            Route("/redirige-propre", redirige_propre),
            Route("/cadre", cadre),
            Route("/nu", nu),
            Route("/compresse", compresse),
            WebSocketRoute("/websockify", websockify),
            WebSocketRoute("/libre", websockify_libre),
        ]
    )


# ── Montage : pool, hôte, sessions ─────────────────────────────────────


def declarer_le_pool(settings: AtelierSettings, amont: str) -> None:
    conn = connect(settings.gateway_db_path)
    try:
        store = IntegratedMcpStore(conn)
        store.upsert(
            "blender",
            {
                "type": "http",
                "url": "http://blender-remote-mcp:8100/mcp",
                "headers": {"Authorization": f"Bearer {JETON}"},
                "atelier": {
                    "vues": [
                        {
                            "nom": "bureau",
                            "genre": "bureau",
                            "amont": amont,
                            "vnc": "/websockify",
                            "titre": "Bureau Blender",
                            "jeton": {"depuis": "entete:Authorization", "pose": f"cookie:{COOKIE_SERVICE}"},
                        }
                    ]
                },
            },
        )
        store.upsert(
            "qgis",
            {
                "type": "http",
                "url": "http://qgis-hub:8888/mcp",
                "atelier": {"vues": [{"nom": "bureau", "genre": "bureau", "amont": amont, "vnc": "/libre"}]},
            },
        )
    finally:
        conn.close()


def lire_le_pool(settings: AtelierSettings) -> dict[str, Any]:
    conn = connect(settings.gateway_db_path)
    try:
        return IntegratedMcpStore(conn).list_servers()
    finally:
        conn.close()


class Monte:
    def __init__(self, service: ServiceApps, hote: Serveur, amont: Serveur) -> None:
        self.service = service
        self.hote = hote
        self.amont = amont
        self.base = hote.base


@pytest.fixture()
def monte(tmp_path: Path) -> Iterator[Monte]:
    amont = Serveur(service_du_namespace(), port_libre())
    port = port_libre()
    settings = AtelierSettings(work_dir=tmp_path / "work", apps_public_url=f"http://127.0.0.1:{port}", public_url=ATELIER)
    settings.ensure_dirs()
    site = settings.projects_dir / "demo" / "artifacts" / "site"
    site.mkdir(parents=True)
    (site / "index.html").write_text("<h1>site</h1>", encoding="utf-8")
    declarer_le_pool(settings, amont.base)
    service = ServiceApps(settings)
    service.bureaux = Bureaux(lambda: lire_le_pool(settings), settings.secrets_dir / "apps", boucle_locale=True)
    app = construire_app_apps(service, origine_atelier=lambda: ATELIER, secret_artefacts=lambda: secret_des_jetons("cle"))
    hote = Serveur(app, port)
    try:
        yield Monte(service, hote, amont)
    finally:
        hote.fermer()
        amont.fermer()


def session_owner(m: Monte) -> str:
    conn = connect(m.service.settings.gateway_db_path)
    migrate_auth_schema(conn)
    try:
        return open_owner_session(conn, 3600)
    finally:
        conn.close()


def entrer(m: Monte, portee: str, destination: str, sid: str | None = None, cookie: str | None = None) -> str:
    """Le parcours du navigateur : code émis par l'Atelier, échangé sur l'hôte."""
    code = m.service.passage.emettre_code(sid or session_owner(m), portee, destination)
    entetes = {"Cookie": f"{COOKIE_APPS}={cookie}"} if cookie else {}
    r = httpx.get(f"{m.base}/_atelier/entree", params={"code": code}, headers=entetes)
    assert r.status_code == 302, r.text
    for valeur in r.headers.get_list("set-cookie"):
        if valeur.startswith(COOKIE_APPS + "="):
            return valeur.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError("pas de cookie de session posé")


def entrer_connecteur(m: Monte, nom: str, **kw: Any) -> str:
    return entrer(m, portee_connecteur(nom), f"/_services/{nom}/bureau/vnc.html", **kw)


def client(cookie: str | None = None, autres_cookies: str = "") -> httpx.Client:
    valeurs = [f"{COOKIE_APPS}={cookie}"] if cookie else []
    if autres_cookies:
        valeurs.append(autres_cookies)
    entetes = {"Cookie": "; ".join(valeurs)} if valeurs else {}
    return httpx.Client(headers=entetes, timeout=30, trust_env=False, follow_redirects=False)


def rien_du_jeton(r: httpx.Response) -> None:
    """Ni le corps, ni aucun en-tête ne porte le jeton, sous aucune forme."""
    for motif in motifs_du_jeton(JETON):
        assert motif not in r.content, r.content[:300]
        for cle, valeur in r.headers.multi_items():
            assert motif.decode() not in valeur, (cle, valeur)


def directives_de_cadrage(r: httpx.Response) -> list[str]:
    vues = []
    for csp in r.headers.get_list("content-security-policy"):
        for d in csp.split(";"):
            d = d.strip()
            if d.lower().startswith("frame-ancestors"):
                vues.append(d)
    return vues


# ── Le jeton : posé côté serveur, jamais rendu au navigateur ───────────


def test_le_jeton_est_pose_cote_serveur_et_jamais_rendu(monte: Monte) -> None:
    cookie = entrer_connecteur(monte, "blender")
    with client(cookie, autres_cookies=f"{COOKIE_SERVICE}=forge-par-la-page") as c:
        r = c.get(f"{monte.base}/_services/blender/bureau/page")
        assert r.status_code == 200, r.text
        assert "<p>bureau</p>" in r.text
        rien_du_jeton(r)
        # Le cookie du service est retiré ; un autre cookie de la page passe, ramené au préfixe.
        poses = r.headers.get_list("set-cookie")
        assert not any(v.startswith(COOKIE_SERVICE + "=") for v in poses)
        assert any(v.startswith("preference=sombre") and "Path=/_services/blender/bureau/" in v for v in poses)

        # L'amont a bien reçu le vrai jeton, et pas celui qu'une page aurait forgé.
        r = c.get(f"{monte.base}/_services/blender/bureau/entetes?a=1")
        rien_du_jeton(r)
        vu = r.json()
        assert vu["jeton_recu"] is True
        assert "forge-par-la-page" not in vu["cookie"]
        assert COOKIE_APPS not in vu["cookie"]
        assert vu["chemin"] == "/entetes" and vu["requete"] == "a=1"
        noms = {k.lower() for k, _ in vu["entetes"]}
        assert "x-atelier-acces" in noms and "authorization" not in noms

        # Coupé entre trois morceaux, le jeton ne passe pas davantage.
        r = c.get(f"{monte.base}/_services/blender/bureau/coupe")
        assert r.status_code == 200
        assert r.text == "debut--fin"
        rien_du_jeton(r)

        # Un `Location` qui le porte disparaît ; un autre est ramené sous le préfixe.
        r = c.get(f"{monte.base}/_services/blender/bureau/redirige")
        rien_du_jeton(r)
        assert "location" not in r.headers
        r = c.get(f"{monte.base}/_services/blender/bureau/redirige-propre")
        assert r.status_code == 302
        assert r.headers["location"] == "/_services/blender/bureau/vnc.html"


def test_une_reponse_compressee_n_est_pas_relayee_quand_un_jeton_est_pose(monte: Monte) -> None:
    """On ne caviarde pas ce qu'on ne lit pas : mieux vaut une erreur qu'un jeton qui fuit."""
    cookie = entrer_connecteur(monte, "blender")
    with client(cookie) as c:
        r = c.get(f"{monte.base}/_services/blender/bureau/compresse")
    assert r.status_code == 502
    rien_du_jeton(r)
    assert gzip.compress(JETON.encode())[:10] not in r.content


def test_l_adresse_d_ouverture_ne_porte_pas_le_jeton(monte: Monte) -> None:
    vue = monte.service.bureaux.vue("blender", "bureau")
    assert vue is not None
    assert JETON not in vue.adresse_accueil
    assert JETON not in json.dumps(monte.service.bureaux.fiches())
    assert "amont" not in json.dumps(monte.service.bureaux.fiches())


# ── Le cadrage : l'Atelier seul, quoi que dise l'amont ─────────────────


def test_un_amont_sans_entete_est_restreint_a_l_atelier(monte: Monte) -> None:
    """Mesure A6 : l'éditeur n8n n'envoie rien ; relayé, il ne s'encadre que dans l'Atelier."""
    cookie = entrer_connecteur(monte, "qgis")
    with client(cookie) as c:
        r = c.get(f"{monte.base}/_services/qgis/bureau/nu")
        assert r.status_code == 200 and r.text == "nu"
        assert directives_de_cadrage(r) == [f"frame-ancestors {ATELIER}"]
        assert "x-frame-options" not in r.headers

        r = c.get(f"{monte.base}/_services/qgis/bureau/vnc.html")
        assert r.status_code == 200 and "noVNC" in r.text
        assert directives_de_cadrage(r) == [f"frame-ancestors {ATELIER}"]


def test_l_amont_ne_choisit_pas_qui_l_encadre(monte: Monte) -> None:
    cookie = entrer_connecteur(monte, "qgis")
    with client(cookie) as c:
        r = c.get(f"{monte.base}/_services/qgis/bureau/cadre")
    assert r.status_code == 200
    assert "x-frame-options" not in r.headers
    assert directives_de_cadrage(r) == [f"frame-ancestors {ATELIER}"]
    assert "default-src 'self'" in r.headers.get_list("content-security-policy")


# ── La portée « connecteur » ───────────────────────────────────────────


def test_une_session_de_connecteur_n_ouvre_ni_un_autre_connecteur_ni_un_projet(monte: Monte) -> None:
    cookie = entrer_connecteur(monte, "qgis")
    with client(cookie) as c:
        assert c.get(f"{monte.base}/_services/qgis/bureau/vnc.html").status_code == 200
        # Un autre connecteur : pas servi, renvoyé vers l'Atelier (401 hors navigation).
        r = c.get(f"{monte.base}/_services/blender/bureau/vnc.html")
        assert r.status_code == 401 and "noVNC" not in r.text
        r = c.get(f"{monte.base}/_services/blender/bureau/vnc.html", headers={"Sec-Fetch-Mode": "navigate"})
        assert r.status_code == 302
        assert r.headers["location"].startswith(f"{ATELIER}/v1/apps/entree?suite=")
        # Un projet : pas davantage.
        r = c.get(f"{monte.base}/demo/site/")
        assert r.status_code == 401 and "site" not in r.text


def test_une_session_de_projet_n_ouvre_aucun_connecteur(monte: Monte) -> None:
    cookie = entrer(monte, "demo", "/demo/site/")
    with client(cookie) as c:
        # La création est servie (sous son jeton de lecture, d'où le renvoi).
        r = c.get(f"{monte.base}/demo/site/")
        assert r.status_code == 302 and r.headers["location"].startswith("/demo/@")
        r = c.get(f"{monte.base}/_services/qgis/bureau/vnc.html")
        assert r.status_code == 401 and "noVNC" not in r.text


def test_un_code_de_connecteur_ne_mene_que_sous_ce_connecteur(monte: Monte) -> None:
    sid = session_owner(monte)
    for destination in ("/demo/site/", "/_services/blender/bureau/", "/_services/qgis/../blender/bureau/"):
        with pytest.raises(ValueError):
            monte.service.passage.emettre_code(sid, portee_connecteur("qgis"), destination)
    with pytest.raises(ValueError):
        monte.service.passage.emettre_code_agent("agent:conv-1", portee_connecteur("qgis"), "/_services/qgis/bureau/")


def test_une_vue_inconnue_est_un_404(monte: Monte) -> None:
    cookie = entrer_connecteur(monte, "qgis")
    with client(cookie) as c:
        assert c.get(f"{monte.base}/_services/qgis/editeur/").status_code == 404
        assert c.get(f"{monte.base}/_services/inconnu/bureau/").status_code == 404


def test_la_racine_d_une_vue_se_termine_par_une_barre(monte: Monte) -> None:
    cookie = entrer_connecteur(monte, "qgis")
    with client(cookie) as c:
        r = c.get(f"{monte.base}/_services/qgis/bureau?x=1")
    assert r.status_code == 308
    assert r.headers["location"].endswith("/_services/qgis/bureau/?x=1")


# ── Le WebSocket du bureau ─────────────────────────────────────────────


def _ws(m: Monte, cookie: str | None, chemin: str, origine: str | None = "defaut", **options: Any):
    entetes = [("Cookie", f"{COOKIE_APPS}={cookie}")] if cookie else []
    return websockets.connect(
        f"ws://127.0.0.1:{m.hote.port}{chemin}",
        origin=(m.base if origine == "defaut" else origine),
        additional_headers=entetes,
        open_timeout=10,
        **options,
    )


def test_le_websocket_du_bureau_est_relaye_avec_le_jeton_pose_cote_serveur(monte: Monte) -> None:
    cookie = entrer_connecteur(monte, "blender")

    async def scenario() -> None:
        async with _ws(monte, cookie, "/_services/blender/bureau/websockify", subprotocols=["binary"]) as ws:
            assert ws.subprotocol == "binary"
            await ws.send(b"\x00\x01poignee")
            # L'amont ferme en 4401 sans son jeton : l'écho prouve qu'il l'a reçu.
            assert await ws.recv() == b"rfb:\x00\x01poignee"

    asyncio.run(scenario())


def test_le_websocket_d_un_bureau_refuse_origine_session_et_autre_connecteur(monte: Monte) -> None:
    cookie_blender = entrer_connecteur(monte, "blender")
    cookie_qgis = entrer_connecteur(monte, "qgis")
    cookie_projet = entrer(monte, "demo", "/demo/site/")

    async def refuse(**kw: Any) -> None:
        with pytest.raises((websockets.InvalidStatus, websockets.ConnectionClosed)):
            async with _ws(monte, **kw) as ws:
                await ws.recv()

    async def scenario() -> None:
        chemin = "/_services/blender/bureau/websockify"
        await refuse(cookie=cookie_blender, chemin=chemin, origine=None)
        await refuse(cookie=cookie_blender, chemin=chemin, origine="https://voisin.user.lab.sspcloud.fr")
        await refuse(cookie=cookie_blender, chemin=chemin, origine=ATELIER)
        await refuse(cookie=None, chemin=chemin)
        await refuse(cookie=cookie_qgis, chemin=chemin)
        await refuse(cookie=cookie_projet, chemin=chemin)
        await refuse(cookie=cookie_blender, chemin="/_services/blender/inconnue/websockify")

    asyncio.run(scenario())


def test_un_bureau_sans_jeton_relaie_aussi_son_websocket(monte: Monte) -> None:
    cookie = entrer_connecteur(monte, "qgis")

    async def scenario() -> None:
        async with _ws(monte, cookie, "/_services/qgis/bureau/libre") as ws:
            assert await ws.recv() == b"RFB 003.008\n"

    asyncio.run(scenario())


# ── Côté Atelier : le catalogue et l'ouverture ─────────────────────────


@pytest.fixture()
def atelier(tmp_path: Path) -> Iterator[TestClient]:
    from mcp_gateway.atelier.api import build_app

    settings = AtelierSettings(work_dir=tmp_path / "work", apps_public_url="https://apps.test", public_url="https://testserver")
    settings.ensure_dirs()
    pool = {
        "blender": {
            "enabled": True,
            "url": "http://blender-remote-mcp:8100/mcp",
            "headers": {"Authorization": f"Bearer {JETON}"},
            "atelier": {
                "vues": [
                    {
                        "nom": "bureau",
                        "genre": "bureau",
                        "amont": "http://blender-remote-mcp:6080",
                        "jeton": {"depuis": "entete:Authorization", "pose": "cookie:blender_token"},
                    },
                    {"nom": "local", "genre": "application", "amont": "http://127.0.0.1:8787"},
                ]
            },
        },
        "n8n": {"enabled": False, "url": "http://n8n/mcp", "atelier": {"vues": [{"nom": "editeur", "genre": "application", "amont": "http://n8n:5678"}]}},
    }
    with TestClient(build_app(settings=settings, use_fake=True), base_url="https://testserver") as c:
        c.app.state.apps.bureaux = Bureaux(lambda: pool, settings.secrets_dir / "apps")
        yield c


def _porteur(c: TestClient) -> dict[str, str]:
    cle = c.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()
    return {"Authorization": f"Bearer {cle}"}


def test_le_catalogue_ne_montre_ni_amont_ni_jeton(atelier: TestClient) -> None:
    r = atelier.get("/v1/bureaux", headers=_porteur(atelier))
    assert r.status_code == 200
    corps = r.json()
    assert [(v["connecteur"], v["nom"], v["genre"]) for v in corps["vues"]] == [("blender", "bureau", "bureau")]
    assert corps["vues"][0]["ouvrir"] == "/v1/bureaux/blender/bureau/ouvrir"
    # L'amont en boucle locale est refusé, et dit pourquoi ; un connecteur coupé ne montre rien.
    assert [(e["connecteur"], e["vue"]) for e in corps["refusees"]] == [("blender", "local")]
    assert JETON not in r.text and "6080" not in r.text and "n8n" not in r.text


def test_ouvrir_emet_un_code_de_la_portee_du_connecteur(atelier: TestClient) -> None:
    atelier.post("/v1/auth/cookie", headers=_porteur(atelier))
    r = atelier.get("/v1/bureaux/blender/bureau/ouvrir", follow_redirects=False)
    assert r.status_code == 302, r.text
    vers = urlsplit(r.headers["location"])
    assert f"{vers.scheme}://{vers.netloc}" == "https://apps.test" and vers.path == "/_atelier/entree"
    assert JETON not in r.headers["location"]
    code = atelier.app.state.apps.passage.consommer_code(parse_qs(vers.query)["code"][0])
    assert code is not None
    assert code.portee == "connecteur:blender"
    assert code.destination.startswith("/_services/blender/bureau/vnc.html?")
    assert "path=_services%2Fblender%2Fbureau%2Fwebsockify" in code.destination
    assert atelier.get("/v1/bureaux/blender/inconnue/ouvrir", follow_redirects=False).status_code == 404
    assert atelier.get("/v1/bureaux/n8n/editeur/ouvrir", follow_redirects=False).status_code == 404


def test_ouvrir_exige_la_session_du_navigateur(atelier: TestClient) -> None:
    r = atelier.get("/v1/bureaux/blender/bureau/ouvrir", headers=_porteur(atelier), follow_redirects=False)
    assert r.status_code == 400
    assert atelier.get("/v1/bureaux/blender/bureau/ouvrir", follow_redirects=False).status_code == 401


def test_le_retour_sans_session_n_emet_de_code_que_pour_une_vue_declaree(atelier: TestClient) -> None:
    atelier.post("/v1/auth/cookie", headers=_porteur(atelier))
    r = atelier.get("/v1/apps/entree", params={"suite": "/_services/blender/bureau/vnc.html"}, follow_redirects=False)
    assert r.status_code == 302
    code = atelier.app.state.apps.passage.consommer_code(parse_qs(urlsplit(r.headers["location"]).query)["code"][0])
    assert code.portee == "connecteur:blender"
    r = atelier.get("/v1/apps/entree", params={"suite": "/_services/blender/autre/"}, follow_redirects=False)
    assert r.status_code == 404
    r = atelier.get("/v1/apps/entree", params={"suite": "/_services/n8n/editeur/"}, follow_redirects=False)
    assert r.status_code == 404


# ── La déclaration ne sort pas du pool (M3) ────────────────────────────


def test_la_cle_atelier_n_est_jamais_materialisee(tmp_path: Path) -> None:
    from mcp_gateway.atelier.mcp_sync import materialize_mcp_config

    settings = AtelierSettings(work_dir=tmp_path / "work")
    settings.ensure_dirs()
    declarer_le_pool(settings, "http://blender-remote-mcp:6080")
    assert "atelier" in lire_le_pool(settings)["blender"]
    conn = connect(settings.gateway_db_path)
    try:
        actifs = IntegratedMcpStore(conn).enabled_mcp_servers()
    finally:
        conn.close()
    assert "blender" in actifs and "atelier" not in actifs["blender"]
    chemin = materialize_mcp_config(settings)
    ecrit = json.loads(Path(chemin).read_text(encoding="utf-8"))
    assert "blender" in json.dumps(ecrit)
    assert "\"atelier\": {\"vues\"" not in json.dumps(ecrit) and "websockify" not in json.dumps(ecrit)


# ── Règles, sans serveur ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "amont",
    [
        "http://127.0.0.1:8787",
        "http://localhost:8788",
        "http://[::1]:80",
        "http://169.254.169.254",
        "http://0.0.0.0:6080",
        "http://atelier.localhost:8787",
        "ftp://blender:6080",
        "http://user:mdp@blender:6080",
        "http://blender:6080/chemin",
        "http://blender:6080?x=1",
        "blender:6080",
    ],
)
def test_un_amont_qui_designe_ce_pod_ou_mal_forme_est_refuse(amont: str) -> None:
    with pytest.raises(DeclarationInvalide):
        lire_vue("blender", {"nom": "bureau", "genre": "bureau", "amont": amont})


def test_une_vue_valide_se_lit() -> None:
    vue = lire_vue("qgis", {"nom": "bureau", "genre": "bureau", "amont": "http://qgis-workspace-nic01asfr:6080/"})
    assert vue.amont == "http://qgis-workspace-nic01asfr:6080"
    assert vue.vnc == "/websockify"
    assert vue.prefixe == "/_services/qgis/bureau"
    assert vue.chemin_amont("/_services/qgis/bureau/core/rfb.js") == "/core/rfb.js"
    assert destination_valide(vue.adresse_accueil, vue.portee)
    app = lire_vue("n8n", {"nom": "editeur", "genre": "application", "amont": "http://n8n:5678", "chemin": "garde"})
    assert app.adresse_accueil == "/_services/n8n/editeur/"
    assert app.chemin_amont("/_services/n8n/editeur/rest/login") == "/_services/n8n/editeur/rest/login"


@pytest.mark.parametrize(
    "vue",
    [
        {"nom": "Bureau", "genre": "bureau", "amont": "http://b:1"},
        {"nom": "bureau", "genre": "video", "amont": "http://b:1"},
        {"nom": "bureau", "genre": "bureau", "amont": "http://b:1", "vnc": "/../x"},
        {"nom": "bureau", "genre": "application", "amont": "http://b:1", "accueil": "//ailleurs"},
        {"nom": "bureau", "genre": "bureau", "amont": "http://b:1", "jeton": {"depuis": "valeur:abc", "pose": "cookie:t"}},
        {"nom": "bureau", "genre": "bureau", "amont": "http://b:1", "jeton": {"depuis": "secret:../x", "pose": "cookie:t"}},
        {"nom": "bureau", "genre": "bureau", "amont": "http://b:1", "jeton": {"depuis": "entete:Authorization", "pose": "url:t"}},
    ],
)
def test_une_declaration_fautive_est_refusee(vue: dict[str, Any]) -> None:
    with pytest.raises(DeclarationInvalide):
        lire_vue("blender", vue)


def test_le_pool_liste_les_refus_sans_bloquer_les_autres() -> None:
    vues, refus = vues_du_pool(
        {
            "a": {"atelier": {"vues": [{"nom": "b", "genre": "bureau", "amont": "http://a:6080"}, {"nom": "b", "genre": "bureau", "amont": "http://a:6081"}]}},
            "c": {"atelier": {"vues": "pas une liste"}},
            "d": {"enabled": False, "atelier": {"vues": [{"nom": "b", "genre": "bureau", "amont": "http://d:1"}]}},
            "e": {"url": "http://e/mcp"},
        }
    )
    assert list(vues) == [("a", "b")]
    assert [r["connecteur"] for r in refus] == ["a", "c"]


def test_poser_le_jeton_remplace_ce_que_le_client_avait_mis() -> None:
    from mcp_gateway.atelier.apps.bureaux import Jeton

    entetes, requete = poser_jeton(
        [("Cookie", "t=forge; autre=1"), ("X-Api", "forge")], "", Jeton("entete", "Authorization", "cookie", "t"), "vrai"
    )
    assert dict(entetes)["Cookie"] == "autre=1; t=vrai"
    entetes, _ = poser_jeton([("X-Api", "forge")], "", Jeton("entete", "Authorization", "entete", "X-Api"), "vrai")
    assert entetes == [("X-Api", "vrai")]
    entetes, _ = poser_jeton([], "", Jeton("entete", "Authorization", "entete", "Authorization"), "vrai")
    assert entetes == [("Authorization", "Bearer vrai")]
    _, requete = poser_jeton([], "token=forge&x=1", Jeton("entete", "Authorization", "requete", "token"), "vrai")
    assert parse_qs(requete) == {"x": ["1"], "token": ["vrai"]}


def test_caviarder_retire_le_jeton_coupe_n_importe_ou() -> None:
    motifs = motifs_du_jeton("abc/def")
    texte = b"x" * 5 + b"abc/def" + b"y" + b"abc%2Fdef" + b"z"

    async def recomposer(taille: int) -> bytes:
        async def flux():
            for i in range(0, len(texte), taille):
                yield texte[i : i + taille]

        return b"".join([m async for m in caviarder(flux(), motifs)])

    for taille in range(1, len(texte) + 1):
        assert asyncio.run(recomposer(taille)) == b"xxxxxyz", taille


def test_le_jeton_se_lit_dans_l_entree_ou_un_secret(tmp_path: Path) -> None:
    secrets = tmp_path / "apps"
    secrets.mkdir()
    (secrets / "n8n-editeur").write_text("secret-du-fichier\n", encoding="utf-8")
    pool = {
        "a": {"headers": {"authorization": "Bearer du-pool"}, "atelier": {"vues": [
            {"nom": "v", "genre": "bureau", "amont": "http://a:1", "jeton": {"depuis": "entete:Authorization", "pose": "cookie:t"}}]}},
        "b": {"headers": {"X-Cle": "${ATELIER_MCP_B}"}, "atelier": {"vues": [
            {"nom": "v", "genre": "bureau", "amont": "http://b:1", "jeton": {"depuis": "entete:X-Cle", "pose": "cookie:t"}}]}},
        "c": {"atelier": {"vues": [
            {"nom": "v", "genre": "bureau", "amont": "http://c:1", "jeton": {"depuis": "secret:n8n-editeur", "pose": "cookie:t"}}]}},
        "d": {"atelier": {"vues": [
            {"nom": "v", "genre": "bureau", "amont": "http://d:1", "jeton": {"depuis": "entete:Authorization", "pose": "cookie:t"}}]}},
    }
    b = Bureaux(lambda: pool, secrets, variables=lambda: {"ATELIER_MCP_B": "developpe"})
    assert b.valeur_du_jeton(b.vue("a", "v")) == "du-pool"
    assert b.valeur_du_jeton(b.vue("b", "v")) == "developpe"
    assert b.valeur_du_jeton(b.vue("c", "v")) == "secret-du-fichier"
    with pytest.raises(DeclarationInvalide):
        b.valeur_du_jeton(b.vue("d", "v"))


def test_les_portees_de_connecteur() -> None:
    assert portee_connecteur("qgis") == "connecteur:qgis"
    assert portee_valide("connecteur:qgis") and portee_valide("demo")
    assert not portee_valide("connecteur:") and not portee_valide("connecteur:../x")
    assert connecteur_de_portee("connecteur:qgis") == "qgis" and connecteur_de_portee("demo") is None
    assert portee_du_chemin("/_services/qgis/bureau/vnc.html") == "connecteur:qgis"
    assert portee_du_chemin("/_services/") is None
    assert portee_du_chemin("/_atelier/entree") is None
    assert destination_valide("/_services/qgis/bureau/", "connecteur:qgis")
    assert not destination_valide("/_services/qgisbis/bureau/", "connecteur:qgis")
    assert not destination_valide("/_services/blender/bureau/", "connecteur:qgis")
    assert not destination_valide("/demo/", "connecteur:qgis")
    assert not destination_valide("/_services/qgis/", "demo")


def test_une_session_de_connecteur_ne_couvre_que_lui(tmp_path: Path) -> None:
    conn = connect(tmp_path / "g.db")
    migrate_auth_schema(conn)
    sid = open_owner_session(conn, 3600)
    conn.close()
    passage = Passage(tmp_path / "g.db")
    code = passage.consommer_code(passage.emettre_code(sid, "connecteur:qgis", "/_services/qgis/bureau/"))
    session = passage.ouvrir(code)
    assert session.couvre("connecteur:qgis")
    assert not session.couvre("connecteur:blender") and not session.couvre("demo")
    assert not session.couvre("qgis")
