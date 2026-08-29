"""Profils gateway — presets org (bundles) et profils perso composables (SQLite)."""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Literal

from mcp_gateway.bundles import BundleSession
from mcp_gateway.catalog import Catalog

from mcp_gateway.registry import list_registry_servers, registry_pool_key
from mcp_gateway.server_enable import filter_enabled_org, is_registry_enabled

_ALLOWLIST_KINDS = frozenset({"upstream", "registry", "composition"})

ProfileKind = Literal["org", "custom"]
WEB_UI_SESSION = "web-ui"
META_KEY_WEB_PROFILE = "web_ui_profile"


@dataclass
class ResolvedProfile:
    kind: ProfileKind
    id: str
    label: str
    description: str
    org_servers: list[str]
    # Consignes destinees au modele, quand elles different de ce qu'on affiche.
    # Un profil personnel n'en a pas : sa description sert aux deux.
    registry_server_ids: list[str]
    bundle_id: str | None
    editable: bool = False
    tool_allowlist: list[str] | None = None
    meta_tools: list[str] | None = None
    mcp_instructions: str = ""
    audience: str = "catalog"  # catalog | advanced | personal


def migrate_user_profiles_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profiles (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            org_servers TEXT NOT NULL DEFAULT '[]',
            registry_servers TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(user_profiles)")}
    if "tool_allowlist" not in cols:
        conn.execute(
            "ALTER TABLE user_profiles ADD COLUMN tool_allowlist TEXT NOT NULL DEFAULT '[]'"
        )
        conn.commit()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(user_profiles)")}
    if "meta_tools" not in cols:
        conn.execute(
            "ALTER TABLE user_profiles ADD COLUMN meta_tools TEXT NOT NULL DEFAULT '[]'"
        )
        conn.commit()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "profil"


def _get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM gateway_meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """INSERT INTO gateway_meta (key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        (key, value),
    )
    conn.commit()


def _parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(x) for x in data]


def _registry_ids_for_org_bundle(
    conn: sqlite3.Connection, catalog: Catalog, bundle_id: str
) -> list[str]:
    """Registre : tout = connecteurs actifs ; bundles métier = allowlist YAML."""
    if bundle_id == "tout":
        return [
            entry.server_id
            for entry in list_registry_servers(conn)
            if is_registry_enabled(conn, entry.server_id)
        ]
    bundle = catalog.bundles.get(bundle_id)
    if bundle and bundle.registry_servers:
        return _registry_ids_allowlist(conn, list(bundle.registry_servers))
    return []


def _registry_ids_allowlist(conn: sqlite3.Connection, allowlist: list[str]) -> list[str]:
    allowed = set(allowlist)
    return [
        entry.server_id
        for entry in list_registry_servers(conn)
        if entry.server_id in allowed and is_registry_enabled(conn, entry.server_id)
    ]


def org_profile_from_bundle(
    conn: sqlite3.Connection, catalog: Catalog, bundle_id: str
) -> ResolvedProfile:
    bundle = catalog.bundles[bundle_id]
    org_servers = filter_enabled_org(conn, list(bundle.servers))
    registry_ids = _registry_ids_for_org_bundle(conn, catalog, bundle_id)
    return ResolvedProfile(
        kind="org",
        id=bundle_id,
        label=bundle.label,
        description=bundle.description,
        mcp_instructions=bundle.mcp_instructions,
        org_servers=org_servers,
        registry_server_ids=registry_ids,
        bundle_id=bundle_id,
        editable=False,
        meta_tools=bundle.meta_tools,
        audience=bundle.audience or "catalog",
    )


def resolve_web_profile(
    conn: sqlite3.Connection, catalog: Catalog, bundles: BundleSession
) -> ResolvedProfile:
    migrate_user_profiles_schema(conn)
    raw = _get_meta(conn, META_KEY_WEB_PROFILE)
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and data.get("kind") == "custom":
            custom = get_custom_profile(conn, catalog, str(data.get("id", "")))
            if custom:
                return custom

    bundle_id = bundles.get(WEB_UI_SESSION)
    if bundle_id not in catalog.bundles:
        bundle_id = catalog.default_bundle
    return org_profile_from_bundle(conn, catalog, bundle_id)


def get_custom_profile(
    conn: sqlite3.Connection, catalog: Catalog, profile_id: str
) -> ResolvedProfile | None:
    migrate_user_profiles_schema(conn)
    row = conn.execute("SELECT * FROM user_profiles WHERE id = ?", (profile_id,)).fetchone()
    if not row:
        return None
    org_servers = filter_enabled_org(
        conn, [s for s in _parse_json_list(row["org_servers"]) if s in catalog.servers]
    )
    registry_ids = _registry_ids_allowlist(conn, _parse_json_list(row["registry_servers"]))
    tool_allowlist = _parse_json_list(row["tool_allowlist"]) if "tool_allowlist" in row.keys() else []
    meta_tools = _parse_json_list(row["meta_tools"]) if "meta_tools" in row.keys() else []
    return ResolvedProfile(
        kind="custom",
        id=row["id"],
        label=row["name"],
        description=row["description"] or "",
        org_servers=org_servers,
        registry_server_ids=registry_ids,
        bundle_id=None,
        editable=True,
        tool_allowlist=tool_allowlist or None,
        meta_tools=meta_tools,
        audience="personal",
    )


def list_org_profiles(conn: sqlite3.Connection, catalog: Catalog) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for bundle in catalog.bundles.values():
        resolved = org_profile_from_bundle(conn, catalog, bundle.id)
        out.append(_profile_to_dict(resolved))
    return out


def list_custom_profiles(conn: sqlite3.Connection, catalog: Catalog) -> list[dict[str, Any]]:
    migrate_user_profiles_schema(conn)
    rows = conn.execute("SELECT id FROM user_profiles ORDER BY name COLLATE NOCASE").fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        profile = get_custom_profile(conn, catalog, row["id"])
        if profile:
            out.append(_profile_to_dict(profile))
    return out


def _profile_to_dict(profile: ResolvedProfile) -> dict[str, Any]:
    return {
        "kind": profile.kind,
        "id": profile.id,
        "label": profile.label,
        "description": profile.description,
        "org_servers": profile.org_servers,
        "registry_servers": profile.registry_server_ids,
        "bundle_id": profile.bundle_id,
        "meta_tools": profile.meta_tools,
        "editable": profile.editable,
        "tool_allowlist": profile.tool_allowlist,
        "audience": profile.audience
        if profile.kind == "org"
        else "personal",
    }


def apply_tool_allowlist(
    profile: ResolvedProfile,
    tools: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Filtre upstream/registry/compositions pour profils perso avec allowlist."""
    allowlist = profile.tool_allowlist
    if profile.kind != "custom" or not allowlist:
        return tools, sources
    allowed = set(allowlist)
    filtered = [
        t
        for t in tools
        if t.get("kind") not in _ALLOWLIST_KINDS or t.get("name") in allowed
    ]
    counts: dict[str, int] = {}
    for t in filtered:
        if t.get("kind") not in _ALLOWLIST_KINDS:
            continue
        src = str(t.get("source", ""))
        counts[src] = counts.get(src, 0) + 1
    for s in sources:
        if s.get("kind") == "meta":
            continue
        s["tools"] = counts.get(s["id"], 0)
    return filtered, sources


def resolve_profile_for_session(
    conn: sqlite3.Connection,
    catalog: Catalog,
    bundles: BundleSession,
    session_id: str | None,
) -> ResolvedProfile:
    """Profil actif pour une session MCP ou le widget (web-ui)."""
    if session_id == WEB_UI_SESSION:
        return resolve_web_profile(conn, catalog, bundles)
    bundle_id = bundles.get(session_id)
    return org_profile_from_bundle(conn, catalog, bundle_id)


def profile_defaults(catalog: Catalog) -> dict[str, str]:
    return {
        "web_bundle": catalog.default_bundle,
        "mcp_bundle": catalog.mcp_default_bundle,
    }


def profiles_payload(
    conn: sqlite3.Connection, catalog: Catalog, bundles: BundleSession
) -> dict[str, Any]:
    active = resolve_web_profile(conn, catalog, bundles)
    return {
        "active": _profile_to_dict(active),
        "active_bundle": active.bundle_id or active.id,
        "defaults": profile_defaults(catalog),
        "org": list_org_profiles(conn, catalog),
        "custom": list_custom_profiles(conn, catalog),
    }


def activate_org_profile(
    conn: sqlite3.Connection, bundles: BundleSession, catalog: Catalog, bundle_id: str
) -> ResolvedProfile:
    if bundle_id not in catalog.bundles:
        raise KeyError(f"Profil org inconnu: {bundle_id}")
    bundles.set(WEB_UI_SESSION, bundle_id)
    _set_meta(conn, META_KEY_WEB_PROFILE, json.dumps({"kind": "org", "id": bundle_id}))
    return org_profile_from_bundle(conn, catalog, bundle_id)


def activate_custom_profile(
    conn: sqlite3.Connection, catalog: Catalog, profile_id: str
) -> ResolvedProfile:
    profile = get_custom_profile(conn, catalog, profile_id)
    if not profile:
        raise KeyError(f"Profil perso introuvable: {profile_id}")
    _set_meta(conn, META_KEY_WEB_PROFILE, json.dumps({"kind": "custom", "id": profile_id}))
    return profile


def create_custom_profile(
    conn: sqlite3.Connection,
    catalog: Catalog,
    *,
    profile_id: str | None,
    name: str,
    description: str = "",
    org_servers: list[str] | None = None,
    registry_servers: list[str] | None = None,
    tool_allowlist: list[str] | None = None,
    meta_tools: list[str] | None = None,
) -> ResolvedProfile:
    migrate_user_profiles_schema(conn)
    pid = _slug(profile_id or name)
    if pid in catalog.bundles:
        raise ValueError(f"Identifiant '{pid}' réservé (profil org)")
    if conn.execute("SELECT 1 FROM user_profiles WHERE id = ?", (pid,)).fetchone():
        raise ValueError(f"Profil '{pid}' existe déjà")

    org = [s for s in (org_servers or []) if s in catalog.servers]
    reg = list(registry_servers or [])
    tools = [] if tool_allowlist is None else list(tool_allowlist)
    meta = [] if meta_tools is None else list(meta_tools)
    conn.execute(
        """INSERT INTO user_profiles (id, name, description, org_servers, registry_servers, tool_allowlist, meta_tools)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            pid,
            name.strip(),
            description.strip(),
            json.dumps(org, ensure_ascii=False),
            json.dumps(reg, ensure_ascii=False),
            json.dumps(tools, ensure_ascii=False),
            json.dumps(meta, ensure_ascii=False),
        ),
    )
    conn.commit()
    profile = get_custom_profile(conn, catalog, pid)
    assert profile is not None
    return profile


def update_custom_profile(
    conn: sqlite3.Connection,
    catalog: Catalog,
    profile_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    org_servers: list[str] | None = None,
    registry_servers: list[str] | None = None,
    tool_allowlist: list[str] | None = None,
    meta_tools: list[str] | None = None,
) -> ResolvedProfile:
    migrate_user_profiles_schema(conn)
    row = conn.execute("SELECT * FROM user_profiles WHERE id = ?", (profile_id,)).fetchone()
    if not row:
        raise KeyError(f"Profil perso introuvable: {profile_id}")

    new_name = name.strip() if name is not None else row["name"]
    new_desc = description.strip() if description is not None else row["description"]
    org = (
        [s for s in org_servers if s in catalog.servers]
        if org_servers is not None
        else _parse_json_list(row["org_servers"])
    )
    reg = registry_servers if registry_servers is not None else _parse_json_list(row["registry_servers"])
    tools = (
        list(tool_allowlist)
        if tool_allowlist is not None
        else (_parse_json_list(row["tool_allowlist"]) if "tool_allowlist" in row.keys() else [])
    )
    meta = (
        list(meta_tools)
        if meta_tools is not None
        else (_parse_json_list(row["meta_tools"]) if "meta_tools" in row.keys() else [])
    )
    conn.execute(
        """UPDATE user_profiles SET name = ?, description = ?, org_servers = ?, registry_servers = ?,
           tool_allowlist = ?, meta_tools = ?, updated_at = datetime('now') WHERE id = ?""",
        (
            new_name,
            new_desc,
            json.dumps(org, ensure_ascii=False),
            json.dumps(reg, ensure_ascii=False),
            json.dumps(tools, ensure_ascii=False),
            json.dumps(meta, ensure_ascii=False),
            profile_id,
        ),
    )
    conn.commit()
    profile = get_custom_profile(conn, catalog, profile_id)
    assert profile is not None
    return profile


def delete_custom_profile(conn: sqlite3.Connection, profile_id: str) -> bool:
    migrate_user_profiles_schema(conn)
    cur = conn.execute("DELETE FROM user_profiles WHERE id = ?", (profile_id,))
    conn.commit()
    if cur.rowcount and _get_meta(conn, META_KEY_WEB_PROFILE):
        try:
            data = json.loads(_get_meta(conn, META_KEY_WEB_PROFILE) or "")
            if data.get("kind") == "custom" and data.get("id") == profile_id:
                conn.execute("DELETE FROM gateway_meta WHERE key = ?", (META_KEY_WEB_PROFILE,))
                conn.commit()
        except json.JSONDecodeError:
            pass
    return cur.rowcount > 0


def registry_pool_keys_for_profile(
    conn: sqlite3.Connection, profile: ResolvedProfile
) -> list[tuple[str, str]]:
    """Retourne [(pool_key, prefix), ...] pour les serveurs registre du profil."""
    keys: list[tuple[str, str]] = []
    allowed = set(profile.registry_server_ids)
    for entry in list_registry_servers(conn):
        if entry.server_id not in allowed:
            continue
        if not is_registry_enabled(conn, entry.server_id):
            continue
        keys.append((registry_pool_key(entry.server_id), entry.prefix))
    return keys
