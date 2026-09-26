from __future__ import annotations

import contextvars
import functools
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from mcp_gateway import __version__
from mcp_gateway.bundles import BundleSession, PlafondDepasse
from mcp_gateway.catalog import Catalog
from mcp_gateway.compositions import CompositionService
from mcp_gateway.meta_tools_defs import META_TOOLS
from mcp_gateway.mcp.instructions import build_mcp_instructions
from mcp_gateway.profile_tools import (
    create_profile_mcp,
    get_profile_mcp,
    list_profiles_mcp,
    update_profile_mcp,
    use_profile_mcp,
)
from mcp_gateway.mcp.tools_registry import ToolsChangeTracker
from mcp_gateway.tool_search import DEFAULT_LIMIT, search_tools
from mcp_gateway.tool_search import (
    looks_like_argument_error,
    suggest_names,
)
from mcp_gateway.tool_search import tool_digest as _tool_digest
from mcp_gateway.tools_hub import list_pins, list_usage
from mcp_gateway.upstream_hints import enrich_upstream_status
from mcp_gateway.profiles import (
    WEB_UI_SESSION,
    registry_pool_keys_for_profile,
    resolve_profile_for_session,
)
from mcp_gateway.tools_exposure import (
    exposed_tool_names,
    resolve_exposed_tools,
    tools_to_mcp_format,
)
from mcp_gateway.upstream.pool import UpstreamPool

MCP_PROTOCOL_VERSION = "2025-06-18"


_log = logging.getLogger("mcp_gateway.mcp.gateway")

# Le méta-outil par lequel passe l'appel en cours, vide pour un appel direct.
# Les outils locaux (le catalogue de commandes de l'Atelier) le lisent pour le
# journal : la classe d'une commande est vérifiée de la même façon par les
# deux chemins, puisque `gateway_call_tool` repasse par `tools_call`.
VIA_META_OUTIL: contextvars.ContextVar[str] = contextvars.ContextVar("via_meta_outil", default="")


def _texte(texte: str, *, erreur: bool | None = None) -> dict:
    """Enveloppe MCP d'un bloc texte.

    `isError` n'est posé que si on le demande : les réponses de succès n'ont
    jamais porté le champ, et l'ajouter partout changerait la charge utile que
    les clients observent déjà.
    """
    reponse: dict[str, Any] = {"content": [{"type": "text", "text": texte}]}
    if erreur is not None:
        reponse["isError"] = erreur
    return reponse


def _json(charge: Any, *, erreur: bool | None = None) -> dict:
    return _texte(json.dumps(charge, ensure_ascii=False), erreur=erreur)


@dataclass(frozen=True)
class _Appel:
    """Ce qu'un gestionnaire reçoit d'un `tools/call`.

    `autorises` vaut None quand le périmètre n'a pas pu être établi — appel
    interne, base absente, service de compositions manquant. Le garde laisse
    alors passer, faute de quoi la passerelle se bloquerait au démarrage.
    """

    nom: str
    arguments: dict[str, Any]
    session_id: str | None
    internal: bool
    profil: Any | None
    autorises: set[str] | None


def _refus_hors_profil(appel: _Appel) -> dict | None:
    if appel.internal or appel.autorises is None or appel.nom in appel.autorises:
        return None
    return _texte(f"Outil non exposé par le profil actif: {appel.nom}", erreur=True)


# Deux tables, parce qu'un nom exact se résout par égalité alors que les
# compositions publiées n'existent que sous la forme `composition_<quelque
# chose>`. L'ordre reste celui de l'ancienne chaîne : exact d'abord, préfixe
# ensuite.
_GESTIONNAIRES_PAR_NOM: dict[str, Any] = {}
_GESTIONNAIRES_PAR_PREFIXE: list[tuple[str, Any]] = []


def _meta_outil(
    nom: str | None = None,
    *,
    prefixe: str | None = None,
    exige_compositions: bool = False,
) -> Any:
    """Inscrit un gestionnaire dans la table, garde compris.

    Le contrôle d'exposition est posé par l'enrobage, jamais par le corps du
    gestionnaire, et passer par ce décorateur est la seule façon d'être atteint
    depuis `tools_call` : un méta-outil sans garde n'est donc pas exprimable.
    """

    def decorateur(fonction: Any) -> Any:
        @functools.wraps(fonction)
        async def enrobage(passerelle: "McpGateway", appel: _Appel) -> dict | None:
            refus = _refus_hors_profil(appel)
            if refus is not None:
                return refus
            return await fonction(passerelle, appel)

        enrobage.garde_pose = True
        enrobage.exige_compositions = exige_compositions
        if nom is not None:
            _GESTIONNAIRES_PAR_NOM[nom] = enrobage
        if prefixe is not None:
            _GESTIONNAIRES_PAR_PREFIXE.append((prefixe, enrobage))
        return enrobage

    return decorateur


