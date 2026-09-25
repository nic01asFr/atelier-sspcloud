"""L'hôte des applications : la seconde application ASGI de l'Atelier.

Même processus que l'Atelier, autre port (`ATELIER_APPS_PORT`, 8788), autre
Ingress, autre origine. On n'y trouve rien de l'Atelier — ni `/v1`, ni
`/vscode`, ni `/mcp`, ni `/chrome`, ni l'interface — seulement :

- `/_sante`, pour les sondes ;
- `/_atelier/entree?code=…`, qui échange un code de passage contre la
  session de cet hôte (voir `passage`) ;
- `/<slug>/`, l'index des artefacts d'un projet ;
- `/<slug>/<nom>/…`, un artefact : ses fichiers en bac à sable (mode
  autonome), ou le processus que déclare son `artefact.json`, relayé par le
  mandataire (mode serveur) ;
- `/<slug>/@<jeton>/<nom>/…`, la lecture sous jeton des pages d'un artefact
  (leurs sous-ressources partent sans cookie, d'une origine opaque).

Toute requête dont l'hôte n'est pas celui des applications reçoit 421 : un
Ingress mal réglé ne doit pas faire servir ce contenu sous une autre adresse,
encore moins sous celle de l'Atelier.

Toute réponse sort avec une seule politique de cadrage : l'Atelier, et lui
seul, peut l'encadrer (voir `cadrage`). C'est ce qui permet au panneau de
montrer une création à côté du fil.
"""

from __future__ import annotations

import html
import logging
from typing import Any, Callable
from urllib.parse import quote

