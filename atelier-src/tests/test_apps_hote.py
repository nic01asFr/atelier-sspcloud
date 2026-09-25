"""L'hôte des applications, éprouvé avec un vrai serveur et une vraie application.

Le serveur de l'hôte tourne dans un fil, sur un port de la machine ; derrière
lui, `app_amont.py` est lancée par le superviseur comme n'importe quelle
application de projet. Aucun double : ce qui est vérifié ici est ce qu'un
navigateur verrait — les en-têtes que l'application reçoit, ceux qui
reviennent, un flux SSE qui arrive à mesure, un envoi de 64 Mo qui ne passe
pas par la mémoire, une WebSocket qui fait l'écho et rend son code de
fermeture.

Le passage d'authentification est pris au mot : une session owner ouverte en
base, un code émis, puis échangé à `/_atelier/entree` comme le ferait le
navigateur. Le cookie `__Host-` étant `Secure`, un client HTTP ne le
renverrait pas en clair : on le repose à la main.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import threading
import time
import tracemalloc
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
import websockets

from mcp_gateway.atelier import artifacts as art
from mcp_gateway.atelier.apps.passage import COOKIE_APPS
from mcp_gateway.atelier.apps.serveur import construire_app_apps
from mcp_gateway.atelier.apps.service import ServiceApps
from mcp_gateway.atelier.apps.superviseur import Superviseur
from mcp_gateway.atelier.artifacts import secret_des_jetons
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.auth import close_owner_session, migrate_auth_schema, open_owner_session
from mcp_gateway.db import connect

AMONT = Path(__file__).with_name("app_amont.py")
ATELIER = "https://atelier.test"


def port_libre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Hote:
    """Le serveur de l'hôte des applications, dans son fil et sa boucle."""

    def __init__(self, service: ServiceApps, app: Any, port: int) -> None:
        self.service = service
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        self.boucle = asyncio.new_event_loop()
        self.serveur = uvicorn.Server(
            # Sans `proxy_headers` : en production, le pair est le contrôleur
            # d'Ingress, qu'uvicorn ne croit pas sur parole ; ici, 127.0.0.1
            # le serait, et un `X-Forwarded-For` forgé passerait pour vrai.
            uvicorn.Config(
                app, host="127.0.0.1", port=port, lifespan="off", log_level="warning", proxy_headers=False
            )
        )
        self.fil = threading.Thread(target=self._tourner, daemon=True)
        self.fil.start()
        fin = time.time() + 10
        while not self.serveur.started:
            if time.time() > fin:
                raise RuntimeError("le serveur de l'hôte n'a pas démarré")
            time.sleep(0.05)

    def _tourner(self) -> None:
        asyncio.set_event_loop(self.boucle)
        self.boucle.run_until_complete(self.serveur.serve())

    def appel(self, coro: Any, delai: float = 30) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self.boucle).result(delai)

    def fermer(self) -> None:
        try:
            self.appel(self.service.superviseur.fermer())
        finally:
            self.serveur.should_exit = True
            self.fil.join(10)