class McpGateway:
    def __init__(
        self,
        catalog: Catalog,
        bundles: BundleSession,
        pool: UpstreamPool,
        compositions: CompositionService | None = None,
        *,
        tools_change_tracker: ToolsChangeTracker | None = None,
        outils_locaux: Any | None = None,
    ) -> None:
        self.catalog = catalog
        self.bundles = bundles
        self.pool = pool
        self.compositions = compositions
        self.tools_change_tracker = tools_change_tracker or ToolsChangeTracker()
        # Une famille d'outils servie par le processus qui porte la passerelle,
        # et non par un serveur amont. L'Atelier s'en sert pour offrir ses
        # propres verbes — conduire une conversation — que personne d'autre ne
        # peut offrir à sa place. Doit exposer `definitions()` et `appeler()`.
        self.outils_locaux = outils_locaux

    def _resolve_exposed(self, session_id: str | None) -> dict[str, Any]:
        conn = self.pool.db
        if not conn or not self.compositions:
            raise RuntimeError("MCP tools require database and compositions service")
        profile = resolve_profile_for_session(conn, self.catalog, self.bundles, session_id)
        return resolve_exposed_tools(
            catalog=self.catalog,
            pool=self.pool,
            compositions=self.compositions,
            conn=conn,
            profile=profile,
            include_unavailable=False,
        )

    def _unavailable_servers(self, session_id: str | None) -> list[str]:
        """Serveurs du profil actif qui ne répondent pas.

        Leurs outils sont retirés du périmètre : sans les nommer, une recherche
        vide se confond avec « cet outil n'existe pas ».
        """
        try:
            attendus = self.bundles.active_server_ids(session_id)
        except Exception:
            return []
        absents = []
        for sid in attendus:
            try:
                if not self.pool.client_probe(sid).get("online"):
                    absents.append(sid)
            except Exception:
                continue
        return absents

    def _tool_exposure(self, session_id: str | None) -> str:
        """Mode d'exposition du bundle actif — `full` si non précisé."""
        bundle = self.catalog.bundles.get(self.bundles.get(session_id))
        return getattr(bundle, "tool_exposure", "full") or "full"

    def _definitions_locales(self, *, pour_la_recherche: bool = False) -> list[dict]:
        """Les outils locaux déclarés ; `pour_la_recherche` : tous ceux que le profil permet.

        Un profil peut ne pas déclarer un outil qu'il permet (l'Assistant et
        ses anciennes commandes de conversation) : la recherche et l'aide à
        l'appel le connaissent quand même.
        """
        if self.outils_locaux is None:
            return []
        try:
            a_chercher = getattr(self.outils_locaux, "definitions_a_chercher", None)
            if pour_la_recherche and a_chercher is not None:
                return list(a_chercher())
            return list(self.outils_locaux.definitions())
        except Exception:  # noqa: BLE001
            # Une famille d'outils qui ne sait pas se décrire ne doit pas
            # emporter la liste entière : le reste du pool reste utilisable.
            _log.exception("définitions des outils locaux")
            return []

    # -- Profil restreint ----------------------------------------------------
    #
    # Les outils locaux peuvent annoncer que l'appel en cours vient d'un profil
    # restreint (l'Atelier : `X-Atelier-Profil: code`, voir
    # `atelier/commandes/profils.py`). La passerelle ne montre alors que les
    # outils locaux que ce profil permet, et refuse tout autre nom à l'appel :
    # ni méta-outils, ni compositions, ni pool. Sans cette annonce, rien ne
    # change.

    def _restreint(self) -> bool:
        annonce = getattr(self.outils_locaux, "restreint", None)
        if annonce is None:
            return False
        try:
            return bool(annonce())
        except Exception:  # noqa: BLE001
            # Dans le doute, restreindre : un profil illisible n'ouvre rien.
            _log.exception("profil des outils locaux")
            return True

    def _refus_du_profil(self, nom: str) -> dict:
        message = getattr(self.outils_locaux, "message_hors_profil", None)
        texte = message(nom) if message is not None else f"Outil hors du profil : {nom}"
        return _texte(texte, erreur=True)

    async def tools_list(self, session_id: str | None) -> list[dict]:
        if self._restreint():
            # Les définitions locales sont déjà celles du profil.
            return self._definitions_locales()
        payload = self._resolve_exposed(session_id)
        tools = payload["tools"]
        if self._tool_exposure(session_id) == "discover":
            # Les méta-outils portent la découverte : les masquer la rendrait
            # inatteignable. Les compositions restent visibles, elles sont peu
            # nombreuses et constituent les points d'entrée métier.
            tools = [
                t for t in tools
                if str(t.get("kind") or "") in ("meta", "composition", "compositions")
            ]
        # Les outils du service portant la passerelle s'annoncent toujours :
        # ils sont peu nombreux, ce sont des points d'entrée métier, et les
        # masquer en mode découverte les rendrait introuvables — `find_tools`
        # cherche dans le pool, où ils ne sont pas.
        return tools_to_mcp_format(tools) + self._definitions_locales()

    def _enrich_call_failure(self, result: dict, target: str, session_id: str | None) -> dict:
        """Rend un échec exploitable : schéma d'appel, ou noms proches.

        Une erreur métier (« No study zone set ») garde son message tel quel :
        y adjoindre un schéma noierait l'information utile.
        """
        if not result.get("isError"):
            return result
        text = " ".join(
            str(b.get("text") or "") for b in result.get("content", []) if isinstance(b, dict)
        )

        try:
            tools = self._resolve_exposed(session_id).get("tools", [])
        except Exception:
            return result
        # Les commandes de l'Atelier sont appelables par gateway_call_tool : un
        # refus de leur part n'est pas un « nom inconnu ».
        tools = list(tools) + self._definitions_locales(pour_la_recherche=True)

        spec = next((t for t in tools if str(t.get("name")) == target), None)

        extra: dict[str, Any] = {}
        if spec is None:
            proches = suggest_names([str(t.get("name")) for t in tools], target)
            extra["outil_introuvable"] = target
            if proches:
                extra["suggestions"] = proches
            extra["aide"] = (
                "Nom inconnu dans le profil actif. Utilisez gateway_find_tools "
                "pour retrouver l'outil et son schéma."
            )
        elif looks_like_argument_error(text):
            extra["inputSchema"] = spec.get("inputSchema") or {
                "type": "object", "properties": {}
            }
            extra["aide"] = (
                "Arguments non conformes. Corrigez selon inputSchema ci-dessus, "
                "puis rappelez gateway_call_tool."
            )

        if not extra:
            return result
        enriched = dict(result)
        enriched["content"] = list(result.get("content") or []) + [
            {"type": "text", "text": json.dumps(extra, ensure_ascii=False)}
        ]
        return enriched

    def _outils_locaux_a_chercher(self) -> list[dict]:
        """Les outils locaux, dans la forme que la recherche lit.

        Ils ne viennent ni du pool ni d'un profil de la passerelle : sans eux,
        `gateway_find_tools` ne trouvait aucune commande `atelier_*` alors que
        `gateway_call_tool` les appelle (audit M7). Ils portent `kind` et
        `server` `atelier`, pour qu'on puisse les chercher par service.
        """
        sortie = []
        for definition in self._definitions_locales(pour_la_recherche=True):
            if not isinstance(definition, dict) or not definition.get("name"):
                continue
            outil = dict(definition)
            outil.setdefault("kind", "atelier")
            outil.setdefault("server", "atelier")
            sortie.append(outil)
        return sortie

    def _find_tools(self, arguments: dict[str, Any], session_id: str | None) -> dict:
        """Recherche dans le périmètre du profil : jamais au-delà."""
        payload = self._resolve_exposed(session_id)
        tools = list(payload.get("tools", []))
        connus = {str(t.get("name") or "") for t in tools}
        tools += [t for t in self._outils_locaux_a_chercher() if t["name"] not in connus]

        usage: dict[str, int] = {}
        pins: set[str] = set()
        if self.pool.db:
            try:
                usage = {
                    str(row["tool_name"]): int(row["use_count"])
                    for row in list_usage(self.pool.db, limit=50)
                }
                pins = {str(row["tool_name"]) for row in list_pins(self.pool.db)}
            except Exception:
                # La pertinence lexicale reste utilisable sans ces signaux.
                usage, pins = {}, set()

        query = str(arguments.get("query") or "").strip()
        kind = str(arguments.get("kind") or "").strip()
        server = str(arguments.get("server") or "").strip()

        # Un critère quelconque signale une intention d'appeler : on renvoie
        # alors les schémas, bornés par la limite. Sans critère c'est un
        # inventaire — complet, mais allégé (joindre les schémas des 105 outils
        # produisait 60 Ko, soit ce que le mode découverte cherche à éviter).
        detailed = bool(query or kind or server)
        limit = arguments.get("limit")
        if isinstance(limit, int) and limit > 0:
            effective_limit = limit
        else:
            effective_limit = DEFAULT_LIMIT if detailed else 0

        found = search_tools(
            tools,
            query=query,
            kind=kind,
            server=server,
            limit=effective_limit,
            usage=usage,
            pins=pins,
        )
        result = {
            "matched": len(found),
            "scope_total": len(tools),
            "tools": tools_to_mcp_format(found) if detailed else _tool_digest(found),
        }
        if not detailed:
            result["hint"] = (
                "Inventaire sans schémas. Rappelez gateway_find_tools avec "
                "query (ou server/kind) pour obtenir les schémas d'appel."
            )
        # Les upstreams injoignables sont retirés du périmètre : sans cette
        # mention, « rien trouvé » se confond avec « n'existe pas ».
        if not found:
            absents = self._unavailable_servers(session_id)
            result["hint"] = (
                f"Aucun résultat. Services injoignables : {', '.join(absents)} — "
                "leurs outils sont temporairement absents du périmètre "
                "(voir gateway_status)."
                if absents
                else "Aucun résultat dans le profil actif. Élargissez la requête "
                "ou changez de profil avec gateway_use_bundle."
            )
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}

    def _gestionnaire(self, nom: str) -> Any | None:
        gestionnaire = _GESTIONNAIRES_PAR_NOM.get(nom)
        if gestionnaire is None:
            for prefixe, candidat in _GESTIONNAIRES_PAR_PREFIXE:
                if nom.startswith(prefixe):
                    gestionnaire = candidat
                    break
        if gestionnaire is None:
            return None
        # Sans service de compositions, ces noms n'ont jamais été traités ici :
        # ils partaient en amont comme n'importe quel outil inconnu.
        if gestionnaire.exige_compositions and not self.compositions:
            return None
        return gestionnaire

    async def tools_call(
        self,
        name: str,
        arguments: dict[str, Any],
        session_id: str | None,
        *,
        internal: bool = False,
    ) -> dict:
        # Un profil restreint n'atteint que ses outils locaux : tout autre nom
        # (méta-outil, composition, outil du pool) est refusé ici, avant
        # toute résolution. Un outil local hors profil est refusé par les
        # outils locaux eux-mêmes, qui le journalisent.
        if self._restreint():
            if self.outils_locaux is not None and name.startswith("atelier_"):
                reponse = await self.outils_locaux.appeler(name, arguments)
                if reponse is not None:
                    return reponse
            return self._refus_du_profil(name)

        # Avant tout le reste : ces outils ne viennent ni du pool ni d'un
        # profil, ils appartiennent au service. Les faire passer par la
        # résolution de profil les ferait refuser comme « hors périmètre ».
        if self.outils_locaux is not None and name.startswith("atelier_"):
            reponse = await self.outils_locaux.appeler(name, arguments)
            if reponse is not None:
                return reponse

        allowed: set[str] | None = None
        profile = None
        if not internal and self.pool.db and self.compositions:
            profile = resolve_profile_for_session(
                self.pool.db, self.catalog, self.bundles, session_id
            )
            payload = resolve_exposed_tools(
                catalog=self.catalog,
                pool=self.pool,
                compositions=self.compositions,
                conn=self.pool.db,
                profile=profile,
                include_unavailable=False,
            )
            allowed = exposed_tool_names(payload)

        appel = _Appel(
            nom=name,
            arguments=arguments,
            session_id=session_id,
            internal=internal,
            profil=profile,
            autorises=allowed,
        )

        gestionnaire = self._gestionnaire(name)
        if gestionnaire is not None:
            # None veut dire « ce n'était pas pour moi » : le gestionnaire de
            # préfixe s'en sert quand le nom ne désigne aucune composition.
            reponse = await gestionnaire(self, appel)
            if reponse is not None:
                return reponse

        refus = _refus_hors_profil(appel)
        if refus is not None:
            return refus

        try:
            result = await self.pool.call(name, arguments)
            content = result.get("content")
            if content:
                return {"content": content, "isError": result.get("isError", False)}
            return _texte(json.dumps(result, ensure_ascii=False, default=str))
        except Exception as exc:
            return _texte(f"Upstream error: {exc}", erreur=True)

    def _active_profile_payload(self, session_id: str | None) -> dict[str, Any]:
        if not self.pool.db:
            raise RuntimeError("DB indisponible")
        if session_id == WEB_UI_SESSION:
            return get_profile_mcp(
                self.pool.db,
                self.catalog,
                self.bundles,
                self.compositions,
            )
        profile = resolve_profile_for_session(
            self.pool.db, self.catalog, self.bundles, session_id
        )
        return get_profile_mcp(
            self.pool.db,
            self.catalog,
            self.bundles,
            self.compositions,
            kind=profile.kind,  # type: ignore[arg-type]
            profile_id=profile.id,
        )

    def prompts_list(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "active_profile",
                "description": "Consigne du profil gateway actif (instructions assistant).",
                "arguments": [],
            }
        ]

    def prompts_get(self, name: str, session_id: str | None) -> dict[str, Any]:
        if name != "active_profile":
            raise KeyError(f"Prompt inconnu: {name}")
        detail = self._active_profile_payload(session_id)
        text = detail.get("instructions") or ""
        return {
            "description": f"Profil actif : {detail.get('label')} ({detail.get('kind')}/{detail.get('id')})",
            "messages": [
                {
                    "role": "user",
                    "content": {"type": "text", "text": text},
                }
            ],
        }

    def resources_list(self) -> list[dict[str, Any]]:
        return [
            {
                "uri": "profile://active",
                "name": "Profil actif",
                "description": "JSON du profil gateway actif (services, consigne, compositions prod).",
                "mimeType": "application/json",
            }
        ]

    def resources_read(self, uri: str, session_id: str | None) -> dict[str, Any]:
        if uri != "profile://active":
            raise KeyError(f"Ressource inconnue: {uri}")
        detail = self._active_profile_payload(session_id)
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(detail, ensure_ascii=False),
                }
            ]
        }

    def _build_initialize_result(self, session_id: str | None) -> dict[str, Any]:
        instructions = ""
        if self._restreint():
            # Les consignes de la passerelle parlent de méta-outils que ce
            # profil n'a pas : on lui donne les siennes.
            propres = getattr(self.outils_locaux, "instructions_du_profil", None)
            instructions = str(propres() or "") if propres is not None else ""
        elif self.pool.db and self.compositions:
            profile = resolve_profile_for_session(
                self.pool.db, self.catalog, self.bundles, session_id
            )
            prod = self.compositions.list_compositions(status="production")
            instructions = build_mcp_instructions(
                profile, prod, tool_exposure=self._tool_exposure(session_id)
            )
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": True},
                "prompts": {},
                "resources": {},
            },
            "serverInfo": {
                "name": "passerelle",
                "title": "Passerelle",
                "version": __version__,
            },
            "instructions": instructions,
            "_meta": {"toolsRevision": self.tools_change_tracker.revision},
        }

    async def handle_jsonrpc(self, body: dict, session_id: str | None) -> dict:
        method = body.get("method")
        req_id = body.get("id")

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": self._build_initialize_result(session_id),
            }

        if method == "tools/list":
            tools = await self.tools_list(session_id)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": tools,
                    "_meta": {"toolsRevision": self.tools_change_tracker.revision},
                },
            }

        if method == "tools/call":
            params = body.get("params") or {}
            result = await self.tools_call(
                params.get("name", ""),
                params.get("arguments") or {},
                session_id,
            )
            return {"jsonrpc": "2.0", "id": req_id, "result": result}

        if self._restreint() and method in (
            "prompts/list", "prompts/get", "resources/list", "resources/read"
        ):
            # Le profil de la passerelle (consigne, services) ne concerne pas
            # un profil restreint : il n'en voit rien.
            vide = {
                "prompts/list": {"prompts": []},
                "resources/list": {"resources": []},
            }.get(method)
            if vide is not None:
                return {"jsonrpc": "2.0", "id": req_id, "result": vide}
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": "hors du profil"},
            }

        if method == "prompts/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"prompts": self.prompts_list()},
            }

        if method == "prompts/get":
            params = body.get("params") or {}
            try:
                result = self.prompts_get(params.get("name", ""), session_id)
            except (KeyError, RuntimeError) as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32000, "message": str(exc)},
                }
            return {"jsonrpc": "2.0", "id": req_id, "result": result}

        if method == "resources/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"resources": self.resources_list()},
            }

        if method == "resources/read":
            params = body.get("params") or {}
            try:
                result = self.resources_read(params.get("uri", ""), session_id)
            except (KeyError, RuntimeError) as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32000, "message": str(exc)},
                }
            return {"jsonrpc": "2.0", "id": req_id, "result": result}

        if method == "notifications/initialized":
            return {}

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }


