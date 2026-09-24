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

from mcp_gateway.atelier.enrichissements import (
    appliquer_a_outil,
    appliquer_a_service as appliquer_enrichissement,
    charger as charger_enrichissement,
    familles_declarees,
)

GROUPE_ACCES = "Accès aux outils"
GROUPE_COMPOSITIONS = "Compositions"
GROUPE_COORDINATION = "Coordination et mémoire"
GROUPE_FICHIERS = "Accès aux fichiers"
GROUPE_NAVIGATEUR = "Navigateur web"
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


def _est_le_navigateur(config: dict[str, Any], nom: str = "") -> bool:
    """Vrai si ce service est le navigateur intégré à l'Atelier.

    Une seule règle pour toute la maison (`navigateur.est_le_navigateur`) :
    l'identifiant du service que l'Atelier déclare. Un connecteur tiers dont
    l'adresse contient « chrome-devtools » reste un connecteur tiers.
    """
    from mcp_gateway.atelier.navigateur import est_le_navigateur

    return est_le_navigateur(nom, config)


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


def nature_service(
    config: dict[str, Any], wikichat_url: str, *, nom: str = ""
) -> dict[str, Any]:
    """Ce qu'est un service, indépendamment de l'écran qui le regarde.

    Deux services n'ont pas le même statut. Le pilote et un serveur de
    fichiers sont l'infrastructure de l'Atelier : un agent en dispose du seul
    fait d'exister, comme il dispose de son dossier de travail. Les autres
    sont des branchements qu'on a faits et qu'on peut défaire — ce sont
    ceux-là, et eux seuls, qu'on propose de cocher.
    """
    if nom == "atelier":
        # La maison elle-même : elle porte la recherche d'outils et les
        # compositions, et ne se retire pas comme un connecteur qu'on aurait
        # branché.
        return {"group": GROUPE_ACCES, "system": True, "scope": []}
    if _est_le_navigateur(config, nom):
        return {"group": GROUPE_NAVIGATEUR, "system": True, "scope": []}
    if _est_le_pilote(config, wikichat_url):
        return {"group": GROUPE_COORDINATION, "system": True, "scope": []}
    repertoires = _repertoires_autorises(config)
    if repertoires:
        return {"group": GROUPE_FICHIERS, "system": True, "scope": repertoires}
    return {"group": GROUPE_POOL, "system": False, "scope": []}


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

    # Le service distingue déjà une variante d'un enchaînement, et connaît
    # son outil d'origine : on s'appuie dessus plutôt que de le redéduire.
    meta: dict[str, dict] = {}
    try:
        for comp in svc.list_compositions("production"):
            meta[comp.get("tool_name", "")] = comp
    except Exception:  # noqa: BLE001
        pass

    sortie = []
    for t in promus:
        nom = t["name"]
        court = nom.replace("composition_", "")
        entree = {
            "name": nom,
            "short": court,
            "description": t.get("description") or "",
        }
        info = meta.get(nom) or {}
        if info.get("variant"):
            base = str(info.get("source_tool") or "").split("__")[-1]
            entree["label"] = f"{court} — variante de {base}" if base else court
        sortie.append(entree)
    return sortie


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
    # Les projets de l'Atelier sont ceux du coordinateur : ils y sont
    # déclarés à leur création. Ces outils portent donc sur les mêmes
    # dossiers que la page Code, et non sur un registre parallèle.
    "Suivi de projet": (
        "declare_project", "list_projects", "set_project_meta",
        "add_project_note", "audit_project", "list_project_agents",
    ),
    "Tâches et idées": (
        "claim_task", "release_task", "add_idea", "get_idea", "list_ideas",
        "update_idea",
    ),
    # Un agent peut en piloter d'autres : c'est un usage légitime, mais
    # « créer » et « supprimer » ne doivent pas se cocher du même geste.
    "Piloter des agents": (
        "register_trigger", "set_trigger_enabled", "fire_trigger", "list_triggers",
        "spawn_session", "list_spawned", "poll_ticket", "respawn_project_agents",
    ),
    "Arrêter et supprimer": ("delete_trigger", "kill_spawn", "purge_registry"),
    "Automatisations": (
        "register_routine", "run_routine", "list_routines", "delete_routine",
    ),
    # Le savoir transverse ne se produit pas tout seul : recensement,
    # cartographie, regroupement, audit d'ensemble, capitalisation à la
    # clôture. Ce sont des passes de fond, longues et rarement déclenchées à
    # la main — leur place est chez un agent d'entretien, pas au milieu d'un
    # échange.
    "Entretien du savoir": (
        "scan_projects", "run_cartography", "run_clustering",
        "audit_all_projects", "harmonize_ideas", "close_project",
    ),
}

FAMILLE_PAR_OUTIL: dict[str, str] = {
    outil: famille for famille, outils in FAMILLES_COORDINATION.items() for outil in outils
}

