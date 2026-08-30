"""Assure data durable WikiChat + connecteur MCP compte (pas le service Node)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.mcp_sync import materialize_mcp_config


def _link_home_wikichat(home_link: Path, durable: Path) -> None:
    """Symlink Unix ; junction Windows (souvent sans privilège admin)."""
    if home_link.exists() or home_link.is_symlink():
        if home_link.is_symlink() or (sys.platform == "win32" and home_link.is_dir()):
            try:
                if home_link.resolve() == durable.resolve():
                    return
            except OSError:
                pass
        if home_link.is_symlink():
            home_link.unlink()
        elif home_link.is_dir() and not any(home_link.iterdir()):
            home_link.rmdir()
        elif home_link.exists():
            # Dossier non vide existant : ne pas détruire (ADR data safety).
            return

    if sys.platform == "win32":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(home_link), str(durable)],
            check=True,
            capture_output=True,
            text=True,
            encoding="oem",
            errors="replace",
        )
        return
    home_link.symlink_to(durable, target_is_directory=True)


def ensure_wikichat_data_link(settings: AtelierSettings) -> Path:
    """~/work/wikichat durable ; $HOME/.wikichat → lien (API native WikiChat)."""
    durable = settings.wikichat_dir
    durable.mkdir(parents=True, exist_ok=True)
    home_link = Path.home() / ".wikichat"
    _link_home_wikichat(home_link, durable)
    return home_link


def ensure_wikichat_mcp_connector(settings: AtelierSettings) -> dict[str, Any]:
    """Upsert connecteur SSE wikichat dans le pool intégré + materialize."""
    from mcp_gateway.db import connect

    from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore

    url = (settings.wikichat_url or "").strip() or "http://127.0.0.1:3777/sse"
    # Le coordinateur veut savoir à qui il parle. Sans identité, il répond
    # bien à `tools/list` — d'où un connecteur qui paraît sain — mais laisse
    # les appels sans réponse : soixante secondes, puis un délai dépassé.
    # C'est par cette voie que passent gateway_call_tool et les compositions,
    # donc rien de ce qui touche wikichat ne fonctionnait au-delà de la liste.
    if "agent=" not in url:
        url += ("&" if "?" in url else "?") + "agent=atelier"
    raw: dict[str, Any] = {"type": "sse", "url": url, "enabled": True}
    conn = connect(settings.gateway_db_path)
    try:
        store = IntegratedMcpStore(conn)
        entry = store.upsert("wikichat", raw)
    finally:
        conn.close()
    materialize_mcp_config(settings)
    return entry