@pytest.fixture()
def hote(tmp_path: Path):
    port = port_libre()
    debut = 21000 + (os.getpid() % 150) * 40
    settings = AtelierSettings(
        work_dir=tmp_path / "work",
        apps_public_url=f"http://127.0.0.1:{port}",
        public_url=ATELIER,
        apps_ports=f"{debut}-{debut + 30}",
    )
    settings.ensure_dirs()
    projet = settings.projects_dir / "demo"
    art = projet / "artifacts"
    art.mkdir(parents=True)

    def declarer(nom: str, **champs: Any) -> None:
        """Un artefact serveur : `artifacts/<nom>/artefact.json`."""
        donnees = {
            "version": 1,
            "commande": [sys.executable, str(AMONT), "--port", "{port}"],
            "sante": "/health",
            "demarrage_s": 30,
            "protocoles": ["http", "ws", "sse"],
        }
        donnees.update(champs)
        (art / nom).mkdir()
        (art / nom / "artefact.json").write_text(json.dumps(donnees), encoding="utf-8")
        (art / nom / "secret-du-code.py").write_text("CLE = 'ne pas servir'", encoding="utf-8")

    declarer("amont")
    declarer("petit", corps_max_mo=1, protocoles=["http"])
    # Des artefacts autonomes : des fichiers, et rien d'autre.
    (art / "site").mkdir()
    (art / "site" / "index.html").write_text("<h1>site</h1>", encoding="utf-8")
    (art / "rapport").mkdir()
    (art / "rapport" / "index.html").write_text("<p>accueil</p>", encoding="utf-8")
    (art / "page.html").write_text("<p>page</p>", encoding="utf-8")
    # L'ancien marqueur de corpus, toujours honoré pour l'écriture.
    (art / "corpus").mkdir()
    (art / "corpus" / ".corpus").write_text("", encoding="utf-8")
    (art / "corpus" / "note.md").write_text("# note", encoding="utf-8")
    # L'édition déclarée par le manifeste d'un artefact autonome.
    (art / "notes").mkdir()
    (art / "notes" / "artefact.json").write_text(
        json.dumps({"version": 1, "type": "statique", "edition": True}), encoding="utf-8"
    )
    (art / "notes" / "a.md").write_text("# a", encoding="utf-8")
    # Un autre projet : une session ouverte pour `demo` ne l'ouvre pas.
    (settings.projects_dir / "autre" / "artifacts" / "x").mkdir(parents=True)
    (settings.projects_dir / "autre" / "artifacts" / "x" / "index.html").write_text("x", encoding="utf-8")

    service = ServiceApps(settings, Superviseur(settings, pas_demarrage_s=0.1, delai_sigkill_s=3))
    cle = "cle-de-test"
    app = construire_app_apps(
        service, origine_atelier=lambda: ATELIER, secret_artefacts=lambda: secret_des_jetons(cle)
    )
    h = Hote(service, app, port)
    try:
        yield h
    finally:
        h.fermer()


def session_owner(h: Hote) -> str:
    conn = connect(h.service.settings.gateway_db_path)
    migrate_auth_schema(conn)
    try:
        return open_owner_session(conn, 3600)
    finally:
        conn.close()


def entrer(h: Hote, portee: str, destination: str | None = None, sid: str | None = None) -> str:
    """Le parcours du navigateur : code émis par l'Atelier, échangé ici."""
    sid = sid or session_owner(h)
    code = h.service.passage.emettre_code(sid, portee, destination or f"/{portee}/")
    r = httpx.get(f"{h.base}/_atelier/entree", params={"code": code})
    assert r.status_code == 302, r.text
    for valeur in r.headers.get_list("set-cookie"):
        if valeur.startswith(COOKIE_APPS + "="):
            return valeur.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError("pas de cookie de session posé")


def client(cookie: str | None = None, **entetes: str) -> httpx.Client:
    h = dict(entetes)
    if cookie:
        h["Cookie"] = f"{COOKIE_APPS}={cookie}"
    return httpx.Client(headers=h, timeout=30, trust_env=False)


def attendre_pret(h: Hote, cookie: str, nom: str = "amont") -> None:
    with client(cookie) as c:
        fin = time.time() + 40
        while time.time() < fin:
            r = c.get(f"{h.base}/demo/{nom}/health")
            if r.status_code == 200:
                return
            assert r.status_code == 503, r.text
            time.sleep(0.2)
    raise AssertionError("l'application n'a pas démarré")


# ── L'hôte et le passage ───────────────────────────────────────────────


def test_un_hote_etranger_recoit_421_sauf_la_sante(hote: Hote) -> None:
    r = httpx.get(f"{hote.base}/demo/amont/", headers={"Host": "atelier.test"})
    assert r.status_code == 421
    assert httpx.get(f"{hote.base}/_sante", headers={"Host": "nimporte"}).status_code == 200


