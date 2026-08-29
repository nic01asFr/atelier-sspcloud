"""Registre MCP du compte Atelier — source de vérité PVC."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
_SECRET_KEYS = frozenset(
    {
        "authorization",
        "api_key",
        "apikey",
        "token",
        "password",
        "secret",
        "access_token",
        "anthropic_api_key",
    }
)


def _is_secret_key(key: str) -> bool:
    k = key.lower().replace("-", "_")
    if k in _SECRET_KEYS:
        return True
    return any(s in k for s in ("token", "secret", "password", "api_key", "authorization"))


def mask_server_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Copie d'une entrée avec secrets masqués (API GET)."""
    out = deepcopy(entry)
    env = out.get("env")
    if isinstance(env, dict):
        out["env"] = {
            k: ("***" if _is_secret_key(k) and v else v) for k, v in env.items()
        }
    headers = out.get("headers")
    if isinstance(headers, dict):
        out["headers"] = {
            k: ("***" if _is_secret_key(k) and v else v) for k, v in headers.items()
        }
    return out


def validate_server_name(name: str) -> str:
    if not _NAME_RE.match(name):
        raise ValueError(
            f"invalid server name {name!r}: use [a-zA-Z0-9][a-zA-Z0-9_.-]{{0,63}}"
        )
    return name


def _normalize_entry(raw: dict[str, Any], *, default_enabled: bool = True) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("server entry must be an object")
    entry = deepcopy(raw)
    enabled = entry.pop("enabled", default_enabled)
    if not isinstance(enabled, bool):
        enabled = bool(enabled)
    entry["enabled"] = enabled

    has_cmd = "command" in entry
    has_url = "url" in entry
    if has_cmd and has_url:
        raise ValueError("entry cannot have both command and url")
    if not has_cmd and not has_url:
        raise ValueError("entry needs command (stdio) or url (http)")
    if has_cmd:
        if not isinstance(entry["command"], str) or not entry["command"].strip():
            raise ValueError("command must be a non-empty string")
        args = entry.get("args", [])
        if args is None:
            entry["args"] = []
        elif not isinstance(args, list):
            raise ValueError("args must be a list")
        env = entry.get("env")
        if env is not None and not isinstance(env, dict):
            raise ValueError("env must be an object")
    if has_url:
        if not isinstance(entry["url"], str) or not entry["url"].strip():
            raise ValueError("url must be a non-empty string")
        if "type" not in entry:
            entry["type"] = "http"
        headers = entry.get("headers")
        if headers is not None and not isinstance(headers, dict):
            raise ValueError("headers must be an object")
    return entry


def claude_shape(entry: dict[str, Any]) -> dict[str, Any]:
    """Entrée sans `enabled`, forme attendue par Claude mcpServers."""
    out = {k: v for k, v in entry.items() if k != "enabled"}
    return out


class McpRegistry:
    """Registre JSON versionné sur le PVC du compte."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"version": 1, "servers": {}}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("registry root must be an object")
        servers = data.get("servers")
        if servers is None:
            servers = {}
        if not isinstance(servers, dict):
            raise ValueError("servers must be an object")
        return {"version": int(data.get("version", 1)), "servers": servers}

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": int(data.get("version", 1)), "servers": data.get("servers", {})}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def list_servers(self, *, mask: bool = False) -> dict[str, dict[str, Any]]:
        servers = self.load()["servers"]
        if not mask:
            return {k: deepcopy(v) for k, v in servers.items()}
        return {k: mask_server_entry(v) for k, v in servers.items()}

    def get(self, name: str) -> dict[str, Any] | None:
        return deepcopy(self.load()["servers"].get(name))

    def upsert(self, name: str, raw: dict[str, Any]) -> dict[str, Any]:
        name = validate_server_name(name)
        entry = _normalize_entry(raw)
        data = self.load()
        data["servers"][name] = entry
        self.save(data)
        return deepcopy(entry)

    def set_enabled(self, name: str, enabled: bool) -> dict[str, Any]:
        name = validate_server_name(name)
        data = self.load()
        if name not in data["servers"]:
            raise KeyError(name)
        data["servers"][name]["enabled"] = bool(enabled)
        self.save(data)
        return deepcopy(data["servers"][name])

    def delete(self, name: str) -> None:
        name = validate_server_name(name)
        data = self.load()
        if name not in data["servers"]:
            raise KeyError(name)
        del data["servers"][name]
        self.save(data)

    def import_mcp_servers(
        self,
        mcp_servers: dict[str, Any],
        *,
        default_enabled: bool = True,
        replace: bool = False,
    ) -> list[str]:
        if not isinstance(mcp_servers, dict):
            raise ValueError("mcpServers must be an object")
        data = self.load() if not replace else {"version": 1, "servers": {}}
        imported: list[str] = []
        for name, raw in mcp_servers.items():
            validate_server_name(name)
            if not isinstance(raw, dict):
                raise ValueError(f"server {name!r} must be an object")
            data["servers"][name] = _normalize_entry(raw, default_enabled=default_enabled)
            imported.append(name)
        self.save(data)
        return imported

    def enabled_mcp_servers(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for name, entry in self.load()["servers"].items():
            if entry.get("enabled", True):
                out[name] = claude_shape(entry)
        return out
