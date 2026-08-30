"""Agrégat Agent — payload pilote Wikichat pour l'onglet Atelier (comme gateway_overview)."""

from __future__ import annotations

from typing import Any

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.pilote_client import pilote_get


async def build_pilote_overview(settings: AtelierSettings) -> dict[str, Any]:
    """Relaie /pilote/api/data + métadonnées pour la vue native."""
    data = await pilote_get(settings, "/pilote/api/data")
    agents = data.get("agents") if isinstance(data.get("agents"), list) else []
    daemon = data.get("daemon") if isinstance(data.get("daemon"), dict) else {}
    return {
        "active": bool(data.get("active", True)),
        "gate_open": bool(data.get("active", True)),
        "daemon": {
            "armed": int(daemon.get("armed") or 0),
            "total": int(daemon.get("total") or len(agents)),
            "wake": str(daemon.get("wake") or "—"),
            "wake_agent": str(daemon.get("wakeAgent") or ""),
            "paused": bool(daemon.get("paused")),
        },
        "agents": agents,
        # Déclencheurs installés par la plateforme : ils n'apparaissent pas
        # dans « agents » côté coordinateur, qui ne retient que les tâches
        # planifiées. Ils agissent pourtant, d'où leur place à l'écran.
        "system_agents": (
            data.get("system_agents")
            if isinstance(data.get("system_agents"), list)
            else []
        ),
        "wikichat_origin": settings.wikichat_url,
    }