def test_sans_session_on_retourne_a_l_atelier(hote: Hote) -> None:
    r = httpx.get(f"{hote.base}/demo/amont/x?y=1", headers={"Sec-Fetch-Mode": "navigate"})
    assert r.status_code == 302
    assert r.headers["location"] == f"{ATELIER}/v1/apps/entree?suite=%2Fdemo%2Famont%2Fx%3Fy%3D1"
    assert httpx.get(f"{hote.base}/demo/amont/health").status_code == 401


def test_le_code_ouvre_une_session_une_seule_fois(hote: Hote) -> None:
    sid = session_owner(hote)
    code = hote.service.passage.emettre_code(sid, "demo", "/demo/amont/page?x=1")
    r = httpx.get(f"{hote.base}/_atelier/entree", params={"code": code})
    assert r.status_code == 302
    assert r.headers["location"] == "/demo/amont/page?x=1"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "no-store" in r.headers["cache-control"]
    pose = [v for v in r.headers.get_list("set-cookie") if v.startswith(COOKIE_APPS)][0].lower()
    assert "httponly" in pose and "secure" in pose and "samesite=lax" in pose and "path=/" in pose
    assert "domain" not in pose
    assert httpx.get(f"{hote.base}/_atelier/entree", params={"code": code}).status_code == 400


def test_une_session_ne_vaut_que_pour_son_projet(hote: Hote) -> None:
    cookie = entrer(hote, "demo")
    with client(cookie) as c:
        assert c.get(f"{hote.base}/demo/page.html").status_code == 200
        assert c.get(f"{hote.base}/autre/x/").status_code == 401


def test_la_session_tombe_avec_celle_de_l_atelier(hote: Hote) -> None:
    sid = session_owner(hote)
    cookie = entrer(hote, "demo", sid=sid)
    with client(cookie) as c:
        assert c.get(f"{hote.base}/demo/page.html").status_code == 200
        conn = connect(hote.service.settings.gateway_db_path)
        try:
            close_owner_session(conn, sid)
        finally:
            conn.close()
        assert c.get(f"{hote.base}/demo/page.html").status_code == 401


def test_une_seconde_ouverture_elargit_la_session(hote: Hote) -> None:
    sid = session_owner(hote)
    premier = entrer(hote, "demo", sid=sid)
    code = hote.service.passage.emettre_code(sid, "autre", "/autre/x/")
    r = httpx.get(
        f"{hote.base}/_atelier/entree", params={"code": code}, headers={"Cookie": f"{COOKIE_APPS}={premier}"}
    )
    second = [v for v in r.headers.get_list("set-cookie") if v.startswith(COOKIE_APPS)][0]
    assert second.split(";")[0] == f"{COOKIE_APPS}={premier}"
    with client(premier) as c:
        assert c.get(f"{hote.base}/demo/page.html").status_code == 200
        assert c.get(f"{hote.base}/autre/x/", follow_redirects=True).status_code == 200


def test_un_artefact_autonome_est_servi_sans_processus(hote: Hote) -> None:
    cookie = entrer(hote, "demo")
    with client(cookie) as c:
        r = c.get(f"{hote.base}/demo/site/")
        # Un dossier d'artefact se lit sous son jeton : ses pages relatives suivent.
        assert r.status_code == 302 and r.headers["location"].startswith("/demo/@")
        r = c.get(f"{hote.base}/demo/site/", follow_redirects=True)
        assert r.status_code == 200 and "site" in r.text
        assert r.headers["x-content-type-options"] == "nosniff"
        assert "sandbox" in r.headers["content-security-policy"]
        assert c.get(f"{hote.base}/demo/site/%2E%2E/%2E%2E/secret").status_code == 404
    assert hote.service.superviseur.etat("demo", "site") is None


def test_un_artefact_inconnu_est_un_404(hote: Hote) -> None:
    cookie = entrer(hote, "demo")
    with client(cookie) as c:
        assert c.get(f"{hote.base}/demo/inconnue/").status_code == 404


