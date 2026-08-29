from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from mcp_gateway import __version__
from mcp_gateway.compositions import CompositionService
from mcp_gateway.credentials import (
    credential_meta,
    delete_server_credentials,
    get_server_credentials_masked,
    resolve_server_url,
    set_server_credentials,
)
from mcp_gateway.registry import (
    config_sans_secrets,
    build_registry_config_from_simple,
    delete_registry_server,
    export_registry,
    get_registry_server,
    import_registry,
    list_registry_servers,
    normalize_server_config,
    parse_registry_import,
    registry_pool_key,
    update_registry_server_config,
    upsert_registry_server,
)
from mcp_gateway.server_enable import (
    SCOPE_ORG,
    SCOPE_REGISTRY,
    is_org_enabled,
    is_registry_enabled,
    set_enabled,
)
from mcp_gateway.tools_hub import (
    META_TOOL_CATALOG,
    list_pins,
    list_usage,
    set_pin,
    track_tool_use,
)
from mcp_gateway.profiles import (
    ResolvedProfile,
    activate_custom_profile,
    activate_org_profile,
    create_custom_profile,
    delete_custom_profile,
    profile_defaults,
    profiles_payload,
    resolve_web_profile,
    update_custom_profile,
)
from mcp_gateway.tools_exposure import (
    aggregate_personalizable_tools,
    aggregate_tools_for_profile,
    resolve_exposed_tools,
)
from mcp_gateway.catalog_sync import catalog_sync_status, reload_catalog, sync_catalog_from_gitlab
from mcp_gateway.mcp.tools_registry import bump_tools_revision
from mcp_gateway.upstream.pool import UpstreamPool

router = APIRouter(prefix="/api/v1")


class SidecarCreate(BaseModel):
    name: str
    mcp_url: str
    transport: str = "streamable-http"
    prefix: str | None = None


class CompositionCreate(BaseModel):
    name: str
    description: str = ""
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}
    steps: list[dict[str, Any]]


class CompositionExecute(BaseModel):
    inputs: dict[str, Any] = {}


class CompositionResume(BaseModel):
    response: Any = None


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict[str, Any] = {}


class ToolPinBody(BaseModel):
    tool_name: str


class ToolTrackBody(BaseModel):
    tool_name: str
    count: int = 1


PICKER_PROFILES = [
    {
        "id": "bundles",
        "label": "Profils",
        "tool": "gateway_list_bundles",
        "arguments": {},
        "live": True,
        "item_label": "label",
        "item_value": "id",
    },
    {
        "id": "compositions",
        "label": "Compositions",
        "tool": "gateway_list_compositions",
        "arguments": {},
        "live": True,
        "item_label": "name",
        "item_value": "id",
    },
    {
        "id": "catalog-servers",
        "label": "Services catalogue",
        "tool": "gateway_status",
        "arguments": {},
        "live": True,
        "item_label": "id",
        "item_value": "id",
        "items_from": "servers",
    },
]


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    from mcp_gateway.upstream_hints import enrich_upstream_status

    catalog = request.app.state.catalog
    errors = request.app.state.catalog_errors
    upstream = getattr(request.app.state, "upstream_status", {})
    pool = getattr(request.app.state, "pool", None)
    auth_hints = {sid: (spec.auth_hint or "") for sid, spec in catalog.servers.items()}
    detail = enrich_upstream_status(pool.status(), auth_hints=auth_hints) if pool else {}
    return {
        "status": "ok" if not errors else "degraded",
        "version": __version__,
        "catalog_errors": errors,
        "default_bundle": catalog.default_bundle,
        "mcp_default_bundle": catalog.mcp_default_bundle,
        "enforce_envelope": catalog.enforce_envelope,
        "upstreams": upstream,
        "upstream_detail": detail,
    }


@router.get("/bundles")
def list_bundles(request: Request) -> list[dict]:
    return request.app.state.bundles.list_bundles()


class RegistryImportBody(BaseModel):
    registry: dict[str, Any] | str


class RegistryServerUpdateBody(BaseModel):
    config: dict[str, Any]


class RegistryServerCreateBody(BaseModel):
    id: str
    url: str
    name: str = ""
    description: str = ""
    prefix: str = ""
    bearer: str = ""


class ProfileActivateBody(BaseModel):
    kind: str
    id: str


class CustomProfileBody(BaseModel):
    id: str = ""
    name: str = ""
    description: str = ""
    org_servers: list[str] = []
    registry_servers: list[str] = []
    tool_allowlist: list[str] | None = None
    meta_tools: list[str] | None = None


class ServerCredentialBody(BaseModel):
    # Absent : la clé reste celle en place. L'interface ne la reçoit plus, elle
    # ne peut donc pas la renvoyer — et un enregistrement sans saisie ne doit
    # pas valoir effacement.
    bearer: str | None = None
    headers: dict[str, str] | None = None
    url: str = ""


