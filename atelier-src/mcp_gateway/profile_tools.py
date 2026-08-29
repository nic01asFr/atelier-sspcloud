"""Helpers meta-tools profils (list / get / use) — partagés MCP et API."""
from __future__ import annotations

import sqlite3
import uuid
from typing import Any, Literal

from mcp_gateway.bundles import BundleSession, PlafondDepasse
from mcp_gateway.catalog import Catalog
from mcp_gateway.compositions import CompositionService
from mcp_gateway.mcp.instructions import build_mcp_instructions
from mcp_gateway.profiles import (
    WEB_UI_SESSION,
    _profile_to_dict,
    activate_custom_profile,
    activate_org_profile,
    create_custom_profile,
    get_custom_profile,
    org_profile_from_bundle,
    profiles_payload,
    resolve_web_profile,
    update_custom_profile,
)

ProfileKindArg = Literal["org", "custom"]


def _summarize_profile(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": entry["kind"],
        "id": entry["id"],
        "label": entry["label"],
        "description": entry.get("description") or "",
        "org_servers": entry.get("org_servers") or [],
        "registry_servers": entry.get("registry_servers") or [],
        "audience": entry.get("audience")
        or ("personal" if entry.get("kind") == "custom" else "catalog"),
    }


def list_profiles_mcp(
    conn: sqlite3.Connection, catalog: Catalog, bundles: BundleSession
) -> dict[str, Any]:
    payload = profiles_payload(conn, catalog, bundles)
    return {
        "active": payload["active"],
        "defaults": payload["defaults"],
        "org": [_summarize_profile(p) for p in payload["org"]],
        "custom": [_summarize_profile(p) for p in payload["custom"]],
    }


def _resolve_profile_by_ref(
    conn: sqlite3.Connection,
    catalog: Catalog,
    bundles: BundleSession,
    *,
    kind: ProfileKindArg | None = None,
    profile_id: str | None = None,
):
    if kind and profile_id:
        if kind == "org":
            if profile_id not in catalog.bundles:
                raise KeyError(f"Profil org inconnu: {profile_id}")
            return org_profile_from_bundle(conn, catalog, profile_id)
        profile = get_custom_profile(conn, catalog, profile_id)
        if not profile:
            raise KeyError(f"Profil perso introuvable: {profile_id}")
        return profile
    return resolve_web_profile(conn, catalog, bundles)