def test_le_projet_seul_renvoie_vers_son_index(hote: Hote) -> None:
    cookie = entrer(hote, "demo")
    with client(cookie) as c:
        r = c.get(f"{hote.base}/demo")
        assert r.status_code == 308 and r.headers["location"] == "/demo/"
        r = c.get(f"{hote.base}/demo/")
        assert r.status_code == 200
        assert "amont" in r.text and "site" in r.text


# ── Le mandataire HTTP ─────────────────────────────────────────────────


def test_premiere_requete_demarre_puis_relaie(hote: Hote) -> None:
    cookie = entrer(hote, "demo")
    with client(cookie) as c:
        r = c.get(f"{hote.base}/demo/amont/health")
        assert r.status_code == 503
        assert r.headers["retry-after"] == "2"
        page = c.get(f"{hote.base}/demo/amont/", headers={"Sec-Fetch-Mode": "navigate"})
        assert page.status_code in (503, 200)
    attendre_pret(hote, cookie)
    info = hote.service.superviseur.etat("demo", "amont")
    assert info.port in hote.service.superviseur.ports


def test_les_entetes_sont_nettoyes_a_l_aller(hote: Hote) -> None:
    cookie = entrer(hote, "demo")
    attendre_pret(hote, cookie)
    with client(None) as c:
        r = c.get(
            f"{hote.base}/demo/amont/entetes?a=1",
            headers={
                "Cookie": f"autre=1; {COOKIE_APPS}={cookie}",
                "Authorization": "Bearer volee",
                "X-Forwarded-For": "6.6.6.6",
                "X-Forwarded-Host": "evil",
                "Forwarded": "for=6.6.6.6",
                "X-Atelier-Acces": "tout",
                "Connection": "keep-alive, X-Saut",
                "X-Saut": "1",
            },
        )
    assert r.status_code == 200, r.text
    vu = r.json()
    entetes = {k: v for k, v in vu["entetes"]}
    assert vu["chemin"] == "/entetes" and vu["requete"] == "a=1"
    assert "authorization" not in entetes and "forwarded" not in entetes and "x-saut" not in entetes
    assert entetes["cookie"] == "autre=1"
    assert entetes["x-forwarded-for"] == "127.0.0.1"
    assert entetes["x-forwarded-host"] == f"127.0.0.1:{hote.port}"
    assert entetes["x-forwarded-prefix"] == "/demo/amont"
    assert entetes["x-forwarded-proto"] == "https"
    assert entetes["x-atelier-acces"] == "proprietaire"
    # L'amont se voit joint sur son propre port : une application qui vérifie
    # son `Host` (le SDK MCP le fait) n'y voit que 127.0.0.1.
    assert entetes["host"].startswith("127.0.0.1:")


def test_cookies_et_redirections_sont_ramenes_au_prefixe(hote: Hote) -> None:
    cookie = entrer(hote, "demo")
    attendre_pret(hote, cookie)
    with client(cookie) as c:
        poses = c.get(f"{hote.base}/demo/amont/cookie").headers.get_list("set-cookie")
        assert any(p.startswith("simple=1; Path=/demo/amont/") for p in poses)
        domaine = [p for p in poses if p.startswith("domaine=")][0]
        assert "Domain" not in domaine and "Path=/demo/amont/sous" in domaine
        assert not any(p.lower().startswith("__host-") for p in poses)
        r = c.get(f"{hote.base}/demo/amont/redirige")
        assert r.headers["location"] == "/demo/amont/health"
        r = c.get(f"{hote.base}/demo/amont/redirige?vers=amont")
        assert r.headers["location"] == f"{hote.base}/demo/amont/health?x=1"
        r = c.get(f"{hote.base}/demo/amont/redirige?vers=ailleurs")
        assert r.headers["location"] == "https://exemple.org/page"