class ServerEnabledBody(BaseModel):
    enabled: bool


def _server_status(
    pool: UpstreamPool | None,
    key: str,
    *,
    enabled: bool = True,
) -> dict[str, Any]:
    if not enabled:
        return {
            "enabled": False,
            "online": False,
            "tools": 0,
            "error": None,
        }
    client = pool._clients.get(key) if pool else None
    online = bool(client and client.tools and not client.error)
    return {
        "enabled": True,
        "online": online,
        "tools": len(client.tools) if client and client.tools else 0,
        "error": client.error if client else None,
    }


def _patch_upstream_status(request: Request, key: str, result: str) -> None:
    status = getattr(request.app.state, "upstream_status", None)
    if not isinstance(status, dict):
        status = {}
    status[key] = result
    request.app.state.upstream_status = status


def _probe_response(pool: UpstreamPool, key: str, server_id: str | None = None) -> dict[str, Any]:
    probe = pool.client_probe(key)
    if server_id:
        probe["server_id"] = server_id
    # C'est la réponse qui suit la saisie d'une clé : le moment où savoir
    # pourquoi le service refuse encore compte le plus.
    return _with_hint(probe)


def _with_hint(entry: dict[str, Any]) -> dict[str, Any]:
    """Fait voyager le diagnostic avec l'erreur qu'il explique.

    Sans lui, l'interface ne dispose que du message brut de l'upstream et doit
    redériver la cause elle-même — ce qu'elle faisait dans du code jamais
    appelé, pendant que ce diagnostic-ci restait invisible.
    """
    from mcp_gateway.upstream_hints import diagnose_upstream_error, service_state

    creds = entry.get("credentials") or {}
    # « n'a pas besoin de clé » et « en a une » étaient confondus sous
    # configured=True : un service sans authentification passait pour configuré,
    # donc pour tombé, alors qu'il n'a jamais eu d'accès à renseigner.
    #
    # auth_required absent (connecteurs personnels) veut dire « on ne sait
    # pas » : la clé, s'il en faut une, vit dans la configuration du
    # connecteur. Rien ne permet d'affirmer qu'elle manque, donc on ne
    # l'affirme pas.
    if entry.get("auth_required") is False:
        source = "not_needed"
    elif entry.get("auth_required") is True:
        source = str(creds.get("source") or "none")
    else:
        source = str(creds.get("source") or "inconnu")
    entry["state"] = service_state(
        online=bool(entry.get("online")),
        enabled=entry.get("enabled") is not False,
        error=entry.get("error"),
        key_source=source,
    )
    # Rien n'a jamais été posé sur ce service : ni clé, ni adresse corrigée.
    # Sans ce repère, une installation neuve annonçait « ne répond plus » pour
    # un service qui n'a jamais rien eu — le mot « plus » suppose un avant.
    entry["never_configured"] = source in ("none", "not_needed", "inconnu") and not entry.get(
        "url_override"
    )

    if entry.get("error") and not entry.get("online"):
        tip = diagnose_upstream_error(
            entry["error"],
            auth_hint=entry.get("auth_hint") or "",
            server_id=str(entry.get("server_id") or entry.get("id") or ""),
            # L'écran qui l'affiche nomme déjà le service : pas de préfixe.
            with_prefix=False,
            key_source=source,
        )
        if tip:
            entry["hint"] = tip
    return entry


def _catalog_payload(request: Request) -> dict[str, Any]:
    catalog = request.app.state.catalog
    pool: UpstreamPool = request.app.state.pool
    conn: sqlite3.Connection = request.app.state.db

    org: list[dict[str, Any]] = []
    for sid, spec in catalog.servers.items():
        enabled = is_org_enabled(conn, sid)
        st = _server_status(pool, sid, enabled=enabled)
        effective_url, url_override = resolve_server_url(conn, sid, spec)
        org.append(
            _with_hint({
                "id": sid,
                "name": spec.name,
                "description": spec.description,
                "url": effective_url,
                "url_default": spec.url,
                "url_editable": spec.url_editable,
                "url_override": url_override,
                "transport": spec.transport,
                "prefix": spec.prefix,
                "auth_env": spec.auth_env,
                "auth_hint": spec.auth_hint,
                "key_location": spec.key_location,
                "auth_required": spec.auth_required,
                "kind": "org",
                "readonly": True,
                "credentials": credential_meta(conn, sid, spec),
                **st,
            })
        )

    personal: list[dict[str, Any]] = []
    registry_servers = list_registry_servers(conn)
    for entry in registry_servers:
        key = registry_pool_key(entry.server_id)
        enabled = is_registry_enabled(conn, entry.server_id)
        st = _server_status(pool, key, enabled=enabled)
        personal.append(
            _with_hint({
                "id": entry.server_id,
                "name": entry.name,
                "description": entry.description,
                "url": entry.url,
                "transport": entry.transport,
                "prefix": entry.prefix,
                "runtime": entry.runtime,
                "supported": entry.supported,
                "kind": "registry",
                "readonly": False,
                "config": config_sans_secrets(entry.config),
                **st,
                "error": st["error"] or entry.error,
            })
        )

    gw = getattr(request.app.state, "gateway_settings", None)
    cat_path = str(gw.catalog_path) if gw else ""

    return {
        "version": catalog.version,
        "org_catalog_path": cat_path,
        "catalog_sync": catalog_sync_status(request.app),
        "org": org,
        "personal": personal,
        "registry": export_registry(registry_servers),
    }


