"""Adaptateur registre MCP intégré (SQLite gateway) pour l'API hub Atelier."""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from typing import Any

from mcp_gateway.registry import (
    config_sans_secrets,
    delete_registry_server,
    get_registry_server,
    import_registry,
    list_registry_servers,
    update_registry_server_config,
)
from mcp_gateway.server_enable import SCOPE_REGISTRY, is_registry_enabled, set_enabled

from mcp_gateway.atelier.mcp_registry import mask_server_entry, validate_server_name as validate_name


def _entry_to_hub_shape(conn: sqlite3.Connection, entry: Any) -> dict[str, Any]:
    cfg = deepcopy(entry.config)
    out = {k: v for k, v in cfg.items() if k != "_metadata"}
    out["enabled"] = is_registry_enabled(conn, entry.server_id)
    return out


class IntegratedMcpStore:
    """Registre perso pod — backend gateway SQLite."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list_servers(self, *, mask: bool = False) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for entry in list_registry_servers(self._conn):
            row = _entry_to_hub_shape(self._conn, entry)
            if mask:
                row = mask_server_entry(row)
            out[entry.server_id] = row
        return out

    def upsert(self, name: str, raw: dict[str, Any]) -> dict[str, Any]:
        name = validate_name(name)
        enabled = raw.get("enabled", True)
        cfg = {k: v for k, v in raw.items() if k != "enabled"}
        if "_metadata" not in cfg:
            cfg["_metadata"] = {"name": name}
        update_registry_server_config(self._conn, name, cfg)
        set_enabled(self._conn, SCOPE_REGISTRY, name, bool(enabled))
        entry = get_registry_server(self._conn, name)
        if not entry:
            raise ValueError(f"failed to upsert {name}")
        return _entry_to_hub_shape(self._conn, entry)

    def set_enabled(self, name: str, enabled: bool) -> dict[str, Any]:
        name = validate_name(name)
        if not get_registry_server(self._conn, name):
            raise KeyError(name)
        set_enabled(self._conn, SCOPE_REGISTRY, name, enabled)
        entry = get_registry_server(self._conn, name)
        if not entry:
            raise KeyError(name)
        return _entry_to_hub_shape(self._conn, entry)

    def delete(self, name: str) -> None:
        name = validate_name(name)
        if not delete_registry_server(self._conn, name):
            raise KeyError(name)

    def import_mcp_servers(
        self,
        mcp_servers: dict[str, Any],
        *,
        default_enabled: bool = True,
        replace: bool = False,
    ) -> list[str]:
        if replace:
            for entry in list_registry_servers(self._conn):
                delete_registry_server(self._conn, entry.server_id)
        payload: dict[str, Any] = {}
        for name, raw in mcp_servers.items():
            validate_name(name)
            if not isinstance(raw, dict):
                raise ValueError(f"server {name!r} must be an object")
            entry_raw = deepcopy(raw)
            enabled = entry_raw.pop("enabled", default_enabled)
            payload[name] = entry_raw
        import_registry(self._conn, {"mcpServers": payload})
        imported: list[str] = []
        for name, raw in mcp_servers.items():
            set_enabled(self._conn, SCOPE_REGISTRY, name, bool(raw.get("enabled", default_enabled)))
            imported.append(name)
        return imported

    def enabled_mcp_servers(self) -> dict[str, dict[str, Any]]:
        """Forme Claude `mcpServers` (enabled registry, secrets inclus)."""
        out: dict[str, dict[str, Any]] = {}
        for entry in list_registry_servers(self._conn):
            if not is_registry_enabled(self._conn, entry.server_id):
                continue
            cfg = deepcopy(entry.config)
            for k in ("_metadata", "enabled"):
                cfg.pop(k, None)
            out[entry.server_id] = cfg
        return out

    def masked_export(self) -> dict[str, dict[str, Any]]:
        return self.list_servers(mask=True)