def test_les_defauts_de_securite_sont_poses(hote: Hote) -> None:
    cookie = entrer(hote, "demo")
    attendre_pret(hote, cookie)
    with client(cookie) as c:
        r = c.get(f"{hote.base}/demo/amont/csp")
        assert r.headers.get_list("content-security-policy") == ["default-src 'self'", f"frame-ancestors {ATELIER}"]
        assert "service-worker-allowed" not in r.headers
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "same-origin"
        assert r.headers["x-accel-buffering"] == "no"
        r = c.get(f"{hote.base}/demo/amont/health")
        assert r.headers.get_list("content-security-policy") == [f"frame-ancestors {ATELIER}"]


# ── Le cadrage : l'Atelier, et lui seul, encadre ce que sert l'hôte ────


def _directives_de_cadrage(r: httpx.Response) -> list[str]:
    """Toutes les directives `frame-ancestors` que le navigateur appliquera."""
    vues = []
    for csp in r.headers.get_list("content-security-policy"):
        for d in csp.split(";"):
            d = d.strip()
            if d.lower().startswith("frame-ancestors"):
                vues.append(d)
    return vues


def test_l_amont_ne_choisit_pas_qui_l_encadre(hote: Hote) -> None:
    """n8n rend `X-Frame-Options: SAMEORIGIN` : le panneau ne pourrait pas l'afficher."""
    cookie = entrer(hote, "demo")
    attendre_pret(hote, cookie)
    with client(cookie) as c:
        r = c.get(f"{hote.base}/demo/amont/cadre")
    assert r.status_code == 200
    assert "x-frame-options" not in r.headers
    assert _directives_de_cadrage(r) == [f"frame-ancestors {ATELIER}"]
    # Le reste de la CSP de l'application tient toujours.
    assert "default-src 'self'" in r.headers.get_list("content-security-policy")


def test_les_fichiers_d_une_creation_ne_s_encadrent_que_dans_l_atelier(hote: Hote) -> None:
    cookie = entrer(hote, "demo")
    with client(cookie) as c:
        r = c.get(f"{hote.base}/demo/site/", follow_redirects=True)
    assert r.status_code == 200 and "site" in r.text
    assert _directives_de_cadrage(r) == [f"frame-ancestors {ATELIER}"]
    # Le bac à sable des fichiers reste entier : seul le cadrage a changé.
    assert any(csp.startswith("sandbox allow-scripts") for csp in r.headers.get_list("content-security-policy"))
    assert "allow-same-origin" not in " ".join(r.headers.get_list("content-security-policy"))


def test_les_pages_de_l_hote_ont_la_meme_politique(hote: Hote) -> None:
    """Lien expiré, 404, renvoi vers l'Atelier : rien ne s'encadre ailleurs."""
    with client() as c:
        for r in (
            c.get(f"{hote.base}/_atelier/entree", params={"code": "faux"}),
            c.get(f"{hote.base}/demo/site/", headers={"Accept": "text/html"}),
            c.get(f"{hote.base}/_sante"),
        ):
            assert _directives_de_cadrage(r) == [f"frame-ancestors {ATELIER}"], r.url
            assert "x-frame-options" not in r.headers


