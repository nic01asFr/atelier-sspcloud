from __future__ import annotations

from typing import Any

from mcp_gateway.catalog import Catalog
from mcp_gateway.meta_tools_defs import META_TOOLS

# Ce que le widget affiche vient de `summary`, écrit pour la personne devant
# l'écran ; `description` reste destinée à l'assistant. Une table parallèle
# tenait ce rôle : elle couvrait onze meta-tools sur quatorze et parlait de
# « preset bundle » et de « run composition » à un lecteur humain.
META_TOOL_CATALOG = [
    {
        "name": t["name"],
        "description": t.get("summary") or t.get("description", ""),
    }
    for t in META_TOOLS
]


def meta_tools_for_bundle(catalog: Catalog, bundle_id: str) -> list[dict[str, Any]]:
    bundle = catalog.bundles.get(bundle_id)
    allowed = bundle.meta_tools if bundle else None
    if allowed is None:
        return list(META_TOOL_CATALOG)
    names = set(allowed)
    return [t for t in META_TOOL_CATALOG if t["name"] in names]


def meta_tools_for_profile(catalog: Catalog, profile) -> list[dict[str, Any]]:
    """Meta-tools gateway selon profil org (YAML) ou perso (SQLite)."""
    allowed = profile.meta_tools
    if profile.kind == "org" and allowed is None and profile.bundle_id:
        bundle = catalog.bundles.get(profile.bundle_id)
        allowed = bundle.meta_tools if bundle else None
    if profile.kind == "custom":
        if allowed is None:
            return list(META_TOOL_CATALOG)
        if len(allowed) == 0:
            return []
        names = set(allowed)
        return [t for t in META_TOOL_CATALOG if t["name"] in names]
    if allowed is None:
        return list(META_TOOL_CATALOG)
    if len(allowed) == 0:
        return []
    names = set(allowed)
    return [t for t in META_TOOL_CATALOG if t["name"] in names]


def track_tool_use(conn, tool_name: str, count: int = 1) -> None:
    conn.execute(
        """INSERT INTO tool_pins (tool_name, use_count, pinned, updated_at)
           VALUES (?, ?, 0, datetime('now'))
           ON CONFLICT(tool_name) DO UPDATE SET
             use_count = use_count + excluded.use_count,
             updated_at = datetime('now')""",
        (tool_name, count),
    )
    conn.commit()


def list_usage(conn, limit: int = 10) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT tool_name, use_count, pinned
           FROM tool_pins
           WHERE use_count > 0
           ORDER BY use_count DESC, tool_name
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_pins(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT tool_name, use_count, pinned, updated_at
           FROM tool_pins WHERE pinned = 1
           ORDER BY use_count DESC, tool_name"""
    ).fetchall()
    return [dict(r) for r in rows]


def set_pin(conn, tool_name: str, pinned: bool = True) -> dict[str, Any]:
    conn.execute(
        """INSERT INTO tool_pins (tool_name, use_count, pinned, updated_at)
           VALUES (?, 0, ?, datetime('now'))
           ON CONFLICT(tool_name) DO UPDATE SET
             pinned = excluded.pinned,
             updated_at = datetime('now')""",
        (tool_name, 1 if pinned else 0),
    )
    conn.commit()
    row = conn.execute(
        "SELECT tool_name, use_count, pinned FROM tool_pins WHERE tool_name = ?",
        (tool_name,),
    ).fetchone()
    return dict(row) if row else {"tool_name": tool_name, "pinned": pinned, "use_count": 0}