import httpx
from fastapi import HTTPException
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import (
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

from mcp_gateway.atelier import artifacts as art
from mcp_gateway.atelier.apps import proxy as px
from mcp_gateway.atelier.apps.cadrage import CadrageDesReponses
from mcp_gateway.atelier.apps.manifeste import Manifeste, ManifesteInvalide, nom_valide
from mcp_gateway.atelier.apps.passage import COOKIE_APPS, DUREE_SESSION_S, destination_valide
from mcp_gateway.atelier.apps.service import ApplicationInconnue, ServiceApps
from mcp_gateway.atelier.apps.superviseur import EN_ECHEC, ErreurApplication
from mcp_gateway.atelier.artefacts_servis import ServeurArtefacts
from mcp_gateway.atelier.relais_ws import relayer

log = logging.getLogger("atelier.apps.serveur")

ENTETES_PASSAGE = {"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"}


def _page(titre: str, texte: str, *, rafraichir: int | None = None) -> str:
    meta = f'<meta http-equiv="refresh" content="{rafraichir}">' if rafraichir else ""
    return (
        '<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">'
        f"{meta}<title>{html.escape(titre)}</title>"
        "<style>body{font:15px/1.6 system-ui,sans-serif;max-width:640px;margin:15vh auto;"
        "padding:0 24px;color:#222}@media(prefers-color-scheme:dark){body{background:#1a1a1a;"
        "color:#e8e8e8}}</style></head><body>"
        f"<h1>{html.escape(titre)}</h1><p>{html.escape(texte)}</p></body></html>"
    )


def _navigation(request: Request) -> bool:
    if request.method != "GET":
        return False
    mode = request.headers.get("sec-fetch-mode")
    if mode:
        return mode == "navigate"
    return "text/html" in (request.headers.get("accept") or "")


class GardeDeLHote:
    """421 pour tout hôte qui n'est pas celui des applications (sauf `/_sante`)."""

    def __init__(self, app: Any, hote: Callable[[], str]) -> None:
        self.app = app
        self.hote = hote

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket") or scope.get("path") == "/_sante":
            await self.app(scope, receive, send)
            return
        vu = ""
        for cle, valeur in scope.get("headers") or []:
            if cle == b"host":
                vu = valeur.decode("latin-1").strip().lower()
                break
        attendu = self.hote()
        if attendu and vu == attendu:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4421})
            return
        corps = b"hote inattendu"
        await send(
            {
                "type": "http.response.start",
                "status": 421,
                "headers": [(b"content-type", b"text/plain"), (b"content-length", str(len(corps)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": corps})


def construire_app_apps(service: ServiceApps, *, origine_atelier: Callable[[], str], secret_artefacts: Callable[[], bytes]) -> Any:
    """L'application ASGI de l'hôte des applications."""
    settings = service.settings
    clients: dict[str, httpx.AsyncClient] = {}

    def client_pour(socket: str | None) -> httpx.AsyncClient:
        cle = socket or ""
        if cle not in clients:
            transport = httpx.AsyncHTTPTransport(uds=socket) if socket else httpx.AsyncHTTPTransport()
            clients[cle] = httpx.AsyncClient(
                transport=transport,
                timeout=httpx.Timeout(connect=10.0, read=None, write=None, pool=None),
                trust_env=False,
                follow_redirects=False,
            )
        return clients[cle]

    artefacts = ServeurArtefacts(
        settings.projects_dir,
        secret_artefacts,
        lambda slug: f"/{slug}/",
        connect_src=lambda slug: f"{service.origine}/{quote(slug, safe='')}/",
    )

    # ── Session ───────────────────────────────────────────────────────

    def session_couvre(request: Request | WebSocket, portee: str) -> bool:
        s = service.passage.session(request.cookies.get(COOKIE_APPS))
        return s is not None and s.couvre(portee)

    def vers_l_entree(request: Request) -> Response:
        """Sans session : retour à l'Atelier, qui émettra un code."""
        atelier = (origine_atelier() or "").rstrip("/")
        suite = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        if not atelier:
            return Response(
                _page("Session requise", "Ouvrez cette application depuis l'Atelier."),
                status_code=401,
                media_type="text/html; charset=utf-8",
                headers=ENTETES_PASSAGE,
            )
        if not _navigation(request):
            return JSONResponse({"detail": "session requise"}, status_code=401, headers=ENTETES_PASSAGE)
        return RedirectResponse(
            f"{atelier}/v1/apps/entree?suite={quote(suite, safe='')}", 302, headers=ENTETES_PASSAGE
        )

    # ── Routes ────────────────────────────────────────────────────────

    async def sante(request: Request) -> Response:
        return JSONResponse({"status": "ok", "service": "atelier-apps"})

    async def entree(request: Request) -> Response:
        code = service.passage.consommer_code(request.query_params.get("code", ""))
        if code is None or not destination_valide(code.destination, code.portee):
            return Response(
                _page("Lien expiré", "Ce lien d'ouverture a déjà servi ou a expiré. Rouvrez l'application depuis l'Atelier."),
                status_code=400,
                media_type="text/html; charset=utf-8",
                headers=ENTETES_PASSAGE,
            )
        session = service.passage.ouvrir(code, request.cookies.get(COOKIE_APPS))
        reponse = RedirectResponse(code.destination, 302, headers=ENTETES_PASSAGE)
        reponse.set_cookie(
            COOKIE_APPS,
            session.id,
            max_age=DUREE_SESSION_S,
            path="/",
            secure=True,
            httponly=True,
            samesite="lax",
        )
        return reponse

    async def projet_seul(request: Request) -> Response:
        slug = request.path_params["slug"]
        return RedirectResponse(f"/{quote(slug, safe='')}/", 308)

    async def projet(request: Request) -> Response:
        """Tout ce qui est sous `/<slug>/` : fichiers, jeton, ou service."""
        slug = request.path_params["slug"]
        reste = request.path_params.get("reste", "")
        if not art.slug_valide(slug):
            return PlainTextResponse("introuvable", status_code=404)
        tete = reste.split("/", 1)[0]
        if tete.startswith(art.PREFIXE_JETON):
            return await fichiers(request, slug, reste)
        if not session_couvre(request, slug):
            return vers_l_entree(request)
        if nom_valide(tete):
            try:
                manifeste = service.superviseur.manifeste(slug, tete) or service.manifeste(slug, tete)
            except ApplicationInconnue:
                manifeste = None
            except ManifesteInvalide as exc:
                return Response(_page("Manifeste invalide", str(exc)), 502, media_type="text/html; charset=utf-8")
            if manifeste is not None and manifeste.service:
                return await application(request, slug, tete, manifeste)
        return await fichiers(request, slug, reste)

    async def fichiers(request: Request, slug: str, chemin: str) -> Response:
        """Les fichiers des artefacts, en bac à sable (voir `artefacts_servis`)."""
        brut, rel = artefacts.separer_jeton(chemin)
        if request.method == "OPTIONS":
            return artefacts.preflight(brut is not None)
        if request.method == "PUT":
            def sans_jeton() -> None:
                # Sans jeton, l'écriture passe par l'Atelier (clé au porteur) :
                # cet hôte n'écrit que pour une page d'artefact en édition.
                raise HTTPException(401, "jeton requis")

            refus = px.refus_meme_site("PUT", request.headers, service.origine) if brut is None else None
            if refus:
                return JSONResponse({"detail": refus}, status_code=403)
            try:
                return await artefacts.ecrire(
                    request,
                    slug,
                    chemin,
                    sans_jeton=sans_jeton,
                    if_match=request.headers.get("if-match"),
                    if_none_match=request.headers.get("if-none-match"),
                )
            except HTTPException as exc:
                return artefacts.refus(exc.status_code, str(exc.detail), False)
        if request.method not in ("GET", "HEAD"):
            return PlainTextResponse("méthode refusée", status_code=405)
        try:
            if brut is None:
                return artefacts.servir(request, slug, rel)
            jeton = artefacts.lire_jeton(slug, brut)
            if jeton is None or jeton.perime():
                if session_couvre(request, slug):
                    return artefacts.redirection(artefacts.url(slug, rel, None, chemin.endswith("/")), 302)
                return artefacts.refus(401, "jeton de lecture invalide ou périmé", True)
            return artefacts.servir(request, slug, rel, jeton, brut)
        except HTTPException as exc:
            return Response(
                art.page_absente(slug), status_code=exc.status_code, media_type="text/html; charset=utf-8"
            )

    async def application(request: Request, slug: str, nom: str, manifeste: Manifeste) -> Response:
        refus = px.refus_meme_site(request.method, request.headers, service.origine)
        if refus:
            return JSONResponse({"detail": refus}, status_code=403)
        prefixe = f"/{slug}/{nom}"
        if request.url.path == prefixe:
            suite = f"?{request.url.query}" if request.url.query else ""
            return RedirectResponse(prefixe + "/" + suite, 308)
        cible = service.superviseur.cible(slug, nom)
        if cible is None:
            return await pas_encore_prete(request, slug, nom)
        return await relayer_http(request, slug, nom, manifeste, cible)

    async def pas_encore_prete(request: Request, slug: str, nom: str) -> Response:
        info = service.superviseur.etat(slug, nom)
        if info is not None and info.etat == EN_ECHEC:
            texte = f"L'application est en échec : {info.raison}. Relancez-la depuis l'Atelier."
            return Response(_page("Application en échec", texte), 502, media_type="text/html; charset=utf-8")
        try:
            await service.demarrer(slug, nom, attendre=False)
        except (ErreurApplication, ManifesteInvalide, ApplicationInconnue) as exc:
            return Response(_page("Démarrage impossible", str(exc)), 503, media_type="text/html; charset=utf-8")
        entetes = {"Retry-After": "2", "Cache-Control": "no-store"}
        if _navigation(request):
            return Response(
                _page("Démarrage…", f"{slug}/{nom} démarre ; cette page se recharge d'elle-même.", rafraichir=2),
                503,
                headers=entetes,
                media_type="text/html; charset=utf-8",
            )
        return JSONResponse({"detail": "application en démarrage"}, status_code=503, headers=entetes)

    async def relayer_http(request: Request, slug: str, nom: str, manifeste: Manifeste, cible: Any) -> Response:
        prefixe = f"/{slug}/{nom}"
        chemin = request.url.path
        if manifeste.chemin == "retire":
            chemin = chemin[len(prefixe):] or "/"
        amont = f"http://127.0.0.1:{cible.port}" if cible.port else "http://localhost"
        url = amont + quote(chemin, safe="/%:@!$&'()*+,;=~-._") + (f"?{request.url.query}" if request.url.query else "")
        sse = "sse" in manifeste.protocoles
        if not sse and "text/event-stream" in (request.headers.get("accept") or ""):
            return JSONResponse({"detail": "flux SSE non déclaré par l'application"}, status_code=406)
        entetes = px.entetes_vers_amont(
            [(k.decode("latin-1"), v.decode("latin-1")) for k, v in request.scope["headers"]],
            prefixe=prefixe,
            hote_public=service.hote,
            client_ip=(request.client.host if request.client else ""),
        )
        plafond = manifeste.corps_max_mo * 2**20
        annonce = request.headers.get("content-length")
        if annonce and annonce.isdigit() and int(annonce) > plafond:
            return JSONResponse({"detail": f"corps trop gros (plafond {manifeste.corps_max_mo} Mo)"}, status_code=413)
        a_un_corps = bool(annonce and annonce != "0") or "transfer-encoding" in request.headers
        contenu = px.corps_borne(request.stream(), plafond) if a_un_corps else None

        client = client_pour(str(cible.socket) if cible.socket else None)
        service.superviseur.ouvrir_connexion(slug, nom)
        ferme = False

        def fermer() -> None:
            nonlocal ferme
            if not ferme:
                ferme = True
                service.superviseur.fermer_connexion(slug, nom)

        try:
            requete = client.build_request(request.method, url, headers=entetes, content=contenu)
            reponse = await client.send(requete, stream=True)
        except px.CorpsTropGros:
            fermer()
            return JSONResponse({"detail": f"corps trop gros (plafond {manifeste.corps_max_mo} Mo)"}, status_code=413)
        except httpx.HTTPError as exc:
            fermer()
            if isinstance(exc.__cause__, px.CorpsTropGros) or "CorpsTropGros" in repr(exc):
                return JSONResponse({"detail": f"corps trop gros (plafond {manifeste.corps_max_mo} Mo)"}, status_code=413)
            log.info("amont %s injoignable : %s", prefixe, exc)
            return Response(_page("Application injoignable", f"{slug}/{nom} ne répond pas."), 502, media_type="text/html; charset=utf-8")
        except BaseException:
            fermer()
            raise

        async def flux() -> Any:
            try:
                async for morceau in reponse.aiter_raw():
                    yield morceau
            finally:
                await reponse.aclose()
                fermer()

        sortie = StreamingResponse(flux(), status_code=reponse.status_code)
        sortie.raw_headers = px.entetes_vers_client(
            list(reponse.headers.multi_items()),
            prefixe=prefixe,
            chemin_retire=manifeste.chemin == "retire",
            amont=amont,
            origine_apps=service.origine,
            origine_atelier=origine_atelier(),
        )
        return sortie

    async def application_ws(websocket: WebSocket) -> None:
        slug = websocket.path_params["slug"]
        nom = websocket.path_params["nom"]
        origine = (websocket.headers.get("origin") or "").rstrip("/").lower()
        if not origine or origine != service.origine:
            await websocket.close(code=px.FERME_ORIGINE_REFUSEE)
            return
        if not nom_valide(nom) or not art.slug_valide(slug) or not session_couvre(websocket, slug):
            await websocket.close(code=px.FERME_NON_AUTHENTIFIE)
            return
        try:
            manifeste = service.superviseur.manifeste(slug, nom) or service.manifeste(slug, nom)
        except (ApplicationInconnue, ManifesteInvalide):
            await websocket.close(code=px.FERME_NON_DECLARE)
            return
        if manifeste is None or not manifeste.service or "ws" not in manifeste.protocoles:
            await websocket.close(code=px.FERME_NON_DECLARE)
            return
        cible = service.superviseur.cible(slug, nom)
        if cible is None:
            info = service.superviseur.etat(slug, nom)
            if info is None or info.etat != EN_ECHEC:
                try:
                    await service.demarrer(slug, nom, attendre=False)
                except Exception:  # noqa: BLE001
                    pass
            await websocket.close(code=px.FERME_PAS_PRETE)
            return
        prefixe = f"/{slug}/{nom}"
        chemin = websocket.url.path
        if manifeste.chemin == "retire":
            chemin = chemin[len(prefixe):] or "/"
        requete = f"?{websocket.url.query}" if websocket.url.query else ""
        hote = f"127.0.0.1:{cible.port}" if cible.port else "localhost"
        url = f"ws://{hote}{quote(chemin, safe='/%:@!$&()*+,;=~-._')}{requete}"
        entetes = px.entetes_vers_amont(
            [(k.decode("latin-1"), v.decode("latin-1")) for k, v in websocket.scope["headers"]],
            prefixe=prefixe,
            hote_public=service.hote,
            client_ip=(websocket.client.host if websocket.client else ""),
            websocket=True,
        )
        await relayer(
            websocket,
            url,
            entetes=entetes,
            journal=f"ws {prefixe}",
            taille_max=px.WS_TAILLE_MAX,
            ping_s=px.WS_PING_S,
            unix_socket=str(cible.socket) if cible.socket else None,
            connexion=service.superviseur.connexion(slug, nom),
        )

    async def fermer_clients() -> None:
        for c in clients.values():
            await c.aclose()
        clients.clear()

    toutes = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    routes = [
        Route("/_sante", sante, methods=["GET", "HEAD"]),
        Route("/_atelier/entree", entree, methods=["GET"]),
        Route("/{slug}", projet_seul, methods=["GET", "HEAD"]),
        Route("/{slug}/{reste:path}", projet, methods=toutes),
        WebSocketRoute("/{slug}/{nom}/{reste:path}", application_ws),
        WebSocketRoute("/{slug}/{nom}", application_ws),
    ]
    app = Starlette(routes=routes)
    app.state.service = service
    app.state.fermer_clients = fermer_clients
    garde = GardeDeLHote(CadrageDesReponses(app, origine_atelier), lambda: service.hote)
    garde.interne = app  # type: ignore[attr-defined]
    return garde


__all__ = ["construire_app_apps", "GardeDeLHote"]