@router.get("/catalog")
def get_catalog(request: Request) -> dict:
    return _catalog_payload(request)


@router.get("/catalog/credentials/{server_id}")
def get_catalog_credentials(server_id: str, request: Request) -> dict[str, Any]:
    catalog = request.app.state.catalog
    if server_id not in catalog.servers:
        raise HTTPException(status_code=404, detail="Ce service ne figure pas dans le catalogue.")
    spec = catalog.servers[server_id]
    data = get_server_credentials_masked(request.app.state.db, server_id)
    data["url_default"] = spec.url
    data["url_editable"] = spec.url_editable
    effective_url, _ = resolve_server_url(request.app.state.db, server_id, spec)
    data["effective_url"] = effective_url
    return data


@router.put("/catalog/credentials/{server_id}")
async def put_catalog_credentials(
    server_id: str, body: ServerCredentialBody, request: Request
) -> dict[str, Any]:
    from mcp_gateway.db import log_audit

    catalog = request.app.state.catalog
    if server_id not in catalog.servers:
        raise HTTPException(status_code=404, detail="Ce service ne figure pas dans le catalogue.")
    conn: sqlite3.Connection = request.app.state.db
    spec = catalog.servers[server_id]
    try:
        set_server_credentials(
            conn,
            server_id,
            bearer=body.bearer,
            headers=body.headers,
            url=body.url if spec.url_editable else None,
            url_editable=spec.url_editable,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_audit(conn, "credentials.set", {"server_id": server_id})
    pool: UpstreamPool = request.app.state.pool
    probe_status = await pool.probe_catalog_server(server_id)
    _patch_upstream_status(request, server_id, probe_status)
    spec = catalog.servers[server_id]
    return {
        "server_id": server_id,
        "credentials": credential_meta(conn, server_id, spec),
        "upstream": probe_status,
        "probe": _probe_response(pool, server_id, server_id),
    }


@router.delete("/catalog/credentials/{server_id}")
async def delete_catalog_credentials(server_id: str, request: Request) -> dict[str, Any]:
    from mcp_gateway.db import log_audit

    catalog = request.app.state.catalog
    if server_id not in catalog.servers:
        raise HTTPException(status_code=404, detail="Ce service ne figure pas dans le catalogue.")
    conn: sqlite3.Connection = request.app.state.db
    delete_server_credentials(conn, server_id)
    log_audit(conn, "credentials.delete", {"server_id": server_id})
    pool: UpstreamPool = request.app.state.pool
    probe_status = await pool.probe_catalog_server(server_id)
    _patch_upstream_status(request, server_id, probe_status)
    spec = catalog.servers[server_id]
    return {
        "deleted": server_id,
        "credentials": credential_meta(conn, server_id, spec),
        "probe": _probe_response(pool, server_id, server_id),
    }


@router.put("/catalog/servers/{server_id}/enabled")
async def set_org_server_enabled(
    server_id: str, body: ServerEnabledBody, request: Request
) -> dict[str, Any]:
    from mcp_gateway.db import log_audit

    catalog = request.app.state.catalog
    if server_id not in catalog.servers:
        raise HTTPException(status_code=404, detail="Ce service ne figure pas dans le catalogue.")
    conn: sqlite3.Connection = request.app.state.db
    pool: UpstreamPool = request.app.state.pool
    set_enabled(conn, SCOPE_ORG, server_id, body.enabled)
    log_audit(conn, "server.enabled", {"server_id": server_id, "enabled": body.enabled})
    if body.enabled:
        probe_status = await pool.probe_catalog_server(server_id)
        _patch_upstream_status(request, server_id, probe_status)
    else:
        await pool.disconnect_server(server_id)
        _patch_upstream_status(request, server_id, "disabled")
    return {
        "server_id": server_id,
        "enabled": body.enabled,
        "probe": _probe_response(pool, server_id, server_id),
    }


@router.put("/catalog/registry/servers/{server_id}/enabled")
async def set_registry_server_enabled(
    server_id: str, body: ServerEnabledBody, request: Request
) -> dict[str, Any]:
    from mcp_gateway.db import log_audit

    if not get_registry_server(request.app.state.db, server_id):
        raise HTTPException(status_code=404, detail="Ce connecteur n'existe pas.")
    conn: sqlite3.Connection = request.app.state.db
    pool: UpstreamPool = request.app.state.pool
    key = registry_pool_key(server_id)
    set_enabled(conn, SCOPE_REGISTRY, server_id, body.enabled)
    log_audit(conn, "registry.enabled", {"server_id": server_id, "enabled": body.enabled})
    if body.enabled:
        probe_status = await pool.probe_registry_server(server_id)
        _patch_upstream_status(request, key, probe_status)
    else:
        await pool.disconnect_server(key)
        _patch_upstream_status(request, key, "disabled")
    return {
        "server_id": server_id,
        "enabled": body.enabled,
        "probe": _probe_response(pool, key, server_id),
    }


@router.get("/catalog/registry/export")
def export_catalog_registry(request: Request) -> dict[str, Any]:
    servers = list_registry_servers(request.app.state.db)
    return export_registry(servers)


@router.post("/catalog/registry/import")
async def import_catalog_registry(body: RegistryImportBody, request: Request) -> dict[str, Any]:
    from mcp_gateway.db import log_audit

    conn: sqlite3.Connection = request.app.state.db
    try:
        import_registry(conn, body.registry)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_audit(conn, "registry.import", {})
    pool: UpstreamPool = request.app.state.pool
    request.app.state.upstream_status = await pool.startup()
    return _catalog_payload(request)


@router.post("/catalog/registry/preview")
def preview_catalog_registry(body: RegistryImportBody) -> dict[str, Any]:
    try:
        parsed = parse_registry_import(body.registry)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "servers": [
            {
                "id": s.server_id,
                "name": s.name,
                "runtime": s.runtime,
                "url": s.url,
                "transport": s.transport,
                "prefix": s.prefix,
                "supported": s.supported,
                "error": s.error,
            }
            for s in parsed.values()
        ]
    }