# --- Gestionnaires de méta-outils -------------------------------------------
#
# Chacun est atteint uniquement par la table, donc uniquement après le garde de
# profil. Un gestionnaire ne rend None que pour dire « ce n'était pas pour
# moi » ; l'appel repart alors vers l'amont.


@_meta_outil("gateway_find_tools")
async def _gerer_find_tools(passerelle: McpGateway, appel: _Appel) -> dict:
    return passerelle._find_tools(appel.arguments, appel.session_id)


@_meta_outil("gateway_call_tool")
async def _gerer_call_tool(passerelle: McpGateway, appel: _Appel) -> dict:
    target = str(appel.arguments.get("name") or "").strip()
    if not target:
        return _texte("Argument 'name' requis.", erreur=True)
    if target == "gateway_call_tool":
        return _texte("Appel récursif refusé.", erreur=True)
    # Même chemin que n'importe quel appel : le garde du profil s'applique
    # à la cible, gateway_call_tool n'élargit donc jamais le périmètre.
    via = VIA_META_OUTIL.set("gateway_call_tool")
    try:
        result = await passerelle.tools_call(
            target,
            appel.arguments.get("arguments") or {},
            appel.session_id,
            internal=appel.internal,
        )
    finally:
        VIA_META_OUTIL.reset(via)
    # Un échec doit rendre de quoi se corriger : sans cela l'assistant
    # relance à l'identique, ou repart en recherche pour rien.
    return passerelle._enrich_call_failure(result, target, appel.session_id)


