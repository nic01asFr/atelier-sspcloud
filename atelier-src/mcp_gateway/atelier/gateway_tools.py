"""Outils exposés par chaque service du pool, lus dans le cache de la gateway.

Le pool ne publie qu'un compte d'outils (`tools: 51`). Les noms sont pourtant
connus : la gateway les met en cache dans `upstream_tool_cache`. C'est cette
liste qui permet de choisir un outil précis plutôt qu'un service entier.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import Request


def build_tools_by_service(request: Request) -> dict[str, Any]:
    gw = getattr(request.app.state, "gateway_settings", None)
    if gw is None:
        return {"services": [], "note": "gateway indisponible"}

    try:
        conn = sqlite3.connect(f"file:{gw.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        return {"services": [], "note": f"base illisible : {exc}"}

    try:
        rows = conn.execute(
            """SELECT source_key, tool_name, qualified_name, description
               FROM upstream_tool_cache
               ORDER BY source_key, qualified_name COLLATE NOCASE"""
        ).fetchall()
    except sqlite3.Error:
        # Cache jamais alimenté : ce n'est pas une erreur, juste un pool neuf.
        return {"services": []}
    finally:
        conn.close()

    par_source: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        par_source.setdefault(row["source_key"], []).append(
            {
                "name": row["qualified_name"],
                "short": row["tool_name"],
                "description": (row["description"] or "")[:220],
            }
        )

    services = [
        {"key": key, "count": len(tools), "tools": tools}
        for key, tools in sorted(par_source.items())
    ]
    return {"services": services}
