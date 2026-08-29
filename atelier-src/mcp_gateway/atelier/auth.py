"""Auth Bearer — clé propriétaire Atelier (fichier 0600)."""

from __future__ import annotations

import secrets
import stat
from pathlib import Path

from fastapi import Header, HTTPException

from mcp_gateway.atelier.config import AtelierSettings


def ensure_owner_key(path: Path) -> str:
    """Crée ou lit la clé owner. Fichier en 0600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        key = path.read_text(encoding="utf-8").strip()
        if key:
            return key
    key = secrets.token_hex(32)
    path.write_text(key + "\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return key


def bearer_from_header(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


class OwnerAuth:
    def __init__(self, settings: AtelierSettings) -> None:
        self.settings = settings
        self.owner_key = ensure_owner_key(settings.owner_key_path)

    def check_token(self, token: str | None) -> str:
        if not token or not secrets.compare_digest(token, self.owner_key):
            raise HTTPException(status_code=401, detail="Bearer owner key required")
        return token

    def require(self, authorization: str | None = Header(default=None)) -> str:
        return self.check_token(bearer_from_header(authorization))
