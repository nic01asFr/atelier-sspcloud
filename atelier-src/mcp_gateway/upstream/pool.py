from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any

from mcp_gateway.catalog import Catalog, ServerSpec
from mcp_gateway.config import settings
from mcp_gateway.mcp_fields import upstream_tool_fields
from mcp_gateway.registry import get_registry_server, list_registry_servers, registry_pool_key
from mcp_gateway.credentials import resolve_server_headers, resolve_server_url
from mcp_gateway.server_enable import is_org_enabled, is_registry_enabled
from mcp_gateway.upstream.client import UpstreamClient

logger = logging.getLogger("mcp_gateway.upstream")


def _registry_stdio_local(entry) -> bool:
    return entry.runtime == "stdio" or entry.transport == "stdio" or bool(entry.config.get("command"))


class UpstreamPool:
    def __init__(
        self,
        catalog: Catalog,
        db: sqlite3.Connection | None = None,
        *,
        stdio_lances: dict[str, dict[str, str]] | None = None,
    ):
        self.catalog = catalog
        self.db = db
        self._clients: dict[str, Any] = {}
        # Les serveurs stdio du registre que la passerelle lance elle-même,
        # avec l'environnement propre à cette instance (identifiant → env).
        # Les autres restent `stdio-local` : lancés par le client final seul.
        self.stdio_lances: dict[str, dict[str, str]] = dict(stdio_lances or {})

    async def startup(self) -> dict[str, str]:
        """Connecte tous les serveurs catalogue + sidecars SQLite."""
        status: dict[str, str] = {}
        for sid, spec in self.catalog.servers.items():
            if self.db and not is_org_enabled(self.db, sid):
                await self.disconnect_server(sid)
                status[sid] = "disabled"
                continue
            hdrs = resolve_server_headers(self.db, sid, spec)
            url, _ = resolve_server_url(self.db, sid, spec)
            status[sid] = await self._connect_spec(
                sid, url, spec.transport, spec, extra_headers=hdrs or None
            )
        if self.db:
            for entry in list_registry_servers(self.db):
                if not is_registry_enabled(self.db, entry.server_id):
                    key = registry_pool_key(entry.server_id)
                    await self.disconnect_server(key)
                    status[key] = "disabled"
                    continue
                key = registry_pool_key(entry.server_id)
                if _registry_stdio_local(entry):
                    if entry.server_id in self.stdio_lances:
                        status[key] = await self._connect_stdio(key, entry)
                    else:
                        status[key] = "stdio-local"
                    continue
                if not entry.supported or not entry.url:
                    client = UpstreamClient(key, entry.url or "stdio://local", entry.transport)
                    client.error = entry.error or "Runtime non supporté"
                    self._clients[key] = client
                    status[key] = f"error: {client.error}"
                    continue
                status[key] = await self._connect_spec(
                    key,
                    entry.url,
                    entry.transport,
                    auth_header=entry.auth_header,
                    extra_headers=entry.headers,
                )
        return status

    async def probe_catalog_server(self, server_id: str) -> str:
        """Re-probe un seul serveur catalogue (sans toucher aux autres upstreams)."""
        spec = self.catalog.servers.get(server_id)
        if not spec:
            raise KeyError(f"Unknown catalog server: {server_id}")
        hdrs = resolve_server_headers(self.db, server_id, spec)
        url, _ = resolve_server_url(self.db, server_id, spec)
        return await self._connect_spec(
            server_id, url, spec.transport, spec, extra_headers=hdrs or None
        )

    async def probe_registry_server(self, server_id: str) -> str:
        """Re-probe un seul serveur registre perso."""
        if not self.db:
            raise KeyError("Registry requires database")
        entry = get_registry_server(self.db, server_id)
        if not entry:
            raise KeyError(f"Unknown registry server: {server_id}")
        key = registry_pool_key(entry.server_id)
        if _registry_stdio_local(entry):
            if entry.server_id in self.stdio_lances:
                return await self._connect_stdio(key, entry)
            return "stdio-local"
        if not entry.supported or not entry.url:
            client = UpstreamClient(key, entry.url or "stdio://local", entry.transport)
            client.error = entry.error or "Runtime non supporté"
            self._clients[key] = client
            return f"error: {client.error}"
        return await self._connect_spec(
            key,
            entry.url,
            entry.transport,
            auth_header=entry.auth_header,
            extra_headers=entry.headers,
        )

    async def disconnect_server(self, key: str) -> None:
        client = self._clients.pop(key, None)
        if client:
            await client.close()

    def client_probe(self, key: str) -> dict[str, Any]:
        client = self._clients.get(key)
        if not client:
            return {"online": False, "tools": 0, "error": "non connecté"}
        return {
            "online": bool(client.tools and not client.error),
            "tools": len(client.tools) if client.tools else 0,
            "error": client.error,
        }

    def registry_entries(self) -> list[tuple[str, str]]:
        """(pool_key, prefix) pour chaque serveur registry remote supporté."""
        if not self.db:
            return []
        out: list[tuple[str, str]] = []
        for entry in list_registry_servers(self.db):
            if not is_registry_enabled(self.db, entry.server_id):
                continue
            if entry.supported and entry.url:
                out.append((registry_pool_key(entry.server_id), entry.prefix))
        return out

    async def _connect_stdio(self, key: str, entry: Any) -> str:
        """Sonde un serveur stdio que la passerelle lance (voir `ClientStdio`)."""
        from mcp_gateway.upstream.stdio_client import ClientStdio

        await self.disconnect_server(key)
        cfg = entry.config if isinstance(entry.config, dict) else {}
        args = cfg.get("args")
        env = cfg.get("env")
        client = ClientStdio(
            key,
            str(cfg.get("command") or ""),
            [str(a) for a in args] if isinstance(args, list) else [],
            {
                **({str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else {}),
                **self.stdio_lances.get(entry.server_id, {}),
            },
        )
        ok = await client.connect()
        self._clients[key] = client
        if ok and client.tools and self.db:
            from mcp_gateway.tool_cache import save_upstream_tools

            save_upstream_tools(self.db, key, entry.prefix, client.tools)
        return "connected" if ok else f"error: {client.error}"

    async def _connect_spec(
        self,
        key: str,
        url: str,
        transport: str,
        spec: ServerSpec | None = None,
        *,
        auth_header: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> str:
        auth = auth_header
        if not (extra_headers and ("Authorization" in extra_headers or "authorization" in extra_headers)):
            auth = auth_header or self._auth_header(key, spec)
        client = UpstreamClient(
            key,
            url,
            transport,
            auth_header=auth,
            extra_headers=extra_headers,
        )
        ok = await client.connect()
        self._clients[key] = client
        if ok and client.tools and self.db:
            from mcp_gateway.tool_cache import save_upstream_tools

            prefix = self._prefix_for_key(key, spec)
            save_upstream_tools(self.db, key, prefix, client.tools)
        return "connected" if ok else f"error: {client.error}"

    def _prefix_for_key(self, key: str, spec: ServerSpec | None) -> str:
        if spec:
            return spec.prefix
        if self.db:
            for entry in list_registry_servers(self.db):
                if registry_pool_key(entry.server_id) == key:
                    return entry.prefix
        return key.split(":")[-1]

    def prefixed_tools(
        self,
        server_ids: list[str],
        prefix_map: dict[str, str],
        *,
        include_unavailable: bool = False,
    ) -> list[dict]:
        out: list[dict] = []
        for sid in server_ids:
            client = self._clients.get(sid)
            if not client or not client.tools:
                spec = self.catalog.servers.get(sid)
                pname = prefix_map.get(sid, sid)
                if client and client.error:
                    if include_unavailable:
                        out.append(
                            {
                                "name": f"{pname}__unavailable",
                                "description": f"[offline] {spec.name if spec else sid}: {client.error}",
                                "inputSchema": {"type": "object", "properties": {}},
                            }
                        )
                continue
            pname = prefix_map.get(sid, sid.split(":")[-1])
            for tool in client.tools:
                row: dict = {
                    "name": f"{pname}__{tool['name']}",
                    "description": tool.get("description") or "",
                    "inputSchema": tool.get("inputSchema") or {"type": "object", "properties": {}},
                }
                row.update(upstream_tool_fields(tool))
                out.append(row)
        return out

    def resolve_tool(self, qualified: str) -> tuple[UpstreamClient | None, str]:
        if "__" not in qualified:
            return None, qualified
        prefix, tool_name = qualified.split("__", 1)
        for sid, spec in self.catalog.servers.items():
            if spec.prefix == prefix:
                return self._clients.get(sid), tool_name
        if self.db:
            for entry in list_registry_servers(self.db):
                key = registry_pool_key(entry.server_id)
                if entry.prefix == prefix:
                    return self._clients.get(key), tool_name
        return None, tool_name

    async def call(self, qualified: str, arguments: dict[str, Any]) -> dict[str, Any]:
        client, tool_name = self.resolve_tool(qualified)
        if not client:
            raise KeyError(f"No upstream for tool {qualified}")
        if tool_name == "unavailable":
            raise RuntimeError(f"Upstream offline for {qualified}")
        return await client.call_tool(tool_name, arguments)

    async def shutdown(self) -> None:
        for client in self._clients.values():
            await client.close()
        self._clients.clear()

    def status(self) -> dict[str, Any]:
        return {
            key: {
                "url": c.url,
                "transport": c._mode,
                "tools": len(c.tools),
                "error": c.error,
            }
            for key, c in self._clients.items()
        }

    @staticmethod
    def _auth_header(server_id: str, spec: ServerSpec | None) -> str | None:
        token = ""
        if spec and spec.auth_env:
            token = os.environ.get(spec.auth_env, "")
        if not token:
            fallback = {
                "compute": settings.bearer_compute,
                "qgis": settings.bearer_qgis,
            }
            token = fallback.get(server_id, "")
        if not token:
            return None
        return token if token.startswith("Bearer ") else f"Bearer {token}"
