"""Cache SQLite des outils upstream — permet la config profil même source hors ligne."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from mcp_gateway.mcp_fields import upstream_tool_fields


def migrate_tool_cache_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS upstream_tool_cache (
            source_key TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            qualified_name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            schema_json TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (source_key, tool_name)
        )
        """
    )
    conn.commit()


def save_upstream_tools(
    conn: sqlite3.Connection,
    source_key: str,
    prefix: str,
    tools: list[dict[str, Any]],
) -> None:
    migrate_tool_cache_schema(conn)
    conn.execute("DELETE FROM upstream_tool_cache WHERE source_key = ?", (source_key,))
    for tool in tools:
        short = str(tool.get("name", ""))
        if not short:
            continue
        schema = tool.get("inputSchema")
        conn.execute(
            """INSERT INTO upstream_tool_cache
               (source_key, tool_name, qualified_name, description, schema_json, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))""",
            (
                source_key,
                short,
                f"{prefix}__{short}",
                str(tool.get("description") or ""),
                json.dumps(schema, ensure_ascii=False) if schema else None,
            ),
        )
    conn.commit()


def list_cached_tools(
    conn: sqlite3.Connection,
    source_key: str,
    *,
    kind: str = "upstream",
) -> list[dict[str, Any]]:
    migrate_tool_cache_schema(conn)
    rows = conn.execute(
        """SELECT qualified_name, description, schema_json
           FROM upstream_tool_cache WHERE source_key = ?
           ORDER BY qualified_name COLLATE NOCASE""",
        (source_key,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        desc = row["description"] or ""
        item: dict[str, Any] = {
            "name": row["qualified_name"],
            "source": source_key,
            "kind": kind,
            "description": f"[cache] {desc}" if desc else "[cache] source hors ligne",
            "online": False,
            "cached": True,
        }
        if row["schema_json"]:
            try:
                item["inputSchema"] = json.loads(row["schema_json"])
            except json.JSONDecodeError:
                pass
        out.append(item)
    return out


def append_upstream_tools(
    tools: list[dict[str, Any]],
    *,
    conn: sqlite3.Connection | None,
    source_key: str,
    prefix: str,
    kind: str,
    client,
    include_unavailable: bool,
    offline_error: str | None = None,
) -> int:
    """Ajoute les outils live ou en cache. Retourne le nombre d'outils ajoutés."""
    if client and client.tools:
        if conn:
            save_upstream_tools(conn, source_key, prefix, client.tools)
        for tool in client.tools:
            item: dict[str, Any] = {
                "name": f"{prefix}__{tool['name']}",
                "source": source_key,
                "kind": kind,
                "description": tool.get("description") or "",
                "online": True,
            }
            if tool.get("inputSchema"):
                item["inputSchema"] = tool["inputSchema"]
            item.update(upstream_tool_fields(tool))
            tools.append(item)
        return len(client.tools)

    if not include_unavailable:
        return 0

    if conn:
        cached = list_cached_tools(conn, source_key, kind=kind)
        if cached:
            tools.extend(cached)
            return len(cached)

    err = offline_error or (client.error if client else None) or "non connecté"
    tools.append(
        {
            "name": f"{prefix}__unavailable",
            "source": source_key,
            "kind": kind,
            "description": f"[offline] {err}",
            "online": False,
        }
    )
    return 1
