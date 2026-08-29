"""Synchronisation du catalogue org depuis GitLab (ou URL YAML distante)."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from mcp_gateway.bundles import BundleSession
from mcp_gateway.catalog import load_catalog, load_catalog_text, validate_catalog
from mcp_gateway.config import Settings

logger = logging.getLogger("mcp_gateway.catalog_sync")


async def fetch_catalog_text(url: str, token: str = "") -> tuple[str, str]:
    headers: dict[str, str] = {}
    if token:
        headers["PRIVATE-TOKEN"] = token
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        text = response.text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return text, digest


def _gateway_cfg(app) -> Settings:
    return getattr(app.state, "gateway_settings", None) or app.state.settings


def catalog_sync_status(app) -> dict[str, Any]:
    meta = getattr(app.state, "catalog_sync", None) or {}
    cfg = _gateway_cfg(app)
    catalog = app.state.catalog
    return {
        "source": meta.get("source") or "local",
        "path": str(cfg.catalog_path),
        "url": cfg.gitlab_catalog_url or "",
        "sync_enabled": bool(cfg.gitlab_catalog_url),
        "at": meta.get("at"),
        "digest": meta.get("digest"),
        "version": catalog.version if catalog else meta.get("version"),
        "catalog_errors": len(getattr(app.state, "catalog_errors", []) or []),
        "message": meta.get("message"),
    }


async def reload_catalog(app, *, text: str | None = None, source: str = "local") -> dict[str, Any]:
    """Recharge le catalogue en mémoire et reprobe les upstreams."""
    cfg = _gateway_cfg(app)
    if text is None:
        catalog = load_catalog(cfg.catalog_path)
        digest = hashlib.sha256(cfg.catalog_path.read_bytes()).hexdigest()[:12]
        sync_meta = {
            "source": source,
            "at": datetime.now(timezone.utc).isoformat(),
            "digest": digest,
            "version": catalog.version,
            "message": "Catalogue local",
        }
    else:
        catalog = load_catalog_text(text)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        sync_meta = {
            "source": source,
            "at": datetime.now(timezone.utc).isoformat(),
            "digest": digest,
            "version": catalog.version,
            "message": "Catalogue synchronisé",
        }
        if cfg.catalog_sync_write_local:
            try:
                cfg.catalog_path.write_text(text, encoding="utf-8")
            except OSError as exc:
                logger.warning("Impossible d'écrire le catalogue local : %s", exc)

    errors = validate_catalog(catalog)
    app.state.catalog = catalog
    app.state.catalog_errors = errors
    app.state.bundles = BundleSession(catalog)
    app.state.pool.catalog = catalog
    if getattr(app.state, "mcp", None):
        app.state.mcp.catalog = catalog
    app.state.catalog_sync = sync_meta
    upstream_status = await app.state.pool.startup()
    app.state.upstream_status = upstream_status
    return {
        **sync_meta,
        "catalog_errors": errors,
        "upstreams": upstream_status,
    }


async def sync_catalog_from_gitlab(app) -> dict[str, Any]:
    cfg: Settings = app.state.settings
    url = (cfg.gitlab_catalog_url or "").strip()
    if not url:
        raise ValueError(
            "URL GitLab non configurée — définissez GATEWAY_GITLAB_CATALOG_URL"
        )
    text, _digest = await fetch_catalog_text(url, cfg.gitlab_catalog_token)
    return await reload_catalog(app, text=text, source=url)
