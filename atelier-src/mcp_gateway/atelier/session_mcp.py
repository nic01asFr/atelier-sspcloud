"""État MCP conversation (niveau 3) pour une session."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.mcp_sync import apply_mcp_overlay, compute_binding_merged


def session_mcp_layers(
    settings: AtelierSettings,
    rec: Any,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if rec.kind == "assistant":
        from mcp_gateway.atelier.sessions import _normalize_assistant_cwd

        _normalize_assistant_cwd(settings, rec)
    cwd = Path(rec.cwd)
    binding = compute_binding_merged(settings, kind=rec.kind, cwd=cwd)
    effective = apply_mcp_overlay(binding, rec.mcp_overlay or None)
    return binding, effective


def build_session_mcp_payload(
    settings: AtelierSettings,
    rec: Any,
    upstream: dict[str, str] | None = None,
) -> dict[str, Any]:
    binding, effective = session_mcp_layers(settings, rec)
    upstream = upstream or {}
    connectors: list[dict[str, Any]] = []
    for name in sorted(binding.keys()):
        pool_key = f"registry:{name}"
        health = upstream.get(pool_key) or upstream.get(name) or ""
        connectors.append(
            {
                "id": name,
                "name": name,
                "bound": True,
                "active": name in effective,
                "health": health,
            }
        )
    return {
        "session_id": rec.session_id,
        "kind": rec.kind,
        "binding": sorted(binding.keys()),
        "effective": sorted(effective.keys()),
        "mcp_overlay": dict(rec.mcp_overlay or {}),
        "connectors": connectors,
        "effective_path": str(settings.mcp_effective_dir / f"{rec.session_id}.json"),
    }