@router.post("/catalog/registry/servers")
async def create_catalog_registry_server(
    body: RegistryServerCreateBody, request: Request
) -> dict[str, Any]:
    import re

    from mcp_gateway.db import log_audit

    server_id = body.id.strip()
    if not server_id or not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", server_id):
        raise HTTPException(
            status_code=400, detail="Identifiant invalide : lettres, chiffres, tirets et soulignés uniquement."
        )
    if not body.url.strip():
        raise HTTPException(status_code=400, detail="L'adresse du service est obligatoire.")
    conn: sqlite3.Connection = request.app.state.db
    if get_registry_server(conn, server_id):
        raise HTTPException(status_code=409, detail=f"Serveur '{server_id}' existe déjà")
    try:
        config = build_registry_config_from_simple(
            server_id=server_id,
            url=body.url,
            name=body.name,
            description=body.description,
            prefix=body.prefix,
            bearer=body.bearer,
        )
        server = normalize_server_config(server_id, config)
        upsert_registry_server(conn, server)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_audit(conn, "registry.create", {"id": server_id})
    pool: UpstreamPool = request.app.state.pool
    key = registry_pool_key(server_id)
    probe_status = await pool.probe_registry_server(server_id)
    _patch_upstream_status(request, key, probe_status)
    payload = _catalog_payload(request)
    payload["probe"] = _probe_response(pool, key, server_id)
    return payload


@router.get("/catalog/sync/status")
def get_catalog_sync_status(request: Request) -> dict[str, Any]:
    return catalog_sync_status(request.app)


@router.post("/catalog/sync")
async def post_catalog_sync(request: Request) -> dict[str, Any]:
    import httpx

    try:
        return await sync_catalog_from_gitlab(request.app)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Échec fetch GitLab : {exc}") from exc


@router.post("/catalog/reload")
async def post_catalog_reload(request: Request) -> dict[str, Any]:
    """Recharge le catalogue YAML local en mémoire (profils org, serveurs)."""
    result = await reload_catalog(request.app, source="local")
    result["tools_revision"] = bump_tools_revision(request.app)
    return result