@_meta_outil("gateway_list_bundles")
async def _gerer_list_bundles(passerelle: McpGateway, appel: _Appel) -> dict:
    return _json(passerelle.bundles.list_bundles())


@_meta_outil("gateway_use_bundle")
async def _gerer_use_bundle(passerelle: McpGateway, appel: _Appel) -> dict:
    bundle = appel.arguments.get("name", "")
    sid = appel.session_id or str(uuid.uuid4())
    try:
        # Se restreindre, oui ; s'élargir, non. C'était l'évasion : trois
        # appels exposés par le profil le plus étroit suffisaient à
        # atteindre le plus large, donc l'exécution de code.
        passerelle.bundles.set_depuis_client(sid, bundle)
    except PlafondDepasse as refus:
        return _texte(str(refus), erreur=True)
    except KeyError:
        return _texte(f"Profil inconnu : {bundle}", erreur=True)
    texte = f"Bundle actif : {bundle} (session={sid})"
    # Basculer vers un profil en découverte vide la liste d'outils. Les
    # instructions d'initialisation ne sont pas réémises : sans ce rappel,
    # l'assistant prend la liste raccourcie pour l'inventaire complet.
    if passerelle._tool_exposure(sid) == "discover":
        texte += (
            "\n\nCe profil est en mode découverte : la liste d'outils ne "
            "montre que le pilotage et les compositions. Pour toute autre "
            "action, cherchez avec gateway_find_tools puis exécutez avec "
            "gateway_call_tool. Ne concluez pas qu'une capacité est absente "
            "sans avoir cherché."
        )
    return _texte(texte)


