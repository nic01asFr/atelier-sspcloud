"""Point d'entrée Atelier — uvicorn mcp_gateway.atelier.app:app.

Deux serveurs dans un seul processus : l'Atelier sur `ATELIER_PORT` (8787),
et, quand un second hôte est déclaré (`ATELIER_APPS_PUBLIC_URL`), l'hôte des
applications des projets sur `ATELIER_APPS_PORT` (8788). Un seul processus,
parce qu'ils partagent le superviseur des applications et les sessions ;
deux serveurs, parce qu'ils sont deux origines.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
from typing import Any, Iterator

import uvicorn

from mcp_gateway.atelier.api import build_app
from mcp_gateway.atelier.config import get_settings


def create_app():
    use_fake = os.environ.get("ATELIER_FAKE_HARNESS", "").lower() in {"1", "true", "yes"}
    return build_app(use_fake=use_fake)


class _ServeurSecondaire(uvicorn.Server):
    """Le serveur de l'hôte des applications : il ne capte pas les signaux.

    Deux serveurs qui posent chacun leur gestionnaire de SIGTERM : seul le
    dernier posé l'entend, et l'autre ne s'arrête jamais. C'est le serveur de
    l'Atelier qui les reçoit ; celui-ci s'arrête quand l'autre a fini.
    """

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:  # type: ignore[override]
        yield


async def _servir(atelier: Any, host: str, port: int, apps_port: int | None) -> None:
    principal = uvicorn.Server(uvicorn.Config(atelier, host=host, port=port, reload=False))
    if apps_port is None:
        await principal.serve()
        return
    secondaire = _ServeurSecondaire(
        uvicorn.Config(atelier.state.app_apps, host=host, port=apps_port, lifespan="off", reload=False)
    )
    tache = asyncio.create_task(secondaire.serve())
    try:
        await principal.serve()
    finally:
        secondaire.should_exit = True
        await tache


def main() -> None:
    parser = argparse.ArgumentParser(description="Atelier session service")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--fake", action="store_true", help="Harness factice")
    args = parser.parse_args()
    settings = get_settings()
    if args.fake:
        os.environ["ATELIER_FAKE_HARNESS"] = "1"
    host = args.host or settings.host
    port = args.port or settings.port
    # Refuse non-loopback without auth configured — owner key always created
    if host not in {"127.0.0.1", "localhost", "::1"} and not settings.owner_key_path.is_file():
        raise SystemExit("Refus: host non local sans clé owner")
    # Sans second hôte, pas de second serveur : on ne sert jamais le contenu
    # des applications sous un chemin de l'origine de l'Atelier.
    apps_port = settings.apps_port if (settings.apps_public_url or "").strip() else None
    asyncio.run(_servir(create_app(), host, port, apps_port))


if __name__ == "__main__":
    main()