def get_profile_mcp(
    conn: sqlite3.Connection,
    catalog: Catalog,
    bundles: BundleSession,
    compositions: CompositionService | None,
    *,
    kind: ProfileKindArg | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    profile = _resolve_profile_by_ref(
        conn, catalog, bundles, kind=kind, profile_id=profile_id
    )
    prod = compositions.list_compositions(status="production") if compositions else []
    instructions = build_mcp_instructions(profile, prod)
    detail = _profile_to_dict(profile)
    detail["instructions"] = instructions
    detail["production_compositions"] = [
        {
            "tool_name": c.get("tool_name") or f"composition_{c.get('name', '')}",
            "name": c.get("name"),
            "description": c.get("description") or "",
            "variant": bool(c.get("variant")),
        }
        for c in prod
    ]
    return detail


def _refuser_si_trop_large(
    bundles: BundleSession,
    *,
    org_servers: list[str] | None,
    registry_servers: list[str] | None,
    meta_tools: list[str] | None,
) -> None:
    """Un profil perso ne doit pas ouvrir ce que les presets MCP n'ouvrent pas.

    Sinon le plafond posé sur `gateway_use_bundle` se contourne en deux appels :
    créer un profil qui nomme tous les serveurs, puis l'activer.
    """
    if not bundles.ouverture_permise(
        serveurs=org_servers, registre=registry_servers, metas=meta_tools
    ):
        raise PlafondDepasse("ce profil perso", bundles.plafond())


def use_profile_mcp(
    conn: sqlite3.Connection,
    catalog: Catalog,
    bundles: BundleSession,
    *,
    kind: ProfileKindArg,
    profile_id: str,
    session_id: str | None,
) -> dict[str, Any]:
    # Sans session, on retombait sur celle du widget : un client MCP réécrivait
    # le profil du propriétaire, et `activate_org_profile` le persistait — le
    # changement lui survivait au redémarrage. On lui donne donc sa propre
    # session. Le cas « Mcp-Session-Id: web-ui » reste possible : il est demandé
    # explicitement, dans le fichier de configuration du propriétaire.
    sid = session_id or uuid.uuid4().hex
    if kind == "org":
        # Même plafond que gateway_use_bundle : sans cela, changer de profil
        # rouvrait l'évasion que la bascule de preset vient de fermer.
        if not bundles.sous_le_plafond(profile_id):
            raise PlafondDepasse(profile_id, bundles.plafond())
        if sid == WEB_UI_SESSION:
            profile = activate_org_profile(conn, bundles, catalog, profile_id)
        else:
            profile = org_profile_from_bundle(conn, catalog, profile_id)
        bundles.set(sid, profile.bundle_id or profile_id)
    elif kind == "custom":
        if sid != WEB_UI_SESSION:
            # Un profil perso créé depuis l'interface peut ouvrir davantage que
            # les presets MCP : le propriétaire en a le droit, son assistant non.
            vise = get_custom_profile(conn, catalog, profile_id)
            if vise is not None and not bundles.ouverture_permise(
                serveurs=list(vise.org_servers or ()),
                registre=list(vise.registry_server_ids or ()),
                metas=None if vise.meta_tools is None else list(vise.meta_tools),
            ):
                raise PlafondDepasse(profile_id, bundles.plafond())
        profile = activate_custom_profile(conn, catalog, profile_id)
        if sid != WEB_UI_SESSION:
            bundles.set(sid, catalog.default_bundle)
    else:
        raise ValueError(f"kind invalide : {kind}")

    return {
        "active_profile": {
            "kind": profile.kind,
            "id": profile.id,
            "label": profile.label,
        },
        "active_bundle": profile.bundle_id or profile.id,
        "session_id": sid,
        "note": (
            "Profil perso actif pour le widget (web-ui). "
            "Session MCP sans en-tête Mcp-Session-Id: web-ui : utilisez gateway_use_bundle "
            "ou reconnectez MCP avec web-ui pour aligner tools/list."
            if kind == "custom" and sid != WEB_UI_SESSION
            else ""
        ),
    }


def create_profile_mcp(
    conn: sqlite3.Connection,
    catalog: Catalog,
    bundles: BundleSession,
    *,
    name: str,
    profile_id: str | None = None,
    description: str = "",
    org_servers: list[str] | None = None,
    registry_servers: list[str] | None = None,
    tool_allowlist: list[str] | None = None,
    meta_tools: list[str] | None = None,
    activate: bool = False,
    session_id: str | None = None,
) -> dict[str, Any]:
    if not (name or "").strip():
        raise ValueError("Nom requis")
    _refuser_si_trop_large(
        bundles,
        org_servers=org_servers or [],
        registry_servers=registry_servers or [],
        meta_tools=meta_tools or [],
    )
    profile = create_custom_profile(
        conn,
        catalog,
        profile_id=profile_id,
        name=name,
        description=description or "",
        org_servers=org_servers,
        registry_servers=registry_servers,
        tool_allowlist=tool_allowlist,
        meta_tools=meta_tools,
    )
    result: dict[str, Any] = {
        "created": {
            "kind": "custom",
            "id": profile.id,
            "label": profile.label,
        }
    }
    if activate:
        result.update(
            use_profile_mcp(
                conn,
                catalog,
                bundles,
                kind="custom",
                profile_id=profile.id,
                session_id=session_id,
            )
        )
    return result


def update_profile_mcp(
    conn: sqlite3.Connection,
    catalog: Catalog,
    bundles: BundleSession,
    *,
    profile_id: str,
    name: str | None = None,
    description: str | None = None,
    org_servers: list[str] | None = None,
    registry_servers: list[str] | None = None,
    tool_allowlist: list[str] | None = None,
    meta_tools: list[str] | None = None,
    activate: bool = False,
    session_id: str | None = None,
) -> dict[str, Any]:
    if not profile_id:
        raise ValueError("id requis")
    actuel = get_custom_profile(conn, catalog, profile_id)
    _refuser_si_trop_large(
        bundles,
        org_servers=(
            org_servers
            if org_servers is not None
            else list(actuel.org_servers or ()) if actuel else []
        ),
        registry_servers=(
            registry_servers
            if registry_servers is not None
            else list(actuel.registry_server_ids or ()) if actuel else []
        ),
        meta_tools=(
            meta_tools
            if meta_tools is not None
            else list(actuel.meta_tools or ()) if actuel else []
        ),
    )
    profile = update_custom_profile(
        conn,
        catalog,
        profile_id,
        name=name,
        description=description,
        org_servers=org_servers,
        registry_servers=registry_servers,
        tool_allowlist=tool_allowlist,
        meta_tools=meta_tools,
    )
    result: dict[str, Any] = {
        "updated": {
            "kind": "custom",
            "id": profile.id,
            "label": profile.label,
        }
    }
    if activate:
        result.update(
            use_profile_mcp(
                conn,
                catalog,
                bundles,
                kind="custom",
                profile_id=profile.id,
                session_id=session_id,
            )
        )
    return result


__all__ = [
    "create_profile_mcp",
    "get_profile_mcp",
    "list_profiles_mcp",
    "update_profile_mcp",
    "use_profile_mcp",
]
