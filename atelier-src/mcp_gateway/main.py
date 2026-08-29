from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from uuid import uuid4

from fastapi import FastAPI, Header, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from mcp_gateway import __version__
from mcp_gateway.api import router as api_router
from mcp_gateway.notifications import migrer_schema as migrer_notifications
from mcp_gateway.auth import (
    bearer_from_header,
    client_key,
    is_public_path,
    migrate_auth_schema,
    owner_key_file,
    resolve_owner_key,
    est_le_proprietaire,
    validate_credential,
    write_owner_key_file,
)
from mcp_gateway.bundles import BundleSession
from mcp_gateway.catalog import load_catalog, validate_catalog
from mcp_gateway.catalog_sync import catalog_sync_status
from mcp_gateway.config import Settings, settings
from mcp_gateway.compositions import CompositionService
from mcp_gateway.db import connect
from mcp_gateway.mcp import McpGateway
from mcp_gateway.profiles import WEB_UI_SESSION
from mcp_gateway.mcp.tools_registry import ToolsChangeTracker
from mcp_gateway.oauth import router as oauth_router
from mcp_gateway.upstream import UpstreamPool

WIDGET_DIR = Path(__file__).resolve().parent.parent.parent / "widget"

logger = logging.getLogger(__name__)


def _widget_dir(cfg: Settings) -> Path:
    """Racine du widget : réglage explicite, sinon voisine des sources."""
    return Path(cfg.widget_dir) if cfg.widget_dir else WIDGET_DIR


def _is_initialize(body: object) -> bool:
    """Vrai si la requête initialise la session — lot JSON-RPC compris."""
    if isinstance(body, dict):
        return body.get("method") == "initialize"
    if isinstance(body, list):
        return any(isinstance(m, dict) and m.get("method") == "initialize" for m in body)
    return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg: Settings = app.state.settings
    app.state.db = connect(cfg.db_path)
    migrate_auth_schema(app.state.db)
    migrer_notifications(app.state.db)
    app.state.owner_key = resolve_owner_key(app.state.db, cfg)
    if cfg.owner_lock:
        key_file = write_owner_key_file(cfg, app.state.owner_key)
        origine = "fournie par GATEWAY_OWNER_KEY" if cfg.owner_key else "générée automatiquement"
        logger.warning(
            "owner_lock actif — clé %s. Pour la retrouver depuis le pod : %s",
            origine,
            key_file or f"table gateway_meta de {cfg.db_path}",
        )
        if not cfg.owner_key:
            # La clé n'est plus écrite dans le journal. En pod, stdout part
            # dans `kubectl logs`, dans l'affichage de logs d'Onyxia et dans
            # toute collecte centralisée, avec sa rétention — pour un secret
            # que le fichier ci-dessus rend déjà accessible à qui a le pod.
            logger.warning(
                "Clé propriétaire générée au premier démarrage. "
                "Elle n'est pas journalisée : relisez-la dans %s",
                key_file or f"la table gateway_meta de {cfg.db_path}",
            )
    else:
        logger.warning(
            "owner_lock inactif — /mcp et /api/v1 sont ouverts. "
            "Positionner GATEWAY_OWNER_LOCK=1 avant toute exposition publique."
        )
    app.state.catalog = load_catalog(cfg.catalog_path)
    app.state.catalog_errors = validate_catalog(app.state.catalog)
    app.state.catalog_sync = catalog_sync_status(app)
    app.state.bundles = BundleSession(app.state.catalog)
    app.state.pool = UpstreamPool(app.state.catalog, app.state.db)
    mcp_holder: dict[str, McpGateway] = {}

    async def composition_tool_call(
        name: str, arguments: dict, session_id: str | None = None
    ) -> dict:
        """Une étape de composition passe le même garde que tout appel.

        Elle ne le passait pas : `internal=True` court-circuitait le contrôle de
        profil entièrement. Enregistrer une composition qui appelle
        `compute__exec` puis la lancer suffisait donc à sortir de son profil —
        deux appels, tous deux exposés par un preset d'usage courant.

        La composition s'exécute désormais sous le profil de qui la lance : sa
        session pour un client MCP, celle du widget pour le propriétaire.
        """
        if "mcp" in mcp_holder:
            return await mcp_holder["mcp"].tools_call(
                name, arguments, session_id or WEB_UI_SESSION, internal=False
            )
        return await app.state.pool.call(name, arguments)

    app.state.tools_change_tracker = ToolsChangeTracker()
    app.state.compositions = CompositionService(app.state.db, composition_tool_call)
    app.state.upstream_status = {"status": "probing"}
    app.state.mcp = McpGateway(
        app.state.catalog,
        app.state.bundles,
        app.state.pool,
        app.state.compositions,
        tools_change_tracker=app.state.tools_change_tracker,
    )
    mcp_holder["mcp"] = app.state.mcp
    app.state.compositions.bind_call_tool(composition_tool_call)

    async def _probe_upstreams() -> None:
        app.state.upstream_status = await app.state.pool.startup()

    asyncio.create_task(_probe_upstreams())
    yield
    await app.state.pool.shutdown()
    app.state.db.close()