@_meta_outil("gateway_list_profiles")
async def _gerer_list_profiles(passerelle: McpGateway, appel: _Appel) -> dict:
    if not passerelle.pool.db:
        return _texte("DB indisponible", erreur=True)
    payload = list_profiles_mcp(passerelle.pool.db, passerelle.catalog, passerelle.bundles)
    return _json(payload)


@_meta_outil("gateway_get_profile")
async def _gerer_get_profile(passerelle: McpGateway, appel: _Appel) -> dict:
    if not passerelle.pool.db:
        return _texte("DB indisponible", erreur=True)
    kind = appel.arguments.get("kind")
    pid = appel.arguments.get("id")
    try:
        payload = get_profile_mcp(
            passerelle.pool.db,
            passerelle.catalog,
            passerelle.bundles,
            passerelle.compositions,
            kind=kind,
            profile_id=pid,
        )
    except KeyError as exc:
        return _texte(str(exc), erreur=True)
    return _json(payload)


@_meta_outil("gateway_use_profile")
async def _gerer_use_profile(passerelle: McpGateway, appel: _Appel) -> dict:
    if not passerelle.pool.db:
        return _texte("DB indisponible", erreur=True)
    kind = appel.arguments.get("kind")
    pid = appel.arguments.get("id")
    if not kind or not pid:
        return _texte("kind et id requis", erreur=True)
    try:
        result = use_profile_mcp(
            passerelle.pool.db,
            passerelle.catalog,
            passerelle.bundles,
            kind=kind,
            profile_id=str(pid),
            session_id=appel.session_id,
        )
        result["tools_revision"] = passerelle.tools_change_tracker.bump()
    except (KeyError, ValueError) as exc:
        return _texte(str(exc), erreur=True)
    return _json(result)


