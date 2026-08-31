"""Auth Atelier : clé propriétaire au porteur, session pour la navigation.

La clé propriétaire ouvre tout — le harnais lance `claude` en
`bypassPermissions`, donc qui la détient exécute ce qu'il veut sur le pod.
Elle n'a rien à faire dans un cookie de trente jours : un cookie exfiltré
donnait cette clé, définitive et non révocable sans se connecter au pod.

La navigation passe donc par un identifiant de session sans pouvoir propre,
daté et révocable. C'est ce que la passerelle a déjà fait pour le même
défaut ; on réutilise sa table plutôt que d'en écrire une seconde.
"""

from __future__ import annotations

import secrets
import stat
from pathlib import Path
from typing import Any

from fastapi import Header, HTTPException

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.auth import (
    close_owner_session,
    migrate_auth_schema,
    open_owner_session,
    owner_session_valid,
)
from mcp_gateway.db import connect


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

    # Durée d'une session de navigation. Assez longue pour qu'on ne se
    # reconnecte pas à chaque ouverture de VS Code, assez courte pour qu'un
    # cookie oublié finisse par ne plus rien valoir.
    DUREE_SESSION = 60 * 60 * 24 * 7

    def _base(self) -> Any:
        conn = connect(self.settings.gateway_db_path)
        migrate_auth_schema(conn)
        return conn

    def ouvrir_session(self) -> str:
        """Un identifiant de navigation, sans pouvoir propre."""
        conn = self._base()
        try:
            return open_owner_session(conn, self.DUREE_SESSION)
        finally:
            conn.close()

    def session_valide(self, sid: str | None) -> bool:
        if not sid:
            return False
        conn = self._base()
        try:
            return owner_session_valid(conn, sid)
        finally:
            conn.close()

    def fermer_session(self, sid: str | None) -> bool:
        conn = self._base()
        try:
            return close_owner_session(conn, sid or "")
        finally:
            conn.close()

    def check_navigation(self, token: str | None, sid: str | None) -> str:
        """Le porteur de la clé, ou une session ouverte par lui.

        La clé reste acceptée : c'est elle que porte l'onglet de l'interface.
        Le cookie, lui, ne vaut plus que par la session qu'il désigne.
        """
        if token:
            return self.check_token(token)
        if self.session_valide(sid):
            return "session"
        raise HTTPException(status_code=401, detail="Bearer owner key required")
