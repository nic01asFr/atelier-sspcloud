"""API HTTP/SSE Atelier — façade sans logique métier."""

from __future__ import annotations

import re
import unicodedata
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from mcp_gateway.atelier import __version__
from mcp_gateway.atelier.auth import OwnerAuth, bearer_from_header
from mcp_gateway.atelier.config import AtelierSettings, get_settings
from mcp_gateway.atelier.events import AtelierEvent
from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
from mcp_gateway.atelier.gateway_overview import build_mcp_overview
from mcp_gateway.atelier.gateway_runtime import gateway_shutdown, gateway_startup
from mcp_gateway.atelier.harness import ClaudeHarness, FakeHarness, Harness
from mcp_gateway.atelier.mcp_registry import mask_server_entry
from mcp_gateway.atelier.mcp_sync import sync_summary
from mcp_gateway.atelier.projects import ProjectStore
from mcp_gateway.atelier.sessions import SessionStore
from mcp_gateway.atelier.ui_settings import (
    load_ui_settings,
    resolve_vscode_url,
    save_ui_settings,
)
from mcp_gateway.atelier.vscode_bridge import (
    COOKIE_NAME,
    folder_abs,
    load_vscode_password,
    save_vscode_password,
)
from mcp_gateway.atelier.vscode_handoff import prepare_vscode_handoff
from mcp_gateway.atelier.vscode_proxy import (
    is_internal_request,
    register_vscode_proxy,
    resolve_vscode_password,
    VscodeUpstream,
)
from mcp_gateway.atelier.wikichat_pilote_proxy import proxy_wikichat_pilote

WEB_DIR = Path(__file__).resolve().parent / "web"


class CreateSessionBody(BaseModel):
    slug: str | None = None
    model: str | None = None
    title: str | None = None
    kind: str | None = None


class PatchSessionBody(BaseModel):
    title: str | None = None
    archived: bool | None = None


class PatchSessionMcpBody(BaseModel):
    overlay: dict[str, bool] = Field(default_factory=dict)


class CreateProjectBody(BaseModel):
    slug: str = Field(min_length=1)
    kind: str | None = None
    title: str | None = None


class PatchProjectBody(BaseModel):
    title: str | None = None
    archived: bool | None = None


class SendMessageBody(BaseModel):
    message: str = ""
    attachments: list[str] = Field(default_factory=list)


class McpServerBody(BaseModel):
    model_config = {"extra": "allow"}

    enabled: bool | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    type: str | None = None
    url: str | None = None
    headers: dict[str, str] | None = None


class McpEnableBody(BaseModel):
    enabled: bool


class McpImportBody(BaseModel):
    mcpServers: dict[str, Any]
    replace: bool = False
    default_enabled: bool = True


class ProfileActivateBody(BaseModel):
    kind: str
    id: str


class CustomProfileBody(BaseModel):
    id: str = ""
    name: str = ""
    description: str = ""
    org_servers: list[str] = Field(default_factory=list)
    registry_servers: list[str] = Field(default_factory=list)
    tool_allowlist: list[str] | None = None
    meta_tools: list[str] | None = None


class ToolVariantBody(BaseModel):
    """Variante d'outil : le même outil, avec des paramètres déjà remplis."""

    tool: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class AgentCreateBody(BaseModel):
    id: str = ""
    name: str
    desc: str = ""
    dir: str = ""
    freq: str = "0 8 * * *"
    model: str = ""
    mission: str = ""
    tools: list[str] = Field(default_factory=list)
    profile_kind: str = ""
    profile_id: str = ""


class AgentDecideBody(BaseModel):
    actionId: str
    decision: str = "approve"
    resolved: dict[str, Any] | None = None


class AgentDaemonBody(BaseModel):
    paused: bool


class MetaPatchBody(BaseModel):
    vscode_url: str | None = None
    # write-only : stocké dans .secrets/vscode_password, jamais renvoyé
    vscode_password: str | None = None


