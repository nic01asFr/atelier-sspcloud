"""Agrégation et filtrage unifiés des outils exposés (API widget + MCP)."""
from __future__ import annotations

import sqlite3
from typing import Any

from mcp_gateway.catalog import Catalog
from mcp_gateway.compositions import CompositionService
from mcp_gateway.meta_tools_defs import META_TOOLS
from mcp_gateway.tool_hints import apply_tool_hints, gateway_tool_hints
from mcp_gateway.profiles import ResolvedProfile, apply_tool_allowlist
from mcp_gateway.registry import list_registry_servers, registry_pool_key
from mcp_gateway.server_enable import filter_enabled_org, is_registry_enabled
from mcp_gateway.tool_cache import append_upstream_tools
from mcp_gateway.tools_hub import meta_tools_for_profile
from mcp_gateway.upstream.pool import UpstreamPool

_META_INPUT_SCHEMAS = {t["name"]: t.get("inputSchema") for t in META_TOOLS}


def aggregate_tools_for_profile(
    *,
    catalog: Catalog,
    pool: UpstreamPool,
    compositions: CompositionService,
    conn: sqlite3.Connection,
    profile: ResolvedProfile,
    include_unavailable: bool = False,
) -> dict[str, Any]:
    bundle_id = profile.bundle_id or profile.id
    meta_defs = meta_tools_for_profile(catalog, profile)

    server_ids = profile.org_servers
    prefix_map: dict[str, str] = {}
    for sid in server_ids:
        spec = catalog.servers.get(sid)
        prefix_map[sid] = spec.prefix if spec else sid

    sources: list[dict[str, Any]] = []
    tools: list[dict[str, Any]] = []

    meta = [
        {
            "id": "gateway",
            "name": "Pilotage",
            "kind": "meta",
            "prefix": "gateway",
            "tools": 0,
            "online": True,
        },
    ]
    for t in meta_defs:
        item: dict[str, Any] = {
            "name": t["name"],
            "source": "gateway",
            "kind": "meta",
            "description": t.get("description") or "",
            "online": True,
        }
        schema = _META_INPUT_SCHEMAS.get(t["name"])
        if schema:
            item["inputSchema"] = schema
        meta_hints = gateway_tool_hints(t["name"])
        if meta_hints.get("title"):
            item["title"] = meta_hints["title"]
        if meta_hints.get("annotations"):
            item["annotations"] = meta_hints["annotations"]
        tools.append(item)
    meta[0]["tools"] = len(meta_defs)
    sources.extend(meta)

    for sid in server_ids:
        spec = catalog.servers.get(sid)
        client = pool._clients.get(sid) if pool else None
        online = bool(client and client.tools and not client.error)
        pname = prefix_map.get(sid, sid)
        added = append_upstream_tools(
            tools,
            conn=conn,
            source_key=sid,
            prefix=pname,
            kind="upstream",
            client=client,
            include_unavailable=include_unavailable,
            offline_error=client.error if client else "non connecté",
        )
        sources.append(
            {
                "id": sid,
                "name": spec.name if spec else sid,
                "kind": "catalog",
                "prefix": pname,
                "tools": added,
                "online": online,
                "error": client.error if client else None,
            }
        )

    if pool and pool.db:
        registry_allowed = set(profile.registry_server_ids)
        for entry in list_registry_servers(pool.db):
            if entry.server_id not in registry_allowed:
                continue
            if profile.id != "preview" and not is_registry_enabled(pool.db, entry.server_id):
                continue
            key = registry_pool_key(entry.server_id)
            client = pool._clients.get(key)
            online = bool(client and client.tools and not client.error)
            added = append_upstream_tools(
                tools,
                conn=conn,
                source_key=key,
                prefix=entry.prefix,
                kind="registry",
                client=client,
                include_unavailable=include_unavailable,
                offline_error=(client.error if client else None) or entry.error,
            )
            sources.append(
                {
                    "id": key,
                    "name": entry.name,
                    "kind": "registry",
                    "prefix": entry.prefix,
                    "tools": added,
                    "online": online,
                    "error": (client.error if client else None) or entry.error,
                }
            )

    prod = compositions.list_compositions(status="production")
    sources.append(
        {
            "id": "compositions",
            "name": "Compositions",
            "kind": "compositions",
            "prefix": "composition",
            "tools": len(prod),
            "online": True,
        }
    )
    for c in prod:
        item = {
            "name": c["tool_name"],
            "source": "compositions",
            "kind": "composition",
            "description": c.get("description") or c["name"],
            "online": True,
            "variant": bool(c.get("variant")),
            "source_tool": c.get("source_tool"),
            "composition_id": c.get("id"),
        }
        schema = c.get("input_schema")
        if schema:
            item["inputSchema"] = schema
        apply_tool_hints(item)
        tools.append(item)

    return {
        "bundle_id": bundle_id,
        "sources": sources,
        "tools": tools,
        "composition_count": len(prod),
    }


def resolve_exposed_tools(
    *,
    catalog: Catalog,
    pool: UpstreamPool,
    compositions: CompositionService,
    conn: sqlite3.Connection,
    profile: ResolvedProfile,
    include_unavailable: bool = False,
) -> dict[str, Any]:
    """Agrège puis applique l'allowlist profil (meta-tools exclus de l'allowlist)."""
    payload = aggregate_tools_for_profile(
        catalog=catalog,
        pool=pool,
        compositions=compositions,
        conn=conn,
        profile=profile,
        include_unavailable=include_unavailable,
    )
    tools, sources = apply_tool_allowlist(profile, payload["tools"], payload["sources"])
    return {
        **payload,
        "tools": tools,
        "sources": sources,
        "profile": profile,
    }


def exposed_tool_names(payload: dict[str, Any]) -> set[str]:
    return {str(t["name"]) for t in payload.get("tools", [])}


def tools_to_mcp_format(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in tools:
        public = {k: v for k, v in t.items() if not k.startswith("_")}
        item: dict[str, Any] = {
            "name": public["name"],
            "description": public.get("description") or "",
            "inputSchema": public.get("inputSchema")
            or {"type": "object", "properties": {}},
        }
        if public.get("title"):
            item["title"] = public["title"]
        if public.get("annotations"):
            item["annotations"] = public["annotations"]
        if public.get("outputSchema"):
            item["outputSchema"] = public["outputSchema"]
        out.append(item)
    return out


def aggregate_personalizable_tools(
    *,
    catalog: Catalog,
    pool: UpstreamPool,
    compositions: CompositionService,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Catalogue complet des outils personnalisables — sans filtre profil actif."""
    org_servers = filter_enabled_org(conn, list(catalog.servers.keys()))
    registry_ids = [
        entry.server_id
        for entry in list_registry_servers(conn)
        if is_registry_enabled(conn, entry.server_id)
    ]
    profile = ResolvedProfile(
        kind="custom",
        id="preview",
        label="personalizable",
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
    tools = [
        t
        for t in payload["tools"]
        if t.get("kind") in ("upstream", "registry", "meta")
    ]
    return {"total": len(tools), "tools": tools}
