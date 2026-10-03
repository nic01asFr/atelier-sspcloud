"""État MCP conversation (niveau 3) pour une session."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.gateway_tools import nature_service
from mcp_gateway.atelier.mcp_sync import compute_binding_merged


def session_mcp_layers(
    settings: AtelierSettings,
    rec: Any,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if rec.kind == "assistant":
        from mcp_gateway.atelier.sessions import _normalize_assistant_cwd

        _normalize_assistant_cwd(settings, rec)
    cwd = Path(rec.cwd)
    binding = compute_binding_merged(settings, kind=rec.kind, cwd=cwd)
    # La sélection est celle du projet (ou du dossier de l'Assistant), la même
    # sur toutes les surfaces : plus de désactivation propre à la conversation.
    effective = dict(binding)
    return binding, effective


def _lignes_des_connecteurs(
    settings: AtelierSettings,
    binding: dict[str, dict[str, Any]],
    effective: dict[str, dict[str, Any]],
    upstream: dict[str, str],
) -> list[dict[str, Any]]:
    connectors: list[dict[str, Any]] = []
    for name in sorted(binding.keys()):
        pool_key = f"registry:{name}"
        health = upstream.get(pool_key) or upstream.get(name) or ""
        config = binding.get(name)
        nature = nature_service(
            config if isinstance(config, dict) else {},
            settings.wikichat_url,
            nom=name,
        )
        connectors.append(
            {
                "id": name,
                "name": name,
                "bound": True,
                "active": name in effective,
                "health": health,
                "group": nature["group"],
                "system": nature["system"],
                "scope": nature["scope"],
            }
        )
    return connectors


def build_session_mcp_payload(
    settings: AtelierSettings,
    rec: Any,
    upstream: dict[str, str] | None = None,
) -> dict[str, Any]:
    binding, effective = session_mcp_layers(settings, rec)
    connectors = _lignes_des_connecteurs(settings, binding, effective, upstream or {})
    return {
        "session_id": rec.session_id,
        "kind": rec.kind,
        "binding": sorted(binding.keys()),
        "effective": sorted(effective.keys()),
        "mcp_overlay": dict(rec.mcp_overlay or {}),
        "connectors": connectors,
        "effective_path": str(settings.mcp_effective_dir / f"{rec.session_id}.json"),
    }


def apercu_avant_le_premier_message(
    settings: AtelierSettings,
    kind: str,
    cwd: Path,
    upstream: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Les connecteurs que recevra une conversation qui n'existe pas encore.

    Même liste que `build_session_mcp_payload`, calculée sur le dossier où elle
    naîtra (le projet, ou la racine de l'Assistant), **sans rien créer** : pas de
    dossier de conversation, pas de fiche. Le choix fait avant le premier message
    se pose, lui, quand la conversation naît (`PATCH /v1/sessions/<id>/mcp`).
    """
    binding = compute_binding_merged(settings, kind=kind, cwd=cwd)  # type: ignore[arg-type]
    connectors = _lignes_des_connecteurs(settings, binding, dict(binding), upstream or {})
    return {
        "session_id": "",
        "kind": kind,
        "apercu": True,
        "binding": sorted(binding.keys()),
        "effective": sorted(binding.keys()),
        "mcp_overlay": {},
        "connectors": connectors,
    }