def create_app(cfg: Settings | None = None) -> FastAPI:
    cfg = cfg or settings
    app = FastAPI(title="Cerema Gateway", version=__version__, lifespan=lifespan)
    app.state.settings = cfg

    @app.middleware("http")
    async def owner_lock_guard(request: Request, call_next):
        if not cfg.owner_lock or is_public_path(request.url.path):
            return await call_next(request)
        token = bearer_from_header(request.headers.get("Authorization"))
        conn = request.app.state.db
        cle = request.app.state.owner_key
        # L'administration reste au propriétaire. Un jeton OAuth n'ouvre que
        # /mcp : c'est le seul geste que ce flux prétend accorder, et c'est ce
        # que les métadonnées annoncent déjà. Sans cette distinction, le jeton
        # confié à un assistant distant lisait les identifiants de tous les
        # services amont et reconfigurait la passerelle.
        if request.url.path.startswith("/api/v1"):
            autorise = est_le_proprietaire(conn, token, cle)
        else:
            autorise = validate_credential(conn, token, cle)
        if autorise:
            return await call_next(request)
        # RFC 9728 : oriente le client MCP vers le serveur d'autorisation.
        base = (cfg.host_url or str(request.base_url)).rstrip("/")
        # Le chemin de la clé dépend du déploiement : seul le serveur le
        # connaît. Sans lui, l'écran de saisie réclame un secret sans dire
        # où le prendre. La clé elle-même n'est évidemment pas divulguée.
        return JSONResponse(
            {"error": "unauthorized", "key_file": str(owner_key_file(cfg))},
            status_code=401,
            headers={
                "WWW-Authenticate": (
                    'Bearer realm="passerelle", '
                    f'resource_metadata="{base}/.well-known/oauth-protected-resource"'
                )
            },
        )

    app.include_router(oauth_router)
    app.include_router(api_router)

    @app.get("/health")
    def root_health():
        return {"status": "ok", "version": __version__}

    @app.post("/mcp")
    async def mcp_post(
        request: Request,
        mcp_session_id: str | None = Header(default=None, alias="Mcp-Session-Id"),
    ):
        body = await request.json()

        # Le transport streamable HTTP veut que le serveur attribue l'identifiant
        # de session à l'initialisation ; le client le renvoie ensuite. Sans cela,
        # chaque requête ouvre une session neuve et gateway_use_bundle n'a aucun
        # effet durable — le profil retombe sur le défaut à l'appel suivant.
        assigned: str | None = None
        if not mcp_session_id and _is_initialize(body):
            assigned = uuid4().hex
            mcp_session_id = assigned

        if mcp_session_id:
            key = client_key(bearer_from_header(request.headers.get("Authorization")))
            app.state.bundles.bind_client(mcp_session_id, key)
            if assigned:
                # Un client qui renégocie sa session doit retrouver le profil
                # choisi, sans quoi il retombe sur le preset par défaut.
                app.state.bundles.restore_for_client(key, mcp_session_id)

        result = await app.state.mcp.handle_jsonrpc(body, mcp_session_id)
        headers = {"Mcp-Session-Id": assigned} if assigned else None
        return JSONResponse(content=result or {}, headers=headers)

    @app.delete("/mcp")
    async def mcp_delete(
        mcp_session_id: str | None = Header(default=None, alias="Mcp-Session-Id"),
    ):
        """Fin de session explicite : libère le bundle retenu pour cette session."""
        if not mcp_session_id:
            return JSONResponse(content={"error": "missing session"}, status_code=400)
        app.state.bundles.drop(mcp_session_id)
        return Response(status_code=204)

    widget_dir = _widget_dir(cfg)
    if widget_dir.is_dir():

        class RevalidatedStatic(StaticFiles):
            """Impose au navigateur de revérifier avant de réutiliser un fichier.

            Le widget est un ensemble de modules qui s'importent entre eux. Seul
            app.js porte un numéro de version dans son URL : sans revalidation,
            une mise à jour peut se charger avec d'anciens modules gardés en
            cache, et l'application casse sur un import devenu absent. L'ETag
            reste envoyé, donc un fichier inchangé coûte un 304, pas un
            téléchargement.
            """

            def file_response(self, *args, **kwargs):
                response = super().file_response(*args, **kwargs)
                response.headers["Cache-Control"] = "no-cache"
                # Un service worker ne contrôle par défaut que le dossier d'où
                # il est servi : depuis /widget/, il ne verrait pas la racine,
                # qui est justement l'adresse d'ouverture de l'application.
                # Cet en-tête est le seul moyen de lui étendre la portée.
                if str(args[0] if args else kwargs.get("full_path", "")).endswith("sw.js"):
                    response.headers["Service-Worker-Allowed"] = "/"
                return response

        app.mount("/widget", RevalidatedStatic(directory=str(widget_dir), html=True), name="widget")

    @app.get("/")
    def root():
        index = widget_dir / "index.html"
        if index.is_file():
            # Même raison : la page nomme les versions de ses ressources.
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return {"service": "passerelle", "mcp": "/mcp", "api": "/api/v1/health"}

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("mcp_gateway.main:app", host="0.0.0.0", port=8080, reload=False)
