"""Le navigateur de l'Atelier : où il est, comment on s'y présente.

Contrat avec le service (fork `chrome-devtools-mcp`, `docs/ATELIER-SPEC.md`) :

- chaque session MCP s'ouvre avec l'en-tête `X-Atelier-Conversation`, qui
  nomme la conversation ; le service rend à toutes les sessions d'une même
  conversation le même Chrome ;
- chaque requête porte `Authorization: Bearer <jeton>`, le jeton étant la
  `CDM_API_KEY` du service. Il n'est jamais écrit en clair dans un fichier de
  configuration : seulement la référence `${ATELIER_MCP_CHROME_DEVTOOLS_MCP_AUTHORIZATION}`,
  que l'Atelier remplit dans l'environnement des processus qu'il lance (voir
  `mcp_secrets`). La valeur vit dans le pool (base de la passerelle) et dans
  le dossier de secrets.

Le navigateur de l'Atelier se reconnaît à son identifiant, `SERVICE_CHROME`,
et à rien d'autre. Un connecteur tiers dont le nom ou l'adresse contient
« chrome » n'est pas le nôtre : on ne le réécrit pas.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.mcp_secrets import nom_de_variable

log = logging.getLogger("atelier.navigateur")

SERVICE_CHROME = "chrome-devtools-mcp"
ENTETE_CONVERSATION = "X-Atelier-Conversation"
# La conversation sous laquelle la passerelle elle-même joint le navigateur
# (gateway_find_tools / gateway_call_tool).
CONVERSATION_PASSERELLE = "atelier-passerelle"
# Celle des clients qui lisent un fichier hors conversation (VS Code, HOME,
# `.mcp.json` d'un projet) : ils n'ont pas d'`ATELIER_SESSION` à fournir.
CONVERSATION_HORS_ATELIER = "poste"


def est_le_navigateur(nom: str, cfg: dict[str, Any] | None = None) -> bool:  # noqa: ARG001
    """Vrai pour le seul service déclaré par l'Atelier, reconnu à son identifiant.

    `cfg` est accepté pour la compatibilité des appelants ; il ne décide
    plus de rien. Reconnaître le navigateur à son adresse faisait réécrire
    en silence tout connecteur tiers dont l'URL contenait « chrome ».
    """
    return nom == SERVICE_CHROME


def _adresse_mcp(url: str) -> str:
    u = url.split("?")[0].strip().rstrip("/")
    if not u:
        return ""
    if not u.endswith("/mcp"):
        u += "/mcp"
    return u


def chrome_mcp_url_configuree(settings: AtelierSettings) -> str:
    """L'adresse du `/mcp` du navigateur, ou "" si aucune n'est configurée."""
    return _adresse_mcp(settings.chrome_mcp_url or "")


def chrome_http_origin(settings: AtelierSettings) -> str:
    """Origine HTTP du service (sans `/mcp`), ou "" s'il n'est pas configuré."""
    mcp = chrome_mcp_url_configuree(settings)
    return mcp[: -len("/mcp")] if mcp.endswith("/mcp") else mcp


def jeton_chrome(settings: AtelierSettings) -> str:
    """Le jeton du service : fichier de secrets d'abord, puis la variable."""
    try:
        valeur = settings.chrome_mcp_token_path.read_text(encoding="utf-8").strip()
    except OSError:
        valeur = ""
    return valeur or (settings.chrome_mcp_token or "").strip()


def variable_du_jeton() -> str:
    """La variable d'environnement qui porte le jeton, dérivée comme les autres."""
    return nom_de_variable(SERVICE_CHROME, "Authorization")


def navigateur_configure(settings: AtelierSettings) -> bool:
    return bool(chrome_mcp_url_configuree(settings) and jeton_chrome(settings))


def declaration_chrome(
    settings: AtelierSettings,
    *,
    cloisonner: bool = True,
) -> dict[str, Any]:
    """Ce qu'un fichier de configuration dit du navigateur. Sans secret.

    `cloisonner` : le fichier effectif d'une conversation, où l'Atelier
    résout `${ATELIER_SESSION}`. Sinon (HOME, projet, VS Code), la variable
    porte un repli : ces clients partagent la conversation « poste ».
    """
    conversation = "${ATELIER_SESSION}" if cloisonner else (
        "${ATELIER_SESSION:-" + CONVERSATION_HORS_ATELIER + "}"
    )
    return {
        "type": "http",
        "url": chrome_mcp_url_configuree(settings),
        "headers": {
            ENTETE_CONVERSATION: conversation,
            "Authorization": "Bearer ${" + variable_du_jeton() + "}",
        },
    }


def declaration_du_pool(settings: AtelierSettings) -> dict[str, Any]:
    """L'entrée du pool : celle dont la passerelle se sert elle-même.

    Elle porte le jeton en clair — c'est la base de la passerelle, où vivent
    déjà les secrets des autres connecteurs, et c'est de là que
    `variables_du_pool` tire la valeur de la référence. Jamais recopiée
    telle quelle dans un fichier : `integrer_le_navigateur` la remplace.
    """
    return {
        "type": "http",
        "url": chrome_mcp_url_configuree(settings),
        "headers": {
            ENTETE_CONVERSATION: CONVERSATION_PASSERELLE,
            "Authorization": f"Bearer {jeton_chrome(settings)}",
        },
    }


def entetes_service(settings: AtelierSettings) -> dict[str, str]:
    """Les en-têtes d'un appel direct de l'Atelier au service (santé, bureau)."""
    jeton = jeton_chrome(settings)
    return {"Authorization": f"Bearer {jeton}"} if jeton else {}
