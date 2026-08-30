"""Outils disponibles dans l'Atelier, regroupés par service.

Trois familles cohabitent, et elles ne sont pas de même nature :

- **Pilotage** — les méta-outils de la passerelle. `gateway_find_tools` et
  `gateway_call_tool` suffisent en principe à atteindre tout le reste : c'est
  le canal universel, pas un connecteur métier.
- **Compositions** — ce qui a été fabriqué ici : assemblages et variantes
  d'outils aux paramètres figés, une fois promus en production.
- **Accès aux fichiers** — les services qui ouvrent des répertoires. Ils ne
  donnent pas une capacité métier mais un droit d'accès : leur question est
  « jusqu'où ouvrent-ils », pas « que savent-ils faire ».
- **Services du pool** — les connecteurs métier déclarés (wikichat…), dont
  les outils sont mis en cache par la passerelle.

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

GROUPE_ACCES = "Accès aux outils"
GROUPE_COMPOSITIONS = "Compositions"
GROUPE_COORDINATION = "Coordination et mémoire"
GROUPE_FICHIERS = "Accès aux fichiers"
GROUPE_POOL = "Mes connecteurs"


def _est_le_pilote(config: dict[str, Any], wikichat_url: str) -> bool:
    """Vrai si ce service est le coordinateur dont dépend l'Atelier.

    Le pilote n'est pas un connecteur qu'on aurait branché parmi d'autres :
    il porte la coordination, la mémoire, et les agents eux-mêmes y sont des
    déclencheurs. On le reconnaît à l'adresse que l'Atelier utilise déjà
    pour lui parler, plutôt qu'à son nom.
    """
    if not wikichat_url:
        return False
    url = str(config.get("url") or "")
    if not url:
        return False
    def racine(u: str) -> str:
        return u.split("://", 1)[-1].split("/", 1)[0]
    return racine(url) == racine(wikichat_url)


def _repertoires_autorises(config: dict[str, Any]) -> list[str]:
    """Répertoires qu'un service ouvre, s'il en déclare.

    Un serveur de fichiers ne donne pas une capacité métier mais un droit
    d'accès : sa question n'est pas « que sait-il faire » mais « jusqu'où
    ouvre-t-il ». On le reconnaît à ses répertoires autorisés plutôt qu'à
    son nom, pour que la règle vaille aussi pour un futur équivalent.
    """
    args = config.get("args")
    if not isinstance(args, list):
        return []
    return [
        a
        for a in args
        if isinstance(a, str) and a.startswith("/") and not a.endswith(".js")
    ]


# Ce qu'un agent peut réellement employer parmi les méta-outils.
#
# Les outils de profils en sont exclus : le périmètre d'un agent est fixé à
# son lancement par --allowedTools, il ne se renégocie pas en cours de route.
# Changer de profil en pleine conversation a du sens pour un client branché
# sur la passerelle, pas pour un agent planifié.
ACCES_OUTILS = ("gateway_find_tools", "gateway_call_tool")
OUTILS_COMPOSITION = (
    "gateway_list_compositions",
    "gateway_save_composition",
    "gateway_run_composition",
    "gateway_composition_run_status",
    "gateway_resume_composition",
)


def _meta(noms: tuple[str, ...]) -> list[dict[str, str]]:
    from mcp_gateway.meta_tools_defs import META_TOOLS

    par_nom = {t["name"]: t for t in META_TOOLS}
    sortie = []
    for nom in noms:
        t = par_nom.get(nom)
        if not t:
            continue
        sortie.append(
            {
                "name": nom,
                "short": nom.replace("gateway_", ""),
                "description": t.get("summary") or t.get("description") or "",
            }
        )
    return sortie


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


# Familles du coordinateur, dans le vocabulaire de l'Atelier.
#
# wikichat n'est pas un connecteur parmi d'autres : il porte la coordination,
# la mémoire et les agents eux-mêmes. Cinquante et une cases côte à côte
# rendent le choix illisible — et surtout, elles mettent sur le même plan
# « écrire une note » et « supprimer un agent ». D'où ce découpage, et
# l'isolement de ce qui engage la plateforme.
FAMILLES_COORDINATION: dict[str, tuple[str, ...]] = {
    "Échanger avec les autres agents": (
        "register", "set_status", "declare_capabilities", "declare_delay",
        "contact_agent", "send_message", "read_messages", "poll",
        "poll_messages", "get_briefing", "list_sessions", "list_channels",
        "create_channel", "share_artifact",
    ),
    "Mémoire et savoir partagé": ("remember", "recall", "forget", "search_knowledge"),
    "Suivi de projet": (
        "declare_project", "list_projects", "set_project_meta",
        "add_project_note", "audit_project", "audit_all_projects",
        "list_project_agents",
    ),
    "Tâches et idées": (
        "claim_task", "release_task", "add_idea", "get_idea", "list_ideas",
        "update_idea", "harmonize_ideas",
    ),
    "Gouvernance de la plateforme": (
        "register_trigger", "delete_trigger", "set_trigger_enabled", "fire_trigger",
        "list_triggers", "register_routine", "run_routine", "list_routines",
        "delete_routine", "spawn_session", "list_spawned", "kill_spawn",
        "poll_ticket", "respawn_project_agents", "close_project",
        "scan_projects", "purge_registry", "run_cartography", "run_clustering",
    ),
}

FAMILLE_PAR_OUTIL: dict[str, str] = {
    outil: famille for famille, outils in FAMILLES_COORDINATION.items() for outil in outils
}


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

    acces = _meta(ACCES_OUTILS)
    if acces:
        services.append(
            {
                "key": "meta:acces",
                "label": "Chercher et appeler un outil",
                "group": GROUPE_ACCES,
                "count": len(acces),
                "tools": acces,
            }
        )

    # Les outils qui pilotent les compositions vont avec ce qu'ils pilotent :
    # un même groupe rassemble ce qui fabrique et ce qui est fabriqué.
    compositions = _meta(OUTILS_COMPOSITION) + _outils_compositions(request)
    if compositions:
        services.append(
            {
                "key": "meta:compositions",
                "label": "Compositions",
                "group": GROUPE_COMPOSITIONS,
                "count": len(compositions),
                "tools": compositions,
            }
        )

    configs: dict[str, dict[str, Any]] = {}
    db = getattr(request.app.state, "db", None)
    if db is not None:
        try:
            from mcp_gateway.registry import list_registry_servers

            configs = {
                f"registry:{e.server_id}": (e.config or {}) for e in list_registry_servers(db)
            }
        except Exception:  # noqa: BLE001 — sans config, on reste sur le groupe par défaut
            configs = {}

    reglages = getattr(request.app.state, "settings", None)
    wikichat_url = getattr(reglages, "wikichat_url", "") if reglages else ""

    for key, tools in sorted(_outils_du_pool(str(gw.db_path)).items()):
        config = configs.get(key, {})
        chemins = _repertoires_autorises(config)
        if _est_le_pilote(config, wikichat_url):
            # Éclaté par famille : le choix reste lisible, et ce qui engage
            # la plateforme ne se coche pas au milieu du reste.
            par_famille: dict[str, list[dict[str, str]]] = {}
            for outil in tools:
                famille = FAMILLE_PAR_OUTIL.get(outil["short"], "Autres outils")
                par_famille.setdefault(famille, []).append(outil)
            for famille in list(FAMILLES_COORDINATION) + ["Autres outils"]:
                lot = par_famille.get(famille)
                if not lot:
                    continue
                services.append(
                    {
                        "key": f"{key}#{famille}",
                        "label": famille,
                        "group": GROUPE_COORDINATION,
                        "scope": [],
                        "count": len(lot),
                        "tools": lot,
                    }
                )
            continue
        if chemins:
            groupe = GROUPE_FICHIERS
        else:
            groupe = GROUPE_POOL
        services.append(
            {
                "key": key,
                "label": key.replace("registry:", ""),
                "group": groupe,
                "scope": chemins,
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