def test_une_ecriture_venue_d_un_voisin_est_refusee(hote: Hote) -> None:
    cookie = entrer(hote, "demo")
    attendre_pret(hote, cookie)
    with client(cookie) as c:
        url = f"{hote.base}/demo/amont/entetes"
        assert c.post(url, headers={"Sec-Fetch-Site": "same-site"}).status_code == 403
        assert c.post(url, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
        assert c.post(url, headers={"Origin": "https://voisin.user.lab.sspcloud.fr"}).status_code == 403
        assert c.post(url, headers={"Origin": hote.base, "Sec-Fetch-Site": "same-origin"}).status_code == 200
        assert c.get(url, headers={"Sec-Fetch-Site": "same-site"}).status_code == 200


def test_un_flux_sse_arrive_a_mesure(hote: Hote) -> None:
    cookie = entrer(hote, "demo")
    attendre_pret(hote, cookie)
    with client(cookie) as c:
        debut = time.monotonic()
        with c.stream("GET", f"{hote.base}/demo/amont/sse", headers={"Accept": "text/event-stream"}) as r:
            assert r.status_code == 200
            assert r.headers["x-accel-buffering"] == "no"
            morceaux = r.iter_raw()
            premier = next(morceaux)
            ecoule = time.monotonic() - debut
            assert b"evenement 0" in premier
            assert ecoule < 0.9, ecoule
            # Pendant le flux, la connexion compte comme activité.
            assert hote.service.superviseur.etat("demo", "amont").connexions == 1
            reste = b"".join(morceaux)
        assert b"evenement 2" in reste
    fin = time.time() + 5
    while hote.service.superviseur.etat("demo", "amont").connexions and time.time() < fin:
        time.sleep(0.05)
    assert hote.service.superviseur.etat("demo", "amont").connexions == 0


def test_un_flux_sse_non_declare_est_refuse(hote: Hote) -> None:
    cookie = entrer(hote, "demo")
    attendre_pret(hote, cookie, "petit")
    with client(cookie) as c:
        r = c.get(f"{hote.base}/demo/petit/sse", headers={"Accept": "text/event-stream"})
        assert r.status_code == 406


def test_un_gros_envoi_passe_en_flux_a_memoire_bornee(hote: Hote) -> None:
    cookie = entrer(hote, "demo")
    attendre_pret(hote, cookie)
    taille = 64 * 2**20
    morceau = b"x" * 2**16

    def corps():
        for _ in range(taille // len(morceau)):
            yield morceau

    tracemalloc.start()
    try:
        with client(cookie) as c:
            r = c.post(f"{hote.base}/demo/amont/compter", content=corps())
        _, pic = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert r.status_code == 200, r.text
    assert r.json()["octets"] == taille
    assert pic < 16 * 2**20, pic


def test_un_corps_au_dela_du_plafond_est_refuse(hote: Hote) -> None:
    cookie = entrer(hote, "demo")
    attendre_pret(hote, cookie, "petit")
    with client(cookie) as c:
        r = c.post(f"{hote.base}/demo/petit/entetes", content=b"x" * (2 * 2**20))
        assert r.status_code == 413

        def corps():
            for _ in range(40):
                yield b"x" * 2**16

        r = c.post(f"{hote.base}/demo/petit/entetes", content=corps())
        assert r.status_code == 413


# ── WebSocket ──────────────────────────────────────────────────────────


def _ws(h: Hote, cookie: str | None, chemin: str = "/demo/amont/ws", origine: str | None = "defaut", **options: Any):
    entetes = []
    if cookie:
        entetes.append(("Cookie", f"{COOKIE_APPS}={cookie}"))
    return websockets.connect(
        f"ws://127.0.0.1:{h.port}{chemin}",
        origin=(h.base if origine == "defaut" else origine),
        additional_headers=entetes,
        open_timeout=10,
        **options,
    )


def test_une_websocket_fait_l_echo_et_rend_sa_fermeture(hote: Hote) -> None:
    cookie = entrer(hote, "demo")
    attendre_pret(hote, cookie)

    async def scenario() -> None:
        async with _ws(hote, cookie, subprotocols=["echo.v1"]) as ws:
            assert ws.subprotocol == "echo.v1"
            await ws.send("bonjour")
            assert await ws.recv() == "echo:bonjour"
            await ws.send(b"\x00\x01")
            assert await ws.recv() == b"echo:\x00\x01"
            assert hote.service.superviseur.etat("demo", "amont").connexions == 1
            await ws.send("ferme")
            with pytest.raises(websockets.ConnectionClosed) as exc:
                await ws.recv()
            assert exc.value.rcvd.code == 4001

    asyncio.run(scenario())
    fin = time.time() + 5
    while hote.service.superviseur.etat("demo", "amont").connexions and time.time() < fin:
        time.sleep(0.05)
    assert hote.service.superviseur.etat("demo", "amont").connexions == 0


def test_une_websocket_sans_origine_exacte_ni_session_est_refusee(hote: Hote) -> None:
    cookie = entrer(hote, "demo")
    attendre_pret(hote, cookie)
    cookie_petit = entrer(hote, "demo")
    attendre_pret(hote, cookie_petit, "petit")

    async def refuse(**kw: Any) -> None:
        with pytest.raises((websockets.InvalidStatus, websockets.ConnectionClosed)):
            async with _ws(hote, **kw) as ws:
                await ws.recv()

    async def scenario() -> None:
        await refuse(cookie=cookie, origine=None)
        await refuse(cookie=cookie, origine="https://voisin.user.lab.sspcloud.fr")
        await refuse(cookie=None)
        # WebSocket non déclarée par l'application : refusée.
        await refuse(cookie=cookie_petit, chemin="/demo/petit/ws")

    asyncio.run(scenario())


# ── Fichiers des artefacts sur l'hôte des applications ─────────────────


def test_les_fichiers_sont_servis_en_bac_a_sable(hote: Hote) -> None:
    cookie = entrer(hote, "demo")
    with client(cookie) as c:
        r = c.get(f"{hote.base}/demo/page.html")
        assert r.status_code == 200
        csp = r.headers["content-security-policy"]
        assert "sandbox" in csp and "allow-downloads" in csp and "allow-same-origin" not in csp
        # Un dossier qui porte son index.html le montre.
        r = c.get(f"{hote.base}/demo/rapport/", follow_redirects=True)
        assert "accueil" in r.text
        # Sous jeton, une page ne joint que le préfixe de son projet.
        r = c.get(f"{hote.base}/demo/corpus/note.md")
        assert r.status_code == 302
        vers = r.headers["location"]
        assert vers.startswith("/demo/@")
        r = httpx.get(f"{hote.base}{vers}")  # sans cookie : le jeton suffit
        assert r.status_code == 200
        assert f"connect-src {hote.base}/demo/" in r.headers["content-security-policy"]


def test_le_manifeste_et_le_code_d_un_serveur_ne_sont_jamais_servis(hote: Hote) -> None:
    cookie = entrer(hote, "demo")
    with client(cookie) as c:
        r = c.get(f"{hote.base}/demo/notes/artefact.json", follow_redirects=True)
        assert r.status_code == 404
        # Un artefact serveur est relayé, jamais lu comme des fichiers : même
        # sous un jeton (émis pour lui), son code ne sort pas.
        jeton = art.signer_jeton(secret_des_jetons("cle-de-test"), "demo", "amont")
        r = httpx.get(f"{hote.base}/demo/@{jeton}/amont/secret-du-code.py")
        assert r.status_code == 409
        assert "ne pas servir" not in r.text


def test_une_page_n_ecrit_que_dans_un_artefact_en_edition(hote: Hote) -> None:
    secret = secret_des_jetons("cle-de-test")
    projet = hote.service.settings.projects_dir / "demo" / "artifacts"

    def ecrire(racine: str, chemin: str, contenu: bytes) -> httpx.Response:
        jeton = art.signer_jeton(secret, "demo", racine)
        return httpx.put(f"{hote.base}/demo/@{jeton}/{chemin}", content=contenu, headers={"Origin": "null"})

    # Édition déclarée par artefact.json.
    assert ecrire("notes", "notes/b.md", b"# b").status_code == 200
    assert (projet / "notes" / "b.md").read_bytes() == b"# b"
    # Ancien marqueur `.corpus`.
    assert ecrire("corpus", "corpus/neuve.md", b"# neuve").status_code == 200
    # Sans édition : lecture seule.
    assert ecrire("rapport", "rapport/x.html", b"x").status_code == 403
    # Jamais le manifeste, jamais un point-fichier.
    assert ecrire("notes", "notes/artefact.json", b"{}").status_code == 403
    assert ecrire("notes", "notes/.auteur", b"moi").status_code == 403
    # Jamais un artefact serveur.
    assert ecrire("amont", "amont/secret-du-code.py", b"x").status_code == 409
    # Sans jeton, cet hôte n'écrit pas.
    cookie = entrer(hote, "demo")
    with client(cookie) as c:
        assert c.put(f"{hote.base}/demo/notes/c.md", content=b"x").status_code == 401