@router.get("/catalog/registry/servers/{server_id}")
def get_catalog_registry_server(server_id: str, request: Request) -> dict[str, Any]:
    entry = get_registry_server(request.app.state.db, server_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Ce connecteur n'existe pas.")
    return {
        "id": entry.server_id,
        "name": entry.name,
        "prefix": entry.prefix,
        "runtime": entry.runtime,
        "url": entry.url,
        "transport": entry.transport,
        "config": config_sans_secrets(entry.config),
    }


@router.put("/catalog/registry/servers/{server_id}")
async def update_catalog_registry_server(
    server_id: str, body: RegistryServerUpdateBody, request: Request
) -> dict[str, Any]:
    from mcp_gateway.db import log_audit

    conn: sqlite3.Connection = request.app.state.db
    if not get_registry_server(conn, server_id):
        raise HTTPException(status_code=404, detail="Ce connecteur n'existe pas.")
    try:
        update_registry_server_config(conn, server_id, body.config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_audit(conn, "registry.update", {"id": server_id})
    pool: UpstreamPool = request.app.state.pool
    key = registry_pool_key(server_id)
    probe_status = await pool.probe_registry_server(server_id)
    _patch_upstream_status(request, key, probe_status)
    payload = _catalog_payload(request)
    payload["probe"] = _probe_response(pool, key, server_id)
    return payload


@router.delete("/catalog/registry/servers/{server_id}")
async def delete_catalog_registry_server(server_id: str, request: Request) -> dict[str, Any]:
    from mcp_gateway.db import log_audit

    conn: sqlite3.Connection = request.app.state.db
    if not delete_registry_server(conn, server_id):
        raise HTTPException(status_code=404, detail="Ce connecteur n'existe pas.")
    log_audit(conn, "registry.delete", {"id": server_id})
    pool: UpstreamPool = request.app.state.pool
    key = registry_pool_key(server_id)
    await pool.disconnect_server(key)
    _patch_upstream_status(request, key, "removed")
    return {"deleted": server_id}


@router.get("/sidecars")
def list_sidecars(request: Request) -> list[dict]:
    """Deprecated — utiliser GET /catalog (personal)."""
    payload = _catalog_payload(request)
    return [
        {
            "id": s["id"],
            "name": s["name"],
            "prefix": s["prefix"],
            "transport": s["transport"],
            "mcp_url": s.get("url") or "",
        }
        for s in payload["personal"]
    ]


@router.post("/sidecars")
async def create_sidecar(body: SidecarCreate, request: Request) -> dict:
    """Deprecated — préférer POST /catalog/registry/import avec JSON mcpServers."""
    from mcp_gateway.db import log_audit
    from mcp_gateway.registry import normalize_server_config, upsert_registry_server

    server_id = (body.prefix or body.name).lower().replace(" ", "-")
    config = {
        "url": body.mcp_url,
        "_metadata": {"name": body.name, "prefix": body.prefix or server_id},
    }
    server = normalize_server_config(server_id, config)
    conn: sqlite3.Connection = request.app.state.db
    upsert_registry_server(conn, server)
    log_audit(conn, "sidecar.create", {"id": server_id, "name": body.name})
    pool: UpstreamPool = request.app.state.pool
    await pool.startup()
    return {
        "id": server_id,
        "name": server.name,
        "mcp_url": server.url,
        "transport": server.transport,
        "prefix": server.prefix,
    }


@router.delete("/sidecars/{sidecar_id}")
async def delete_sidecar_legacy(sidecar_id: str, request: Request) -> dict:
    return await delete_catalog_registry_server(sidecar_id, request)


@router.get("/gateway")
def gateway_info(request: Request) -> dict:
    settings = request.app.state.settings
    # Qui publie le catalogue chargé. L'interface s'en sert pour nommer les
    # écrans — l'onglet du catalogue, le libellé d'un modèle — au lieu de porter une
    # organisation en dur : le produit se réinstalle ailleurs sans retouche.
    #
    # Un catalogue qui ne déclare rien reçoit un nom d'attente plutôt qu'un
    # vide : l'écran doit rester lisible pour qui vient d'installer l'outil,
    # et « Mon organisation » se lit comme une invitation à la renseigner.
    org = getattr(request.app.state.catalog, "organisation", {}) or {}
    nom_org = str(org.get("nom") or "").strip() or "Mon organisation"
    return {
        "mcp_url": f"{settings.host_url.rstrip('/')}/mcp",
        "widget_url": settings.widget_url,
        "organisation": {
            "nom": nom_org,
            "catalogue": str(org.get("catalogue") or "").strip()
            or (f"Catalogue {nom_org}" if org.get("nom") else "Mon catalogue"),
        },
        # L'écran promettait que copier l'adresse suffisait. Quand la passerelle
        # est protégée — le cas en production — l'assistant se fait refuser
        # l'entrée et doit d'abord obtenir une autorisation. Le dire ici évite
        # de laisser quelqu'un devant un refus qu'il ne comprend pas.
        "protegee": bool(settings.owner_lock),
        "cursor_config": {
            "mcpServers": {
                "passerelle": {
                    "url": f"{settings.host_url.rstrip('/')}/mcp",
                }
            }
        },
    }


@router.get("/tools")
def list_tools(
    request: Request,
    bundle: str | None = None,
    include_unavailable: bool = False,
) -> dict[str, Any]:
    """Outils agrégés pour le hub Tools (sources + liste searchable)."""
    catalog = request.app.state.catalog
    bundles = request.app.state.bundles
    pool: UpstreamPool = request.app.state.pool
    compositions: CompositionService = request.app.state.compositions
    conn: sqlite3.Connection = request.app.state.db

    if bundle and bundle in catalog.bundles:
        from mcp_gateway.profiles import org_profile_from_bundle

        profile = org_profile_from_bundle(conn, catalog, bundle)
    else:
        profile = resolve_web_profile(conn, catalog, bundles)

    payload = resolve_exposed_tools(
        catalog=catalog,
        pool=pool,
        compositions=compositions,
        conn=conn,
        profile=profile,
        include_unavailable=include_unavailable,
    )
    tools = payload["tools"]
    sources = payload["sources"]

    return {
        "active_bundle": payload["bundle_id"],
        "active_profile": {
            "kind": profile.kind,
            "id": profile.id,
            "label": profile.label,
        },
        "defaults": profile_defaults(catalog),
        "mcp_default_bundle": catalog.mcp_default_bundle,
        "include_unavailable": include_unavailable,
        "total": len(tools),
        "composition_count": payload["composition_count"],
        "sources": sources,
        "tools": tools,
        "pins": list_pins(request.app.state.db),
        "usage_top": list_usage(request.app.state.db),
    }


@router.get("/tools/personalizable")
def list_personalizable_tools(request: Request) -> dict[str, Any]:
    """Tous les outils du catalogue (services activés), sans filtre du profil actif."""
    catalog = request.app.state.catalog
    pool: UpstreamPool = request.app.state.pool
    compositions: CompositionService = request.app.state.compositions
    conn: sqlite3.Connection = request.app.state.db
    return aggregate_personalizable_tools(
        catalog=catalog,
        pool=pool,
        compositions=compositions,
        conn=conn,
    )


@router.post("/upstreams/reprobe")
async def reprobe_upstreams(request: Request) -> dict[str, Any]:
    pool: UpstreamPool = request.app.state.pool
    status = await pool.startup()
    request.app.state.upstream_status = status
    return {"upstreams": status, "upstream_detail": pool.status()}


@router.get("/tools/pins")
def get_tool_pins(request: Request) -> list[dict[str, Any]]:
    return list_pins(request.app.state.db)


@router.post("/tools/pins")
def pin_tool(body: ToolPinBody, request: Request) -> dict[str, Any]:
    return set_pin(request.app.state.db, body.tool_name, pinned=True)


@router.delete("/tools/pins/{tool_name}")
def unpin_tool(tool_name: str, request: Request) -> dict[str, Any]:
    return set_pin(request.app.state.db, tool_name, pinned=False)


@router.post("/tools/track")
def track_tool(body: ToolTrackBody, request: Request) -> dict[str, str]:
    track_tool_use(request.app.state.db, body.tool_name, count=max(1, body.count))
    return {"tracked": body.tool_name}


@router.post("/tools/call")
async def call_tool(body: ToolCallRequest, request: Request) -> dict[str, Any]:
    """Appel MCP read-only pour pickers dynamiques (credentials pod)."""
    mcp = request.app.state.mcp
    result = await mcp.tools_call(body.name, body.arguments or {}, "web-ui")
    if result.get("isError"):
        raise HTTPException(status_code=502, detail=_tool_result_text(result))
    return result


@router.get("/pickers/profiles")
def list_picker_profiles() -> list[dict[str, Any]]:
    return PICKER_PROFILES


def _tool_result_text(result: dict[str, Any]) -> str:
    for block in result.get("content") or []:
        if block.get("type") == "text":
            return str(block.get("text", ""))
    return "Erreur outil"


@router.put("/compositions/{comp_id}")
def update_composition(comp_id: str, body: CompositionCreate, request: Request) -> dict:
    svc: CompositionService = request.app.state.compositions
    try:
        return svc.update_composition(comp_id, body.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Cette composition n'existe pas.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/compositions/templates/list")
def composition_templates() -> list[dict[str, Any]]:
    return COMPOSITION_TEMPLATES


COMPOSITION_TEMPLATES: list[dict[str, Any]] = []


@router.get("/compositions")
def list_compositions(request: Request, status: str | None = None) -> list[dict]:
    svc: CompositionService = request.app.state.compositions
    return svc.list_compositions(status=status)


@router.post("/compositions")
async def create_composition(body: CompositionCreate, request: Request) -> dict:
    svc: CompositionService = request.app.state.compositions
    try:
        return svc.create_composition(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/compositions/{comp_id}")
def get_composition(comp_id: str, request: Request) -> dict:
    svc: CompositionService = request.app.state.compositions
    row = svc.get_composition(comp_id)
    if not row:
        raise HTTPException(status_code=404, detail="Cette composition n'existe pas.")
    return row


@router.post("/compositions/{comp_id}/validate")
def validate_composition(comp_id: str, request: Request) -> dict:
    svc: CompositionService = request.app.state.compositions
    try:
        return svc.validate(comp_id, mark=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Cette composition n'existe pas.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/compositions/{comp_id}/validate")
def preview_validate_composition(comp_id: str, request: Request) -> dict:
    svc: CompositionService = request.app.state.compositions
    try:
        return svc.validate(comp_id, mark=False)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Cette composition n'existe pas.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/compositions/{comp_id}/promote")
def promote_composition(comp_id: str, request: Request) -> dict:
    svc: CompositionService = request.app.state.compositions
    try:
        result = svc.promote(comp_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result["tools_revision"] = bump_tools_revision(request.app)
    return result


@router.post("/compositions/{comp_id}/demote")
def demote_composition(comp_id: str, request: Request) -> dict:
    """Retire une composition des outils de l'assistant.

    Activer n'avait pas d'inverse : pour qu'un assistant cesse de voir une
    composition, il fallait la supprimer.
    """
    svc: CompositionService = request.app.state.compositions
    try:
        result = svc.demote(comp_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    result["tools_revision"] = bump_tools_revision(request.app)
    return result


@router.delete("/compositions/{comp_id}")
def delete_composition(comp_id: str, request: Request) -> dict[str, str]:
    svc: CompositionService = request.app.state.compositions
    if not svc.delete_composition(comp_id):
        raise HTTPException(status_code=404, detail="Cette composition n'existe pas.")
    bump_tools_revision(request.app)
    return {"deleted": comp_id}


@router.post("/compositions/{comp_id}/execute")
async def execute_composition(
    comp_id: str, body: CompositionExecute, request: Request
) -> dict:
    svc: CompositionService = request.app.state.compositions
    try:
        return await svc.execute(comp_id, body.inputs)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.post("/composition-runs/{run_id}/resume")
async def resume_composition_run(
    run_id: str, body: CompositionResume, request: Request
) -> dict:
    svc: CompositionService = request.app.state.compositions
    try:
        return await svc.resume(run_id, body.response)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/composition-runs/{run_id}/abandon")
def abandon_composition_run(run_id: str, request: Request) -> dict:
    """Renonce à une exécution en attente.

    Sans elle, la liste des choses à traiter ne peut que grandir : une
    exécution suspendue n'avait d'autre issue que sa reprise.
    """
    svc: CompositionService = request.app.state.compositions
    try:
        row = svc.abandon_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="Cette exécution n'existe pas.")
    return row


@router.get("/composition-runs/{run_id}")
def get_composition_run(run_id: str, request: Request) -> dict:
    svc: CompositionService = request.app.state.compositions
    row = svc.get_run(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Cette exécution n'existe pas.")
    return row


@router.get("/profiles")
def get_profiles(request: Request) -> dict[str, Any]:
    conn: sqlite3.Connection = request.app.state.db
    catalog = request.app.state.catalog
    bundles = request.app.state.bundles
    return profiles_payload(conn, catalog, bundles)


@router.get("/profiles/meta-tools")
def list_meta_tools_catalog() -> dict[str, Any]:
    return {"tools": META_TOOL_CATALOG}


@router.post("/profiles/preview-tools")
def preview_profile_tools(body: CustomProfileBody, request: Request) -> dict[str, Any]:
    """Liste les outils disponibles pour une sélection de sources (sans allowlist)."""
    conn: sqlite3.Connection = request.app.state.db
    catalog = request.app.state.catalog
    pool: UpstreamPool = request.app.state.pool
    compositions: CompositionService = request.app.state.compositions
    org_servers = [s for s in body.org_servers if s in catalog.servers]
    reg_selected = set(body.registry_servers)
    registry_ids = [
        entry.server_id
        for entry in list_registry_servers(conn)
        if entry.server_id in reg_selected
    ]
    profile = ResolvedProfile(
        kind="custom",
        id="preview",
        label="preview",
        description="",
        org_servers=org_servers,
        registry_server_ids=registry_ids,
        bundle_id=None,
        editable=False,
        tool_allowlist=None,
        meta_tools=None,
    )
    payload = aggregate_tools_for_profile(
        catalog=catalog,
        pool=pool,
        compositions=compositions,
        conn=conn,
        profile=profile,
        include_unavailable=True,
    )
    selectable = [
        t
        for t in payload["tools"]
        if t.get("kind") in ("upstream", "registry", "composition")
    ]
    return {"total": len(selectable), "tools": selectable}


@router.post("/profiles/activate")
def activate_profile(body: ProfileActivateBody, request: Request) -> dict[str, Any]:
    from mcp_gateway.db import log_audit

    conn: sqlite3.Connection = request.app.state.db
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
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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


@router.post("/profiles/custom")
def create_profile(body: CustomProfileBody, request: Request) -> dict[str, Any]:
    from mcp_gateway.db import log_audit

    conn: sqlite3.Connection = request.app.state.db
    catalog = request.app.state.catalog
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Nom requis")
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_audit(conn, "profile.create", {"id": body.id or body.name})
    return profiles_payload(conn, catalog, request.app.state.bundles)


@router.put("/profiles/custom/{profile_id}")
def update_profile(profile_id: str, body: CustomProfileBody, request: Request) -> dict[str, Any]:
    from mcp_gateway.db import log_audit

    conn: sqlite3.Connection = request.app.state.db
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
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    log_audit(conn, "profile.update", {"id": profile_id})
    return profiles_payload(conn, catalog, request.app.state.bundles)


@router.delete("/profiles/custom/{profile_id}")
def remove_profile(profile_id: str, request: Request) -> dict[str, Any]:
    from mcp_gateway.db import log_audit

    conn: sqlite3.Connection = request.app.state.db
    catalog = request.app.state.catalog
    if not delete_custom_profile(conn, profile_id):
        raise HTTPException(status_code=404, detail="Ce profil n'existe pas.")
    log_audit(conn, "profile.delete", {"id": profile_id})
    return profiles_payload(conn, catalog, request.app.state.bundles)


@router.get("/bundles/active")
def active_bundle(request: Request) -> dict:
    conn: sqlite3.Connection = request.app.state.db
    profile = resolve_web_profile(conn, request.app.state.catalog, request.app.state.bundles)
    return {
        "active_bundle": profile.bundle_id or profile.id,
        "active_profile": {"kind": profile.kind, "id": profile.id, "label": profile.label},
    }


@router.get("/composition-runs")
def list_composition_runs(
    request: Request,
    limit: int = 30,
    status: str | None = None,
    include_state: bool = False,
) -> list[dict]:
    svc: CompositionService = request.app.state.compositions
    return svc.list_runs(status=status, limit=limit, include_state=include_state)


@router.post("/bundles/{bundle_id}/activate")
def activate_bundle(bundle_id: str, request: Request) -> dict:
    conn: sqlite3.Connection = request.app.state.db
    catalog = request.app.state.catalog
    bundles = request.app.state.bundles
    try:
        profile = activate_org_profile(conn, bundles, catalog, bundle_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {
        "active_bundle": bundle_id,
        "active_profile": {"kind": profile.kind, "id": profile.id, "label": profile.label},
    }


# ── Notifications web ─────────────────────────────────────────────────────
# Le service savait afficher qu'une exécution attendait ; il fallait ouvrir la
# page pour l'apprendre. Ces trois routes permettent à un navigateur de
# s'abonner, et à la passerelle de le joindre application fermée.


@router.get("/push/cle-publique")
def push_cle_publique(request: Request) -> dict:
    """La clé que le navigateur doit présenter pour s'abonner.

    Publique par nature : elle ne permet que de recevoir, jamais d'envoyer.
    """
    from mcp_gateway.notifications import cles_vapid

    _, publique = cles_vapid(request.app.state.db)
    return {"cle_publique": publique}


@router.post("/push/abonnements", status_code=201)
async def push_abonner(request: Request) -> dict:
    from mcp_gateway.notifications import enregistrer_abonnement

    corps = await request.json()
    abonnement = corps.get("abonnement") or corps
    if not abonnement.get("endpoint"):
        raise HTTPException(status_code=400, detail="Abonnement sans adresse de remise.")
    enregistrer_abonnement(
        request.app.state.db, abonnement, str(corps.get("appareil") or "")
    )
    return {"enregistre": True}


@router.delete("/push/abonnements")
async def push_desabonner(request: Request) -> dict:
    from mcp_gateway.notifications import oublier_abonnement

    corps = await request.json()
    endpoint = (corps or {}).get("endpoint", "")
    return {"oublie": oublier_abonnement(request.app.state.db, endpoint)}


@router.post("/push/essai")
def push_essai(request: Request) -> dict:
    """Envoie une notification d'essai — le seul moyen de savoir que la chaîne
    complète fonctionne avant qu'une composition ne se suspende pour de vrai."""
    from mcp_gateway.notifications import prevenir

    atteints = prevenir(
        request.app.state.db,
        "Passerelle",
        "Les notifications fonctionnent. Vous serez prévenu quand une composition attendra votre réponse.",
        tag="essai",
    )
    return {"appareils_atteints": atteints}
