"""Runtime gateway intégré dans le processus Atelier (pool, catalog, compositions)."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from mcp_gateway.auth import migrate_auth_schema, resolve_owner_key
from mcp_gateway.bundles import BundleSession
from mcp_gateway.catalog import load_catalog, validate_catalog
from mcp_gateway.catalog_sync import catalog_sync_status
from mcp_gateway.compositions import CompositionService
from mcp_gateway.config import Settings
from mcp_gateway.db import connect
from mcp_gateway.mcp import McpGateway
from mcp_gateway.mcp.tools_registry import ToolsChangeTracker
from mcp_gateway.notifications import migrer_schema as migrer_notifications
from mcp_gateway.profiles import WEB_UI_SESSION
from mcp_gateway.registry import import_registry, list_registry_servers
from mcp_gateway.upstream import UpstreamPool

from mcp_gateway.atelier.auth import ensure_owner_key
from mcp_gateway.atelier.config import AtelierSettings

log = logging.getLogger("atelier.gateway")


def build_gateway_settings(settings: AtelierSettings) -> Settings:
    owner = ensure_owner_key(settings.owner_key_path)
    catalog = settings.gateway_catalog_path
    if not catalog.is_file():
        seed = Path(__file__).resolve().parent.parent.parent / "mcp" / "catalog.yaml"
        if seed.is_file():
            settings.mcp_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(seed, catalog)
    return Settings(
        catalog_path=catalog,
        db_path=settings.gateway_db_path,
        host_url=f"http://127.0.0.1:{settings.port}",
        owner_key=owner,
        owner_lock=False,
        upstream_probe_on_startup=True,
    )


def migrate_legacy_registry_json(conn: Any, registry_path: Path) -> bool:
    """Importe `registry.json` vers SQLite si la table sidecars est vide."""
    if not registry_path.is_file():
        return False
    if list_registry_servers(conn):
        return False
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("registry.json illisible — migration ignorée")
        return False
    servers = data.get("servers") if isinstance(data, dict) else None
    if not isinstance(servers, dict) or not servers:
        return False
    import_registry(conn, {"mcpServers": servers})
    backup = registry_path.with_suffix(
        f".migrated.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.json"
    )
    registry_path.rename(backup)
    log.info("registry.json migré vers gateway.db — backup %s", backup)
    return True


async def gateway_startup(app: FastAPI, atelier_settings: AtelierSettings) -> None:
    cfg = build_gateway_settings(atelier_settings)
    app.state.gateway_settings = cfg
    app.state.db = connect(cfg.db_path)
    migrate_auth_schema(app.state.db)
    migrer_notifications(app.state.db)
    app.state.gateway_owner_key = resolve_owner_key(app.state.db, cfg)
    migrate_legacy_registry_json(app.state.db, atelier_settings.mcp_registry_path)

    app.state.catalog = load_catalog(cfg.catalog_path)
    app.state.catalog_errors = validate_catalog(app.state.catalog)
    app.state.catalog_sync = catalog_sync_status(app)
    app.state.bundles = BundleSession(app.state.catalog)
    app.state.pool = UpstreamPool(app.state.catalog, app.state.db)
    mcp_holder: dict[str, McpGateway] = {}

    async def composition_tool_call(
        name: str, arguments: dict, session_id: str | None = None
    ) -> dict:
        if "mcp" in mcp_holder:
            return await mcp_holder["mcp"].tools_call(
                name, arguments, session_id or WEB_UI_SESSION, internal=False
            )
        return await app.state.pool.call(name, arguments)

    app.state.tools_change_tracker = ToolsChangeTracker()
    app.state.compositions = CompositionService(app.state.db, composition_tool_call)
    app.state.upstream_status: dict[str, str] = {"status": "probing"}
    app.state.mcp = McpGateway(
        app.state.catalog,
        app.state.bundles,
        app.state.pool,
        app.state.compositions,
        tools_change_tracker=app.state.tools_change_tracker,
    )
    mcp_holder["mcp"] = app.state.mcp
    app.state.compositions.bind_call_tool(composition_tool_call)

    async def _probe() -> None:
        app.state.upstream_status = await app.state.pool.startup()

    asyncio.create_task(_probe())


async def gateway_shutdown(app: FastAPI) -> None:
    pool = getattr(app.state, "pool", None)
    if pool:
        await pool.shutdown()
    db = getattr(app.state, "db", None)
    if db:
        db.close()


@asynccontextmanager
async def atelier_lifespan(app: FastAPI, settings: AtelierSettings):
    await gateway_startup(app, settings)
    yield
    await gateway_shutdown(app)
