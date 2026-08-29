"""Outils disponibles dans l'Atelier, regroupés par service.

Trois familles cohabitent, et elles ne sont pas de même nature :

- **Pilotage** — les méta-outils de la passerelle. `gateway_find_tools` et
  `gateway_call_tool` suffisent en principe à atteindre tout le reste : c'est
  le canal universel, pas un connecteur métier.
- **Compositions** — ce qui a été fabriqué ici : assemblages et variantes
  d'outils aux paramètres figés, une fois promus en production.
- **Services du pool** — les connecteurs déclarés (wikichat, filesystem…),
  dont les outils sont mis en cache par la passerelle.

Le pool ne publie qu'un compte d'outils ; les noms viennent du cache
(`upstream_tool_cache`), et les deux premières familles des définitions
gateway. Sans cette agrégation, une variante fabriquée resterait invisible
au moment de composer la sélection d'un agent.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import Request

GROUPE_PILOTAGE = "Pilotage"
GROUPE_COMPOSITIONS = "Compositions"
GROUPE_POOL = "Mes connecteurs"


def _outils_pilotage() -> list[dict[str, str]]:
    from mcp_gateway.meta_tools_defs import META_TOOLS

    return [
        {
            "name": t["name"],
            "short": t["name"].replace("gateway_", ""),
            "description": t.get("summary") or t.get("description") or "",
        }
        for t in META_TOOLS
    ]


def _outils_compositions(request: Request) -> list[dict[str, str]]:
    svc = getattr(request.app.state, "compositions", None)
    if svc is None:
        return []
    try:
        promus = svc.promoted_tools()
    except Exception:  # noqa: BLE001 — une composition cassée ne doit rien bloquer
        return []
    return [
        {
            "name": t["name"],
            "short": t["name"].replace("composition_", ""),
            "description": t.get("description") or "",
        }
        for t in promus
    ]


def _outils_du_pool(db_path: str) -> dict[str, list[dict[str, str]]]:
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return {}
    try:
        rows = conn.execute(
            """SELECT source_key, tool_name, qualified_name, description
               FROM upstream_tool_cache
               ORDER BY source_key, qualified_name COLLATE NOCASE"""
        ).fetchall()
    except sqlite3.Error:
        return {}
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
    return par_source


def build_tools_by_service(request: Request) -> dict[str, Any]:
    gw = getattr(request.app.state, "gateway_settings", None)
    if gw is None:
        return {"services": [], "note": "passerelle indisponible"}

    services: list[dict[str, Any]] = []

    pilotage = _outils_pilotage()
    if pilotage:
        services.append(
            {
                "key": "meta:gateway",
                "label": "Pilotage de la passerelle",
                "group": GROUPE_PILOTAGE,
                "count": len(pilotage),
                "tools": pilotage,
            }
        )

    compositions = _outils_compositions(request)
    if compositions:
        services.append(
            {
                "key": "meta:compositions",
                "label": "Compositions et variantes",
                "group": GROUPE_COMPOSITIONS,
                "count": len(compositions),
                "tools": compositions,
            }
        )

    for key, tools in sorted(_outils_du_pool(str(gw.db_path)).items()):
        services.append(
            {
                "key": key,
                "label": key.replace("registry:", ""),
                "group": GROUPE_POOL,
                "count": len(tools),
                "tools": tools,
            }
        )

    return {"services": services}


def tool_schema(request: Request, qualified_name: str) -> dict[str, Any]:
    """Schéma d'entrée d'un outil, pour proposer ses paramètres à figer."""
    gw = getattr(request.app.state, "gateway_settings", None)
    if gw is None:
        return {}
    try:
        conn = sqlite3.connect(f"file:{gw.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return {}
    try:
        row = conn.execute(
            """SELECT source_key, tool_name, qualified_name, description, schema_json
               FROM upstream_tool_cache WHERE qualified_name = ? LIMIT 1""",
            (qualified_name,),
        ).fetchone()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    if not row:
        return {}
    schema: dict[str, Any] = {}
    if row["schema_json"]:
        try:
            schema = json.loads(row["schema_json"])
        except json.JSONDecodeError:
            schema = {}
    return {
        "name": row["qualified_name"],
        "short": row["tool_name"],
        "source": row["source_key"],
        "description": row["description"] or "",
        "schema": schema,
    }
