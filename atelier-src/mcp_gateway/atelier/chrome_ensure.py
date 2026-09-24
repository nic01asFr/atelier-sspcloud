"""Propose le navigateur dans le pool, une fois, et respecte ce qu'on en fait.

Au démarrage de l'Atelier :

- pas d'URL ou pas de jeton configurés → rien n'est créé ni modifié ;
- connecteur absent et jamais proposé → créé, activé ;
- connecteur absent alors qu'il a déjà été proposé → la personne l'a
  supprimé : on ne le recrée pas ;
- connecteur présent → son adresse et son jeton suivent la configuration,
  son état activé / désactivé reste celui que la personne a choisi.

La trace « déjà proposé » est un fichier du dossier MCP de l'Atelier. La
supprimer fait reproposer le navigateur au démarrage suivant.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.navigateur import (
    SERVICE_CHROME,
    chrome_mcp_url_configuree,
    declaration_du_pool,
    jeton_chrome,
)

log = logging.getLogger("atelier.chrome_ensure")

TRACE_PROPOSE = "navigateur-propose"


def ensure_chrome_mcp_connector(settings: AtelierSettings) -> dict[str, Any] | None:
    """Crée ou met à jour le connecteur du navigateur. Rend l'entrée, ou None."""
    from mcp_gateway.db import connect

    from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
    from mcp_gateway.atelier.mcp_sync import materialize_mcp_config

    if not chrome_mcp_url_configuree(settings):
        log.info("navigateur : aucune URL configurée (ATELIER_CHROME_MCP_URL), rien à déclarer")
        return None
    if not jeton_chrome(settings):
        log.warning(
            "navigateur : URL configurée mais pas de jeton (%s) — le service l'exige,"
            " connecteur non déclaré",
            settings.chrome_mcp_token_path,
        )
        return None

    trace = settings.mcp_dir / TRACE_PROPOSE
    conn = connect(settings.gateway_db_path)
    try:
        store = IntegratedMcpStore(conn)
        existant = store.list_servers().get(SERVICE_CHROME)
        if existant is None:
            if trace.exists():
                log.info("navigateur : supprimé par la personne, non recréé")
                return None
            entry = store.upsert(SERVICE_CHROME, {**declaration_du_pool(settings), "enabled": True})
        else:
            actif = existant.get("enabled", True) is not False
            entry = store.upsert(SERVICE_CHROME, {**declaration_du_pool(settings), "enabled": actif})
    finally:
        conn.close()
    settings.mcp_dir.mkdir(parents=True, exist_ok=True)
    trace.touch(exist_ok=True)
    materialize_mcp_config(settings)
    return entry