@_meta_outil("gateway_create_profile")
async def _gerer_create_profile(passerelle: McpGateway, appel: _Appel) -> dict:
    if not passerelle.pool.db:
        return _texte("DB indisponible", erreur=True)
    arguments = appel.arguments
    try:
        result = create_profile_mcp(
            passerelle.pool.db,
            passerelle.catalog,
            passerelle.bundles,
            name=str(arguments.get("name") or ""),
            profile_id=arguments.get("id"),
            description=str(arguments.get("description") or ""),
            org_servers=arguments.get("org_servers"),
            registry_servers=arguments.get("registry_servers"),
            tool_allowlist=arguments.get("tool_allowlist"),
            meta_tools=arguments.get("meta_tools"),
            activate=bool(arguments.get("activate")),
            session_id=appel.session_id,
        )
        if arguments.get("activate"):
            result["tools_revision"] = passerelle.tools_change_tracker.bump()
    except (KeyError, ValueError) as exc:
        return _texte(str(exc), erreur=True)
    return _json(result)


@_meta_outil("gateway_update_profile")
async def _gerer_update_profile(passerelle: McpGateway, appel: _Appel) -> dict:
    if not passerelle.pool.db:
        return _texte("DB indisponible", erreur=True)
    arguments = appel.arguments
    try:
        result = update_profile_mcp(
            passerelle.pool.db,
            passerelle.catalog,
            passerelle.bundles,
            profile_id=str(arguments.get("id") or ""),
            name=arguments.get("name"),
            description=arguments.get("description"),
            org_servers=arguments.get("org_servers"),
            registry_servers=arguments.get("registry_servers"),
            tool_allowlist=arguments.get("tool_allowlist"),
            meta_tools=arguments.get("meta_tools"),
            activate=bool(arguments.get("activate")),
            session_id=appel.session_id,
        )
        if arguments.get("activate"):
            result["tools_revision"] = passerelle.tools_change_tracker.bump()
    except (KeyError, ValueError) as exc:
        return _texte(str(exc), erreur=True)
    return _json(result)