def build_app(
    *,
    settings: AtelierSettings | None = None,
    harness: Harness | None = None,
    use_fake: bool = False,
) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()
    if harness is None:
        harness = FakeHarness() if use_fake else ClaudeHarness(settings)
    store = SessionStore(settings, harness)
    projects = ProjectStore(settings)
    auth = OwnerAuth(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not use_fake:
            await gateway_startup(app, settings)
        yield
        if not use_fake and hasattr(app.state, "pool"):
            await gateway_shutdown(app)

    app = FastAPI(title="Atelier", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.state.projects = projects
    app.state.auth = auth
    app.state.harness = harness
    app.state.use_fake = use_fake

    def _mcp_store() -> IntegratedMcpStore:
        if app.state.use_fake:
            raise HTTPException(503, "gateway not available in fake harness mode")
        return IntegratedMcpStore(app.state.db)

    internal = (settings.vscode_internal_url or "").strip() or "http://127.0.0.1:8080"
    pw = resolve_vscode_password(settings) or ""
    auth_mode = (settings.vscode_upstream_auth or "atelier").strip().lower()
    app.state.vscode_upstream = VscodeUpstream(internal, pw, auth_mode=auth_mode)

    def _sync() -> dict[str, Any]:
        return sync_summary(settings)

    router = APIRouter(prefix="/v1")

    def require_owner(authorization: Annotated[str | None, Header()] = None) -> str:
        return auth.require(authorization)

    def require_owner_nav(request: Request, authorization: Annotated[str | None, Header()] = None) -> str:
        """Bearer ou cookie HttpOnly (navigation /v1/vscode/open)."""
        token = bearer_from_header(authorization) or request.cookies.get(COOKIE_NAME)
        return auth.check_token(token)

    def _meta_payload() -> dict[str, Any]:
        from mcp_gateway.atelier.vscode_bridge import bridge_status

        vs = resolve_vscode_url(settings)
        st = bridge_status(settings)
        return {
            "vscode_url": vs,
            "vscode_ready": st["ready"],
            "vscode_password_configured": st["password_configured"],
            "default_slug": settings.default_slug,
            "assistant_slug": settings.assistant_slug,
            "projects_root": str(settings.projects_dir),
            "ui": load_ui_settings(settings),
            "models": _models_payload(),
        }

    def _models_payload() -> dict[str, Any]:
        from mcp_gateway.atelier.models_catalog import list_available_models

        return list_available_models(settings)

    @router.get("/models")
    def list_models(_owner: str = Depends(require_owner)) -> dict[str, Any]:
        return _models_payload()

    @router.put("/internal/vscode-password")
    def register_vscode_password_internal(
        request: Request,
        password: Annotated[str, Header(alias="X-Code-Server-Password")] = "",
    ) -> dict[str, str]:
        """Pod VS Code → Atelier (réseau cluster) : enregistre $PASSWORD sans action utilisateur."""
        if not is_internal_request(request):
            raise HTTPException(403, "cluster only")
        pw = password.strip()
        if not pw:
            raise HTTPException(400, "X-Code-Server-Password required")
        save_vscode_password(settings, pw)
        app.state.vscode_upstream.reset(pw)
        return {"status": "ok"}

    @app.get("/health")
    def health() -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": "ok",
            "service": "atelier",
            "version": __version__,
            "harness": type(harness).__name__,
            "gateway_integrated": not use_fake,
        }
        if not use_fake and hasattr(app.state, "upstream_status"):
            payload["gateway_pool"] = app.state.upstream_status
            payload["gateway_db"] = str(settings.gateway_db_path)
        return payload

    @router.get("/health")
    def health_v1() -> dict[str, Any]:
        """Alias sous /v1 pour les recettes / clients."""
        return health()

    @router.post("/auth/cookie")
    def set_auth_cookie(
        response: Response,
        _owner: str = Depends(require_owner),
    ) -> dict[str, str]:
        """Pose le cookie de navigation pour les liens VS Code (même onglet / nouvel onglet)."""
        response.set_cookie(
            key=COOKIE_NAME,
            value=auth.owner_key,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 30,
            path="/",
        )
        return {"status": "ok"}

    @router.get("/meta")
    def meta(_owner: str = Depends(require_owner)) -> dict[str, Any]:
        """Infos compte pour le hub (liens faces, chemins)."""
        return _meta_payload()

    @router.put("/meta")
    def put_meta(
        body: MetaPatchBody,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        """Persiste l’URL VS Code (+ mdp code-server write-only) sur le PVC."""
        patch: dict[str, Any] = {}
        if body.vscode_url is not None:
            patch["vscode_url"] = body.vscode_url.strip().rstrip("/")
        if patch:
            save_ui_settings(settings, patch)
        if body.vscode_password is not None:
            save_vscode_password(settings, body.vscode_password)
        return _meta_payload()

    @router.get("/projects")
    def list_projects(
        kind: str | None = None,
        include_archived: bool = False,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        items = projects.list_projects(include_archived=include_archived)
        if kind in ("assistant", "code"):
            items = [p for p in items if p.kind == kind]
        return {"projects": [p.to_dict() for p in items]}

    @router.post("/projects")
    def create_project(
        body: CreateProjectBody,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        kind = body.kind if body.kind in ("assistant", "code") else None
        try:
            rec = projects.create(body.slug, kind=kind, title=body.title)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return rec.to_dict()

    @router.patch("/projects/{slug}")
    def patch_project(
        slug: str,
        body: PatchProjectBody,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        try:
            rec = projects.patch(slug, title=body.title, archived=body.archived)
        except KeyError:
            raise HTTPException(404, "project not found") from None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return rec.to_dict()

    @router.delete("/projects/{slug}")
    def delete_project(
        slug: str,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        # Un projet ne disparait que s'il ne reste rien : ni conversation,
        # ni fichier. Sinon on invite a l'archiver.
        liees = store.list_sessions(slug, include_archived=True)
        if liees:
            raise HTTPException(
                409,
                f"{len(liees)} conversation(s) rattachée(s) — archivez le projet",
            )
        try:
            projects.delete(slug)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"deleted": slug}

    @router.get("/vscode/open")
    async def vscode_open(
        session: str | None = None,
        slug: str | None = None,
        _owner: str = Depends(require_owner_nav),
    ) -> Response:
        """Handoff hub → face VS Code intégrée (/vscode proxy, auth Atelier)."""
        slug_v = (slug or settings.default_slug).strip() or settings.default_slug
        if session:
            try:
                prepare_vscode_handoff(settings, slug_v, session)
            except OSError:
                pass
        from urllib.parse import quote

        folder = quote(folder_abs(settings, slug_v), safe="")
        q = f"folder={folder}"
        if session:
            q += f"&atelier_session={quote(session, safe='')}"
        return RedirectResponse(url=f"/vscode/?{q}", status_code=302)

    @router.post("/sessions")
    def create_session(
        body: CreateSessionBody,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        kind = body.kind if body.kind in ("assistant", "code") else None
        rec = store.create(
            slug=body.slug,
            model=body.model,
            title=body.title,
            kind=kind,
        )
        return rec.to_dict()

    @router.get("/sessions")
    def list_sessions(
        slug: str | None = None,
        kind: str | None = None,
        include_archived: bool = False,
        sync_titles: bool = True,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        if sync_titles:
            try:
                store.sync_claude_titles()
            except OSError:
                pass
        sessions = store.list_sessions(slug, include_archived=include_archived)
        if kind in ("assistant", "code"):
            sessions = [s for s in sessions if s.kind == kind]
        return {"sessions": [s.to_dict() for s in sessions]}

    @router.post("/sessions/sync-titles")
    def sync_session_titles(_owner: str = Depends(require_owner)) -> dict[str, Any]:
        try:
            return store.sync_claude_titles()
        except OSError as exc:
            raise HTTPException(500, str(exc)) from exc

    @router.get("/sessions/{session_id}")
    def get_session(
        session_id: str,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        rec = store.get(session_id)
        if not rec:
            raise HTTPException(404, "session not found")
        return rec.to_dict()

    @router.patch("/sessions/{session_id}")
    def patch_session(
        session_id: str,
        body: PatchSessionBody,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        try:
            rec = store.patch(
                session_id,
                title=body.title,
                archived=body.archived,
            )
        except KeyError:
            raise HTTPException(404, "session not found") from None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return rec.to_dict()

    @router.get("/sessions/{session_id}/mcp")
    def get_session_mcp(
        session_id: str,
        request: Request,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        rec = store.get(session_id)
        if not rec:
            raise HTTPException(404, "session not found")
        upstream = getattr(request.app.state, "upstream_status", {}) or {}
        return store.get_mcp_state(rec, upstream)

    @router.patch("/sessions/{session_id}/mcp")
    def patch_session_mcp(
        session_id: str,
        body: PatchSessionMcpBody,
        request: Request,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        try:
            rec = store.patch_mcp_overlay(session_id, body.overlay)
        except KeyError:
            raise HTTPException(404, "session not found") from None
        upstream = getattr(request.app.state, "upstream_status", {}) or {}
        return store.get_mcp_state(rec, upstream)

    @router.delete("/sessions/{session_id}")
    def delete_session(
        session_id: str,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        try:
            store.delete(session_id)
        except KeyError:
            raise HTTPException(404, "session not found") from None
        return {"deleted": session_id}

    @router.post("/sessions/{session_id}/messages")
    def send_message(
        session_id: str,
        body: SendMessageBody,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        if not store.get(session_id):
            raise HTTPException(404, "session not found")
        if not body.message.strip() and not body.attachments:
            raise HTTPException(400, "message or attachments required")
        try:
            result = store.send(session_id, body.message, attachment_ids=body.attachments)
        except KeyError:
            raise HTTPException(404, "session not found") from None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, str(exc)) from exc
        return {
            "session_id": session_id,
            "exit_code": result.exit_code,
            "text": result.text,
            "events": [
                {
                    "kind": e.kind,
                    "text": e.text,
                    "tool": e.tool,
                    "cause": e.cause,
                    "raw_type": e.raw_type,
                    "tool_id": e.tool_id,
                }
                for e in result.events
            ],
            "log_path": result.log_path,
            "transcript_path": result.transcript_path,
            "session": store.get(session_id).to_dict() if store.get(session_id) else None,
        }

    @router.post("/sessions/{session_id}/attachments")
    async def upload_session_attachment(
        session_id: str,
        file: UploadFile = File(...),
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        rec = store.get(session_id)
        if not rec:
            raise HTTPException(404, "session not found")
        if rec.kind == "assistant":
            from mcp_gateway.atelier.sessions import _normalize_assistant_cwd

            _normalize_assistant_cwd(settings, rec)
            store.save(rec)
        from mcp_gateway.atelier.session_attachments import save_upload

        data = await file.read()
        try:
            meta = save_upload(
                Path(rec.cwd),
                file.filename or "file",
                data,
                mime=file.content_type or "",
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return meta.to_dict()

    @router.delete("/sessions/{session_id}/attachments/{attachment_id}")
    def delete_session_attachment(
        session_id: str,
        attachment_id: str,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        rec = store.get(session_id)
        if not rec:
            raise HTTPException(404, "session not found")
        from mcp_gateway.atelier.session_attachments import delete_attachment

        ok = delete_attachment(Path(rec.cwd), attachment_id)
        if not ok:
            raise HTTPException(404, "attachment not found")
        return {"deleted": attachment_id}

    @router.get("/sessions/{session_id}/events")
    def stream_events(
        session_id: str,
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        message: str | None = None,
        attachments: str | None = None,
    ) -> StreamingResponse:
        """SSE : envoie un message (query ?message=) puis streame les événements du tour."""
        token = bearer_from_header(authorization) or request.query_params.get("token")
        auth.check_token(token)

        if not store.get(session_id):
            raise HTTPException(404, "session not found")
        if not message and not attachment_ids:
            raise HTTPException(400, "message or attachments required")

        attachment_ids = [
            x.strip() for x in (attachments or "").split(",") if x.strip()
        ]

        def gen():
            try:
                result = store.send(session_id, message, attachment_ids=attachment_ids)
            except Exception as exc:  # noqa: BLE001
                ev = AtelierEvent(kind="erreur", session_id=session_id, cause=str(exc))
                yield ev.as_sse()
                return
            for ev in result.events:
                yield ev.as_sse()

        return StreamingResponse(gen(), media_type="text/event-stream")

    @router.post("/sessions/{session_id}/interrupt")
    def interrupt(
        session_id: str,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        try:
            rec = store.interrupt(session_id)
        except KeyError:
            raise HTTPException(404, "session not found") from None
        return rec.to_dict()

    @router.get("/sessions/{session_id}/transcript")
    def transcript(
        session_id: str,
        _owner: str = Depends(require_owner),
    ) -> JSONResponse:
        try:
            text = store.transcript_text(session_id)
        except KeyError:
            raise HTTPException(404, "session not found") from None
        return JSONResponse({"session_id": session_id, "transcript": text})

    @router.get("/mcp/servers")
    def mcp_list_servers(_owner: str = Depends(require_owner)) -> dict[str, Any]:
        return {"servers": _mcp_store().list_servers(mask=True)}

    @router.get("/mcp/pool/status")
    def mcp_pool_status(_owner: str = Depends(require_owner)) -> dict[str, Any]:
        if hasattr(app.state, "pool"):
            return {"status": app.state.pool.status(), "upstream": app.state.upstream_status}
        return {"status": {}, "upstream": {}}

    @router.get("/mcp/tools")
    def mcp_tools(request: Request, _owner: str = Depends(require_owner)) -> dict[str, Any]:
        """Outils de chaque service, pour choisir plus fin qu'un service entier."""
        from mcp_gateway.atelier.gateway_tools import build_tools_by_service

        return build_tools_by_service(request)

    @router.post("/mcp/servers/{name}/probe")
    async def mcp_probe_server(
        name: str,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        """
        Sonde un serveur lancé en local pour connaître ses outils.

        Le pool ne connecte pas les serveurs stdio : leurs outils resteraient
        inconnus, et on ne pourrait proposer que le service entier. On lance
        donc le serveur le temps d'un `tools/list`, on met en cache, on ferme.
        """
        if app.state.use_fake or not hasattr(app.state, "db"):
            raise HTTPException(503, "gateway not available")
        from mcp_gateway.atelier.stdio_probe import (
            commande_depuis_config,
            probe_stdio_tools,
        )
        from mcp_gateway.registry import list_registry_servers
        from mcp_gateway.tool_cache import save_upstream_tools

        entree = next(
            (e for e in list_registry_servers(app.state.db) if e.server_id == name),
            None,
        )
        if entree is None:
            raise HTTPException(404, "connecteur inconnu")
        commande, args, env = commande_depuis_config(entree.config)
        if not commande:
            raise HTTPException(
                400, "ce connecteur n'est pas lancé en local : rien à sonder"
            )
        try:
            outils = await probe_stdio_tools(commande, args, env)
        except RuntimeError as exc:
            raise HTTPException(502, f"sondage impossible : {exc}") from exc
        save_upstream_tools(app.state.db, f"registry:{name}", name, outils)
        return {"server": name, "tools": len(outils)}

    @router.get("/mcp/tools/schema")
    def mcp_tool_schema(
        request: Request,
        tool: str,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        from mcp_gateway.atelier.gateway_tools import tool_schema

        data = tool_schema(request, tool)
        if not data:
            raise HTTPException(404, "outil inconnu du pool")
        return data

    @router.post("/mcp/tool-variants")
    def mcp_create_tool_variant(
        request: Request,
        body: ToolVariantBody,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        """
        Enregistre une variante d'outil aux paramètres figés.

        La passerelle représente déjà cela comme une composition à une seule
        étape : on réutilise ce mécanisme plutôt que d'en créer un second.
        """
        svc = getattr(request.app.state, "compositions", None)
        if svc is None:
            raise HTTPException(503, "compositions indisponibles")
        # L'identifiant d'une composition est alphanumérique ; le nom saisi
        # reste le libellé lisible de l'étape.
        slug = re.sub(r"[^a-z0-9]+", "_", unicodedata.normalize("NFD", body.name)
                      .encode("ascii", "ignore").decode("ascii").lower()).strip("_")
        if not slug:
            slug = re.sub(r"[^a-z0-9]+", "_", body.tool.split("__")[-1].lower()).strip("_")
        try:
            cree = svc.create_from_steps(
                nom=slug,
                description=body.description or body.name,
                etapes=[
                    {
                        "tool": body.tool,
                        "label": body.name,
                        "parameters": body.parameters,
                    }
                ],
            )
            # Créer ne suffit pas : une variante reste inerte tant qu'elle
            # n'est pas validée puis promue, comme le fait la passerelle.
            comp_id = cree.get("id")
            verdict = svc.validate(comp_id)
            if not verdict.get("ok", False):
                raise HTTPException(
                    400,
                    "paramètres refusés : " + str(verdict.get("errors") or verdict),
                )
            promu = svc.promote(comp_id)
            return {"id": comp_id, "composition": promu, "validation": verdict}
        except HTTPException:
            raise
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/mcp/overview")
    def mcp_overview(request: Request, _owner: str = Depends(require_owner)) -> dict[str, Any]:
        if app.state.use_fake:
            raise HTTPException(503, "gateway not available in fake harness mode")
        return build_mcp_overview(request)

    @router.post("/mcp/reprobe")
    async def mcp_reprobe(_owner: str = Depends(require_owner)) -> dict[str, Any]:
        if app.state.use_fake or not hasattr(app.state, "pool"):
            raise HTTPException(503, "gateway not available")
        app.state.upstream_status = await app.state.pool.startup()

        # Le pool ne connecte pas les serveurs lancés en local : sans ce
        # passage, leurs outils resteraient inconnus et on ne pourrait
        # proposer que le service entier.
        sondes: dict[str, Any] = {}
        if hasattr(app.state, "db"):
            from mcp_gateway.atelier.stdio_probe import (
                commande_depuis_config,
                probe_stdio_tools,
            )
            from mcp_gateway.registry import list_registry_servers
            from mcp_gateway.tool_cache import save_upstream_tools

            for entree in list_registry_servers(app.state.db):
                commande, args, env = commande_depuis_config(entree.config)
                if not commande:
                    continue
                try:
                    outils = await probe_stdio_tools(commande, args, env)
                except RuntimeError as exc:
                    sondes[entree.server_id] = f"erreur : {exc}"
                    continue
                save_upstream_tools(
                    app.state.db, f"registry:{entree.server_id}", entree.server_id, outils
                )
                sondes[entree.server_id] = len(outils)

        return {"upstream": app.state.upstream_status, "sondes": sondes}

    @router.put("/mcp/servers/{name}")
    def mcp_upsert_server(
        name: str,
        body: McpServerBody,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        raw = body.model_dump(exclude_none=True)
        try:
            entry = _mcp_store().upsert(name, raw)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        summary = _sync()
        return {"name": name, "server": mask_server_entry(entry), "sync": summary}

    @router.patch("/mcp/servers/{name}")
    def mcp_patch_server(
        name: str,
        body: McpEnableBody,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        try:
            _mcp_store().set_enabled(name, body.enabled)
        except KeyError:
            raise HTTPException(404, "server not found") from None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {
            "name": name,
            "server": _mcp_store().list_servers(mask=True)[name],
            "sync": _sync(),
        }

    @router.delete("/mcp/servers/{name}")
    def mcp_delete_server(
        name: str,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        try:
            _mcp_store().delete(name)
        except KeyError:
            raise HTTPException(404, "server not found") from None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"deleted": name, "sync": _sync()}

    @router.post("/mcp/import")
    def mcp_import(
        body: McpImportBody,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        try:
            imported = _mcp_store().import_mcp_servers(
                body.mcpServers,
                default_enabled=body.default_enabled,
                replace=body.replace,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"imported": imported, "sync": _sync()}

    @router.post("/mcp/sync")
    def mcp_sync(_owner: str = Depends(require_owner)) -> dict[str, Any]:
        return _sync()

    @router.get("/mcp/profiles")
    def mcp_profiles(
        request: Request,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        if app.state.use_fake:
            raise HTTPException(503, "gateway not available in fake harness mode")
        from mcp_gateway.profiles import profiles_payload

        return profiles_payload(request.app.state.db, request.app.state.catalog, request.app.state.bundles)

    @router.post("/mcp/profiles/activate")
    def mcp_activate_profile(
        body: ProfileActivateBody,
        request: Request,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        if app.state.use_fake:
            raise HTTPException(503, "gateway not available in fake harness mode")
        from mcp_gateway.db import log_audit
        from mcp_gateway.mcp.tools_registry import bump_tools_revision
        from mcp_gateway.profiles import activate_custom_profile, activate_org_profile

        conn = request.app.state.db
        catalog = request.app.state.catalog
        bundles = request.app.state.bundles
        try:
            if body.kind == "org":
                profile = activate_org_profile(conn, bundles, catalog, body.id)
            elif body.kind == "custom":
                profile = activate_custom_profile(conn, catalog, body.id)
            else:
                raise ValueError(f"kind invalide : {body.kind}")
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        log_audit(conn, "profile.activate", {"kind": body.kind, "id": body.id})
        return {
            "active_profile": {
                "kind": profile.kind,
                "id": profile.id,
                "label": profile.label,
            },
            "active_bundle": profile.bundle_id or profile.id,
            "tools_revision": bump_tools_revision(request.app),
        }

    @router.post("/mcp/profiles/custom")
    def mcp_create_profile(
        body: CustomProfileBody,
        request: Request,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        if app.state.use_fake:
            raise HTTPException(503, "gateway not available in fake harness mode")
        from mcp_gateway.db import log_audit
        from mcp_gateway.profiles import create_custom_profile, profiles_payload

        conn = request.app.state.db
        catalog = request.app.state.catalog
        if not body.name.strip():
            raise HTTPException(400, "Nom requis")
        try:
            create_custom_profile(
                conn,
                catalog,
                profile_id=body.id or None,
                name=body.name,
                description=body.description,
                org_servers=body.org_servers,
                registry_servers=body.registry_servers,
                tool_allowlist=body.tool_allowlist,
                meta_tools=body.meta_tools,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        log_audit(conn, "profile.create", {"id": body.id or body.name})
        return profiles_payload(conn, catalog, request.app.state.bundles)

    @router.put("/mcp/profiles/custom/{profile_id}")
    def mcp_update_profile(
        profile_id: str,
        body: CustomProfileBody,
        request: Request,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        if app.state.use_fake:
            raise HTTPException(503, "gateway not available in fake harness mode")
        from mcp_gateway.db import log_audit
        from mcp_gateway.profiles import profiles_payload, update_custom_profile

        conn = request.app.state.db
        catalog = request.app.state.catalog
        try:
            update_custom_profile(
                conn,
                catalog,
                profile_id,
                name=body.name or None,
                description=body.description,
                org_servers=body.org_servers,
                registry_servers=body.registry_servers,
                tool_allowlist=body.tool_allowlist,
                meta_tools=body.meta_tools,
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        log_audit(conn, "profile.update", {"id": profile_id})
        return profiles_payload(conn, catalog, request.app.state.bundles)

    @router.delete("/mcp/profiles/custom/{profile_id}")
    def mcp_delete_profile(
        profile_id: str,
        request: Request,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        if app.state.use_fake:
            raise HTTPException(503, "gateway not available in fake harness mode")
        from mcp_gateway.db import log_audit
        from mcp_gateway.profiles import delete_custom_profile, profiles_payload

        conn = request.app.state.db
        catalog = request.app.state.catalog
        if not delete_custom_profile(conn, profile_id):
            raise HTTPException(404, "Ce profil n'existe pas.")
        log_audit(conn, "profile.delete", {"id": profile_id})
        return profiles_payload(conn, catalog, request.app.state.bundles)

    @router.get("/mcp/profiles/{kind}/{profile_id}/pilote-bindings")
    def mcp_profile_pilote_bindings(
        kind: str,
        profile_id: str,
        request: Request,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        """Bindings pour le pilote Wikichat (outils coarse + consignes) — pas une UI dupliquée."""
        if app.state.use_fake:
            raise HTTPException(503, "gateway not available in fake harness mode")
        from mcp_gateway.profiles import get_custom_profile, org_profile_from_bundle

        conn = request.app.state.db
        catalog = request.app.state.catalog
        if kind == "org":
            if profile_id not in catalog.bundles:
                raise HTTPException(404, "profil org inconnu")
            profile = org_profile_from_bundle(conn, catalog, profile_id)
        elif kind == "custom":
            profile = get_custom_profile(conn, catalog, profile_id)
            if not profile:
                raise HTTPException(404, "profil perso introuvable")
        else:
            raise HTTPException(400, "kind invalide")
        tools: list[str] = ["Bash", "Read"]
        for sid in profile.registry_server_ids:
            tools.append(f"registry:{sid}")
        for org_key in profile.org_servers:
            if org_key not in tools:
                tools.append(org_key)
        mission_prefix = (profile.description or "").strip()
        if profile.mcp_instructions:
            mission_prefix = (profile.mcp_instructions or "").strip()
        return {
            "kind": profile.kind,
            "id": profile.id,
            "label": profile.label,
            "tools": tools,
            "mission_prefix": mission_prefix,
        }

    @router.get("/agent/overview")
    async def agent_overview(_owner: str = Depends(require_owner)) -> dict[str, Any]:
        if app.state.use_fake:
            raise HTTPException(503, "wikichat pilote not available in fake harness mode")
        from mcp_gateway.atelier.pilote_overview import build_pilote_overview

        try:
            return await build_pilote_overview(settings)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(503, f"wikichat pilote: {exc}") from exc

    @router.post("/agent/daemon")
    async def agent_daemon(
        body: AgentDaemonBody,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        if app.state.use_fake:
            raise HTTPException(503, "wikichat pilote not available in fake harness mode")
        from mcp_gateway.atelier.pilote_client import pilote_post

        return await pilote_post(settings, "/pilote/api/daemon", {"paused": body.paused})

    @router.post("/agent")
    async def agent_create(
        body: AgentCreateBody,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        if app.state.use_fake:
            raise HTTPException(503, "wikichat pilote not available in fake harness mode")
        from mcp_gateway.atelier.pilote_client import pilote_post

        payload = body.model_dump(exclude_none=True)
        return await pilote_post(settings, "/pilote/api/agent", payload)

    @router.get("/agent/tools")
    async def agent_tools(_owner: str = Depends(require_owner)) -> dict[str, Any]:
        """Outils intégrés reconnus par le harness, pour la sélection d'un agent."""
        if app.state.use_fake:
            raise HTTPException(503, "wikichat pilote not available in fake harness mode")
        from mcp_gateway.atelier.pilote_client import pilote_get

        return await pilote_get(settings, "/pilote/api/tools")

    @router.get("/agent/{agent_id}/transcript")
    async def agent_transcript(
        agent_id: str,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        if app.state.use_fake:
            raise HTTPException(503, "wikichat pilote not available in fake harness mode")
        from mcp_gateway.atelier.pilote_client import pilote_get

        return await pilote_get(settings, f"/pilote/api/agent/{agent_id}/transcript")

    @router.post("/agent/{agent_id}/continue")
    async def agent_continue(
        agent_id: str,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        if app.state.use_fake:
            raise HTTPException(503, "wikichat pilote not available in fake harness mode")
        from mcp_gateway.atelier.pilote_client import pilote_post

        return await pilote_post(settings, f"/pilote/api/agent/{agent_id}/continue", {})

    @router.post("/agent/{agent_id}/fire")
    async def agent_fire(
        agent_id: str,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        if app.state.use_fake:
            raise HTTPException(503, "wikichat pilote not available in fake harness mode")
        from mcp_gateway.atelier.pilote_client import pilote_post

        return await pilote_post(settings, f"/pilote/api/agent/{agent_id}/fire", {})

    @router.post("/agent/{agent_id}/toggle")
    async def agent_toggle(
        agent_id: str,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        if app.state.use_fake:
            raise HTTPException(503, "wikichat pilote not available in fake harness mode")
        from mcp_gateway.atelier.pilote_client import pilote_post

        return await pilote_post(settings, f"/pilote/api/agent/{agent_id}/toggle", {})

    @router.post("/agent/{agent_id}/decide")
    async def agent_decide(
        agent_id: str,
        body: AgentDecideBody,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        if app.state.use_fake:
            raise HTTPException(503, "wikichat pilote not available in fake harness mode")
        from mcp_gateway.atelier.pilote_client import pilote_post

        payload = body.model_dump(exclude_none=True)
        return await pilote_post(settings, f"/pilote/api/agent/{agent_id}/decide", payload)

    @router.delete("/agent/{agent_id}")
    async def agent_delete(
        agent_id: str,
        _owner: str = Depends(require_owner),
    ) -> dict[str, Any]:
        if app.state.use_fake:
            raise HTTPException(503, "wikichat pilote not available in fake harness mode")
        from mcp_gateway.atelier.pilote_client import pilote_delete

        return await pilote_delete(settings, f"/pilote/api/agent/{agent_id}")

    app.include_router(router)

    register_vscode_proxy(app, settings, require_owner_nav)

    @app.get("/pilote")
    @app.api_route("/pilote/{rest:path}", methods=["GET", "POST", "DELETE"])
    async def wikichat_pilote_proxy(
        request: Request,
        rest: str = "",
        _owner: str = Depends(require_owner_nav),
    ) -> Response:
        """Pilote agents Wikichat — même chemins que :3777/pilote (owner cookie/bearer)."""
        if app.state.use_fake:
            raise HTTPException(503, "wikichat pilote not available in fake harness mode")
        return await proxy_wikichat_pilote(request, settings, subpath=rest)

    # UI P3 — après les routes API pour ne pas les masquer
    if WEB_DIR.is_dir():

        @app.get("/")
        def ui_index() -> FileResponse:
            return FileResponse(
                WEB_DIR / "index.html",
                media_type="text/html; charset=utf-8",
                headers={"Cache-Control": "no-store"},
            )

        css_dir = WEB_DIR / "css"
        js_dir = WEB_DIR / "js"
        if css_dir.is_dir():
            app.mount("/css", StaticFiles(directory=css_dir), name="atelier-css")
        if js_dir.is_dir():
            app.mount("/js", StaticFiles(directory=js_dir), name="atelier-js")

        @app.middleware("http")
        async def no_store_static_ui(request: Request, call_next):  # type: ignore[no-untyped-def]
            response = await call_next(request)
            path = request.url.path or ""
            if path.startswith("/js/") or path.startswith("/css/"):
                response.headers["Cache-Control"] = "no-store"
            return response

    return app