# Libellés en langage Atelier. Le nom technique reste affiché en second :
# c'est lui que l'agent recevra dans --allowedTools, le renommer ici ne
# change que ce qu'on lit au moment de choisir.
LIBELLES_OUTILS: dict[str, str] = {
    "register_trigger": "Créer un agent",
    "delete_trigger": "Supprimer un agent",
    "set_trigger_enabled": "Activer ou désactiver un agent",
    "fire_trigger": "Lancer un agent maintenant",
    "list_triggers": "Lister les agents",
    "spawn_session": "Lancer une session ponctuelle",
    "list_spawned": "Lister les sessions lancées",
    "kill_spawn": "Arrêter une session lancée",
    "poll_ticket": "Suivre une session lancée",
    "respawn_project_agents": "Relancer les agents d’un projet",
    "purge_registry": "Purger le registre des projets",
    "close_project": "Clôturer un projet",
    "scan_projects": "Recenser les projets de la machine",
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
        court = row["tool_name"]
        entree = {
            "name": row["qualified_name"],
            "short": court,
            "description": (row["description"] or "")[:220],
        }
        libelle = LIBELLES_OUTILS.get(court)
        if libelle:
            entree["label"] = libelle
        par_source.setdefault(row["source_key"], []).append(entree)
    return par_source


def build_tools_by_service(request: Request) -> dict[str, Any]:
    gw = getattr(request.app.state, "gateway_settings", None)
    if gw is None:
        return {"services": [], "note": "passerelle indisponible"}
    settings_atelier = getattr(request.app.state, "settings", None)

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

    # Gérer les compositions et s'en servir sont deux choses : « lancer une
    # composition » est un outil de pilotage, une composition promue est un
    # outil à part entière.
    gestion = _meta(OUTILS_COMPOSITION)
    if gestion:
        services.append(
            {
                "key": "meta:gestion-compositions",
                "label": "Gérer les compositions",
                "group": GROUPE_COMPOSITIONS,
                "count": len(gestion),
                "tools": gestion,
            }
        )

    disponibles = _outils_compositions(request)
    if disponibles:
        services.append(
            {
                "key": "meta:compositions",
                "label": "Compositions disponibles",
                "group": GROUPE_COMPOSITIONS,
                "count": len(disponibles),
                "tools": disponibles,
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
            #
            # Ses familles sont écrites à la main — le coordinateur est trop
            # central pour dépendre d'une description automatique. Le reste
            # de l'enrichissement s'applique quand même : sans cela, décrire
            # ce service produirait un fichier que rien ne lirait.
            enrichi_pilote = (
                charger_enrichissement(settings_atelier, key.replace("registry:", ""))
                if settings_atelier
                else {}
            )
            tools = [appliquer_a_outil(t, enrichi_pilote) for t in tools]
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
        nom = key.replace("registry:", "")
        if _est_le_navigateur(config, nom):
            groupe = GROUPE_NAVIGATEUR
            libelle = "Navigateur web"
        elif chemins:
            # Un service de fichiers est seul de sa famille : répéter son nom
            # technique sous l'intitulé du groupe n'apprend rien. Ce qui
            # compte, c'est jusqu'où il ouvre.
            groupe = GROUPE_FICHIERS
            libelle = "Lire et écrire des fichiers"
        else:
            groupe = GROUPE_POOL
            libelle = nom

        # Ce que l'Atelier a appris de ce connecteur : libellés lisibles,
        # regroupements, hints. Écrit dans un fichier à part, jamais ici —
        # les règles en dur ne valaient que pour le coordinateur.
        enrichi = charger_enrichissement(settings_atelier, nom) if settings_atelier else {}
        familles_sup = familles_declarees(enrichi)
        if familles_sup:
            par_famille: dict[str, list[dict[str, str]]] = {}
            appartenance = {
                o: f for f, outils in familles_sup.items() for o in outils
            }
            for outil in tools:
                famille = appartenance.get(outil["short"]) or appartenance.get(
                    outil["name"]
                ) or "Autres outils"
                par_famille.setdefault(famille, []).append(outil)
            for famille in list(familles_sup) + ["Autres outils"]:
                lot = par_famille.get(famille)
                if not lot:
                    continue
                services.append(
                    appliquer_enrichissement(
                        {
                            "key": f"{key}#{famille}",
                            "label": famille,
                            "group": groupe,
                            "scope": chemins,
                            "count": len(lot),
                            "tools": lot,
                        },
                        enrichi,
                    )
                    | {"label": famille}
                )
            continue

        services.append(
            appliquer_enrichissement(
            {
                "key": key,
                "label": libelle,
                "group": groupe,
                "scope": chemins,
                "count": len(tools),
                "tools": tools,
            },
            enrichi,
            )
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
    # Ce que la description du connecteur a appris de cet outil : un libellé,
    # une phrase, et surtout un mot par paramètre. Sans eux, un formulaire ne
    # peut afficher que le nom brut du champ.
    settings_atelier = getattr(request.app.state, "settings", None)
    service = str(row["source_key"] or "").replace("registry:", "")
    enrichi = charger_enrichissement(settings_atelier, service) if settings_atelier else {}
    info = (enrichi.get("outils") or {}).get(row["qualified_name"]) or {}
    return {
        "name": row["qualified_name"],
        "short": row["tool_name"],
        "source": row["source_key"],
        "description": row["description"] or "",
        "label": info.get("libelle") or "",
        "resume": info.get("resume") or "",
        "risque": info.get("risque") or "",
        "hints": info.get("parametres") or {},
        "schema": schema,
    }