@_meta_outil("gateway_status")
async def _gerer_status(passerelle: McpGateway, appel: _Appel) -> dict:
    session_id = appel.session_id
    bundle_id = passerelle.bundles.get(session_id)
    profile = appel.profil
    if profile is None and passerelle.pool.db:
        profile = resolve_profile_for_session(
            passerelle.pool.db, passerelle.catalog, passerelle.bundles, session_id
        )
    registry_servers = []
    if profile and passerelle.pool.db:
        registry_servers = [
            {"prefix": prefix, "pool_key": key}
            for key, prefix in registry_pool_keys_for_profile(passerelle.pool.db, profile)
        ]
    auth_hints = {
        sid: (spec.auth_hint or "")
        for sid, spec in passerelle.catalog.servers.items()
    }
    upstreams = enrich_upstream_status(passerelle.pool.status(), auth_hints=auth_hints)
    session_note = None
    if session_id != WEB_UI_SESSION:
        session_note = (
            "Session MCP hors web-ui : profil = preset mcp_default_bundle "
            f"({passerelle.catalog.mcp_default_bundle}). "
            "Pour suivre le profil du widget, reconnectez avec "
            "en-tête Mcp-Session-Id: web-ui (voir .cursor/mcp.json)."
        )
    payload = {
        "bundle": bundle_id,
        "profile": {"kind": profile.kind, "id": profile.id} if profile else None,
        "mcp_default_bundle": passerelle.catalog.mcp_default_bundle,
        "web_ui_session": session_id == WEB_UI_SESSION,
        "session_note": session_note,
        "enforce_envelope": passerelle.catalog.enforce_envelope,
        "servers": profile.org_servers
        if profile
        else passerelle.bundles.active_server_ids(session_id),
        "registry_servers": registry_servers,
        "upstreams": upstreams,
        "compositions": len(passerelle.compositions.list_compositions())
        if passerelle.compositions
        else 0,
        "tools_revision": passerelle.tools_change_tracker.revision,
    }
    return _json(payload)


