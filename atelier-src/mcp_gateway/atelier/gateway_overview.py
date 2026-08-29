"""Agrégat Connecteurs — catalogue org, registry, pool, compositions."""

from __future__ import annotations

from typing import Any

from fastapi import Request


def build_mcp_overview(request: Request) -> dict[str, Any]:
    """Payload pour l'onglet Connecteurs (niveau 1 pool)."""
    from mcp_gateway.api import _catalog_payload

    catalog = _catalog_payload(request)
    compositions: list[dict[str, Any]] = []
    comp_svc = getattr(request.app.state, "compositions", None)
    if comp_svc is not None:
        compositions = comp_svc.list_compositions()

    upstream = getattr(request.app.state, "upstream_status", {}) or {}
    gw = getattr(request.app.state, "gateway_settings", None)
    gateway_db = str(gw.db_path) if gw else ""

    org = catalog.get("org") or []
    personal = catalog.get("personal") or []
    pool_summary = _pool_summary(upstream, org, personal)

    return {
        "catalog": catalog,
        "compositions": compositions,
        "upstream": upstream,
        "gateway_db": gateway_db,
        "pool_summary": pool_summary,
    }


def _pool_summary(
    upstream: dict[str, str],
    org: list[dict[str, Any]],
    personal: list[dict[str, Any]],
) -> dict[str, int]:
    counts = {"connected": 0, "stdio_local": 0, "error": 0, "disabled": 0, "other": 0}
    for item in org + personal:
        if not item.get("enabled", True):
            counts["disabled"] += 1
            continue
        sid = item.get("id") or ""
        key = f"registry:{sid}" if item.get("kind") == "registry" else sid
        raw = upstream.get(key) or ""
        if raw == "connected":
            counts["connected"] += 1
        elif raw == "stdio-local":
            counts["stdio_local"] += 1
        elif raw.startswith("error") or item.get("error"):
            counts["error"] += 1
        else:
            counts["other"] += 1
    return counts
