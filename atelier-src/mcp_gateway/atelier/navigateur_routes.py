"""L'état du navigateur, pour l'interface : `/chrome/health`.

Le navigateur tourne en stdio dans le processus de chaque agent : il n'y a
plus de service à joindre, ni de bureau à relayer (`/chrome/view`,
`/chrome/novnc/…`, `/chrome/vnc` ont disparu avec le mode HTTP distant). Ce
que l'Atelier peut en dire vient du pod : le lanceur est-il là, trouve-t-il
node, le serveur et Chrome, combien de Chrome sont ouverts, et pour quel
plafond. `bureau` reste dans la réponse, toujours faux, pour les interfaces
qui le lisaient.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.navigateur import etat_local


def register_navigateur_routes(
    app: FastAPI,
    settings: AtelierSettings,
    auth_dep: Callable[..., Any],
) -> None:
    """Monte `/chrome/health`."""

    @app.get("/chrome/health")
    async def chrome_health(_owner: str = Depends(auth_dep)) -> JSONResponse:
        # La vérification lance le lanceur (sans rien ouvrir) : hors de la
        # boucle, pour ne pas la bloquer.
        return JSONResponse(await run_in_threadpool(etat_local, settings))