@_meta_outil("gateway_list_compositions", exige_compositions=True)
async def _gerer_list_compositions(passerelle: McpGateway, appel: _Appel) -> dict:
    items = passerelle.compositions.list_compositions(status=appel.arguments.get("status"))
    return _json(items)


@_meta_outil("gateway_save_composition", exige_compositions=True)
async def _gerer_save_composition(passerelle: McpGateway, appel: _Appel) -> dict:
    try:
        cree = passerelle.compositions.create_from_steps(
            nom=str(appel.arguments.get("name") or ""),
            description=str(appel.arguments.get("description") or ""),
            etapes=appel.arguments.get("steps") or [],
        )
        return _json(cree)
    except Exception as exc:
        # Le motif exact est plus utile que « échec » : l'assistant peut
        # corriger un nom d'outil ou une référence et rappeler.
        return _texte(f"Enregistrement impossible : {exc}", erreur=True)


@_meta_outil("gateway_run_composition", exige_compositions=True)
async def _gerer_run_composition(passerelle: McpGateway, appel: _Appel) -> dict:
    comp_id = appel.arguments.get("composition_id", "")
    try:
        # La session voyage jusqu'aux étapes : une composition
        # s'exécute sous le profil de qui la lance, pas hors de tout.
        result = await passerelle.compositions.execute(
            comp_id, appel.arguments.get("inputs") or {}, session_id=appel.session_id
        )
        return _json(result)
    except Exception as exc:
        return _texte(f"Composition error: {exc}", erreur=True)


@_meta_outil("gateway_composition_run_status", exige_compositions=True)
async def _gerer_composition_run_status(passerelle: McpGateway, appel: _Appel) -> dict:
    run_id = appel.arguments.get("run_id", "")
    row = passerelle.compositions.get_run(run_id)
    if not row:
        return _texte(f"Run introuvable: {run_id}", erreur=True)
    return _json(row)


@_meta_outil("gateway_resume_composition", exige_compositions=True)
async def _gerer_resume_composition(passerelle: McpGateway, appel: _Appel) -> dict:
    run_id = appel.arguments.get("run_id", "")
    try:
        result = await passerelle.compositions.resume(
            run_id, appel.arguments.get("response"), session_id=appel.session_id
        )
        return _json(result)
    except Exception as exc:
        return _texte(f"Resume error: {exc}", erreur=True)


@_meta_outil(prefixe="composition_", exige_compositions=True)
async def _gerer_composition_publiee(passerelle: McpGateway, appel: _Appel) -> dict | None:
    comp_id = passerelle.compositions.composition_id_for_tool(appel.nom)
    # Un nom en composition_ qui ne désigne aucune composition publiée n'était
    # pas traité ici : il repartait vers l'amont, avec le message d'amont.
    if not comp_id:
        return None
    try:
        # La session voyage ici aussi. Sans elle, une composition lancée par son
        # nom d'outil publié — le chemin normal pour un assistant — retombait
        # sur la session du widget, donc sur le profil du propriétaire : ses
        # étapes s'exécutaient hors du périmètre du client qui l'appelait,
        # pendant que le même enchaînement lancé par gateway_run_composition y
        # restait. Deux portes pour la même pièce, une seule fermée.
        result = await passerelle.compositions.execute(
            comp_id, appel.arguments, session_id=appel.session_id
        )
        return _json(result, erreur=result.get("status") == "failed")
    except Exception as exc:
        return _texte(f"Composition error: {exc}", erreur=True)


__all__ = ["McpGateway", "META_TOOLS"]
