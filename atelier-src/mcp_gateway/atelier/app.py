"""Point d'entrée Atelier — uvicorn mcp_gateway.atelier.app:app."""

from __future__ import annotations

import argparse
import os

import uvicorn

from mcp_gateway.atelier.api import build_app
from mcp_gateway.atelier.config import get_settings


def create_app():
    use_fake = os.environ.get("ATELIER_FAKE_HARNESS", "").lower() in {"1", "true", "yes"}
    return build_app(use_fake=use_fake)


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
    uvicorn.run(
        "mcp_gateway.atelier.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
