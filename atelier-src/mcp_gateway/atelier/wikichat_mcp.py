"""La connexion d'un agent à wikichat : par le pont stdio, qui porte la conversation.

Contrat avec wikichat (branche `atelier-coherence`, `docs/hooks-et-dialogue.md`
§4.1 et §8, points 1 à 3) : une connexion MCP qui porte l'identifiant de la
conversation Claude prend le nom de cette conversation (`<slug>-<id6>`) ; le nom
commun `atelier`, écrit jusqu'ici dans les `.mcp.json` (`?agent=atelier`), ne
désigne plus personne.

Deux transports possibles ; on retient le **pont stdio**
(`<wikichat>/scripts/wikichat-mcp-stdio.mjs`) :

- Claude Code pose `CLAUDE_CODE_SESSION_ID` dans l'environnement des serveurs
  stdio (documenté ; un serveur stdio garde l'identifiant de son lancement).
  Le pont le passe au helper de wikichat, qui en tire le jeton et l'en-tête
  `x-wikichat-claude-session`, et le pont les porte dans l'adresse SSE
  (`?claude_session=`, `?token=`).
- L'autre voie, une entrée SSE avec `headersHelper`, dépend de ce que Claude
  Code donne au helper : la documentation ne dit pas qu'il reçoit
  `CLAUDE_CODE_SESSION_ID`, le pont lui-même note que l'extension VS Code
  n'envoie pas ces en-têtes, et le serveur a journalisé 6 970 connexions sans
  une seule identité restaurée par ce chemin.
- Le pont reçoit aussi l'environnement du processus `claude` : dans un tour
  de l'Atelier, `WIKICHAT_AGENT` (le nom résolu, `?agent=`), et ailleurs
  rien, auquel cas le nom vient de la conversation.

Coût : un processus node (~40 Mo) par client connecté, comme le navigateur.

La passerelle de l'Atelier garde, pour ses propres appels (`gateway_call_tool`,
compositions), l'entrée SSE du pool, sous un nom qui lui est propre :
`passerelle-atelier`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from mcp_gateway.atelier.config import AtelierSettings

log = logging.getLogger("atelier.wikichat_mcp")

SERVICE_WIKICHAT = "wikichat"
PONT = "wikichat-mcp-stdio.mjs"
# Le nom sous lequel la passerelle elle-même parle au coordinateur. Pas
# `atelier` : wikichat le tient pour générique (`WIKICHAT_NOMS_GENERIQUES`) et
# une connexion sans nom attend sans réponse.
NOM_PASSERELLE = "passerelle-atelier"
NOMS_GENERIQUES = frozenset({"", "atelier"})
_PORT_PAR_DEFAUT = 3777
_HOTES_LOCAUX = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def script_du_pont(settings: AtelierSettings) -> Path:
    return settings.wikichat_source / "scripts" / PONT


def node_de_l_atelier(settings: AtelierSettings) -> Path:
    """Le node posé par l'init (22.x) : celui du système est un Node 18 sur le pod."""
    return settings.work_dir / "bin" / "node"


def declaration_wikichat(settings: AtelierSettings) -> dict[str, Any]:
    """Ce qu'un fichier de configuration dit de wikichat. Sans secret ni nom.

    La même pour le fichier effectif d'un tour, le `.mcp.json` d'un projet et
    `claude-mcp.json` : l'identité vient de l'environnement du client
    (`WIKICHAT_AGENT` dans nos tours, `CLAUDE_CODE_SESSION_ID` partout).
    """
    declaration: dict[str, Any] = {
        "type": "stdio",
        "command": str(node_de_l_atelier(settings)),
        "args": [str(script_du_pont(settings))],
    }
    adresse = urlsplit(settings.wikichat_url or "")
    env: dict[str, str] = {}
    if adresse.hostname and adresse.hostname not in _HOTES_LOCAUX:
        env["WIKICHAT_HOST"] = adresse.hostname
    if adresse.port and adresse.port != _PORT_PAR_DEFAUT:
        env["WIKICHAT_PORT"] = str(adresse.port)
    if env:
        declaration["env"] = env
    return declaration


def _autorite(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    hote = (parts.hostname or "").lower()
    if hote in _HOTES_LOCAUX:
        hote = "local"
    try:
        port = parts.port
    except ValueError:
        port = None
    return f"{hote}:{port or ''}"


def est_le_pont(cfg: Any) -> bool:
    args = cfg.get("args") if isinstance(cfg, dict) else None
    return isinstance(args, list) and any(isinstance(a, str) and a.endswith(PONT) for a in args)


def est_wikichat(nom: str, cfg: Any, settings: AtelierSettings) -> bool:
    """Vrai pour l'entrée du coordinateur : son nom, son adresse, ou le pont.

    Une entrée SSE qui vise la même machine et le même port que
    `settings.wikichat_url` est le coordinateur, quel que soit son nom.
    """
    if not isinstance(cfg, dict):
        return False
    if est_le_pont(cfg):
        return True
    url = str(cfg.get("url") or "")
    if url and settings.wikichat_url:
        return _autorite(url) == _autorite(settings.wikichat_url)
    return nom == SERVICE_WIKICHAT and not url and not cfg.get("command")


def integrer_wikichat(servers: dict[str, Any], settings: AtelierSettings) -> dict[str, Any]:
    """Remplace toute entrée du coordinateur par la déclaration du pont."""
    return {
        nom: declaration_wikichat(settings) if est_wikichat(nom, cfg, settings) else cfg
        for nom, cfg in servers.items()
    }


def url_de_la_passerelle(url: str) -> str:
    """L'adresse SSE du pool, avec le nom propre de la passerelle.

    `?agent=` absent ou générique (`atelier`) devient `?agent=passerelle-atelier` ;
    un autre nom, choisi par quelqu'un, est gardé.
    """
    base, _, requete = url.partition("?")
    parties = [p for p in requete.split("&") if p]
    agents = [p for p in parties if p.startswith("agent=")]
    if agents and agents[0].split("=", 1)[1].strip().lower() not in NOMS_GENERIQUES:
        return url
    garde = [p for p in parties if not p.startswith("agent=")]
    return base + "?" + "&".join([f"agent={quote(NOM_PASSERELLE, safe='')}", *garde])


def renommer_la_passerelle(settings: AtelierSettings) -> list[str]:
    """Au démarrage : les entrées SSE du pool vers wikichat quittent le nom `atelier`.

    Rend les noms des entrées modifiées. Leur état activé ou non est gardé.
    """
    from copy import deepcopy

    from mcp_gateway.db import connect
    from mcp_gateway.registry import list_registry_servers, update_registry_server_config

    modifiees: list[str] = []
    conn = connect(settings.gateway_db_path)
    try:
        for entree in list_registry_servers(conn):
            config = deepcopy(entree.config)
            url = str(config.get("url") or "")
            if not url or not est_wikichat(entree.server_id, config, settings):
                continue
            nouvelle = url_de_la_passerelle(url)
            if nouvelle == url:
                continue
            # La configuration telle quelle, métadonnées comprises ; l'état
            # activé ou non vit ailleurs et ne bouge pas.
            config["url"] = nouvelle
            update_registry_server_config(conn, entree.server_id, config)
            modifiees.append(entree.server_id)
    finally:
        conn.close()
    if modifiees:
        log.info("wikichat : la passerelle se présente désormais comme %s (%s)", NOM_PASSERELLE, modifiees)
    return modifiees
