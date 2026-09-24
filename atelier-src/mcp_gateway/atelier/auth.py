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

import json
import os
import re
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


def rotate_owner_key(path: Path) -> str:
    """Remplace la clé propriétaire par une neuve, et rend la neuve.

    Écrire par-dessus laisserait, le temps de l'écriture, un fichier vide ou
    tronqué : une requête tombant là ne trouverait pas de clé, et
    `ensure_owner_key` en fabriquerait une troisième. On écrit donc à côté,
    puis on remplace d'un seul geste.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    neuve = secrets.token_hex(32)
    provisoire = path.with_suffix(path.suffix + ".neuve")
    provisoire.write_text(neuve + chr(10), encoding="utf-8")
    provisoire.chmod(stat.S_IRUSR | stat.S_IWUSR)
    os.replace(provisoire, path)
    return neuve


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

    def faire_tourner(self) -> str:
        """Renouvelle la clé, referme les sessions et révoque les jetons.

        Une clé se renouvelle parce qu'elle a fui. Laisser vivre les sessions
        de navigation qu'elle avait ouvertes reviendrait à ne rien changer
        pour qui les détient : elles tombent avec elle.

        Les jetons OAuth tombent pour la même raison. Ils ne tombaient pas :
        la clé n'avait alors aucun rôle dans leur émission. Depuis qu'elle est
        ce qui consent à un client distant, la changer sans les révoquer
        laissait un connecteur branché au nom d'une clé qui n'existe plus.
        """
        neuve = rotate_owner_key(self.settings.owner_key_path)
        self.owner_key = neuve
        conn = self._base()
        try:
            conn.execute("DELETE FROM oauth_sessions")
            conn.execute("DELETE FROM oauth_tokens")
            conn.commit()
        finally:
            conn.close()
        return neuve

    def fermer_session(self, sid: str | None) -> bool:
        conn = self._base()
        try:
            return close_owner_session(conn, sid or "")
        finally:
            conn.close()

    def check_navigation(self, token: str | None, sid: str | None) -> str:
        """Le porteur de la clé, ou une session ouverte par lui.

        La clé au porteur reste pour les clients hors navigateur (CLI, MCP).
        Le cookie, lui, ne vaut que par la session qu'il désigne. Une clé
        présentée et fausse ne retombe pas sur le cookie : elle est refusée.
        """
        if token:
            return self.check_token(token)
        if self.session_valide(sid):
            return "session"
        raise HTTPException(status_code=401, detail="Bearer owner key required")

    def check_api(self, token: str | None, sid: str | None, depuis_interface: bool) -> str:
        """La garde de l'API : la clé au porteur, ou la session de l'interface.

        L'interface ne garde plus la clé : elle s'en sert une fois pour ouvrir
        une session, puis parle à l'API par le cookie. Le cookie seul ne suffit
        pas pour autant : il faut aussi l'en-tête `X-Atelier-Interface`, qu'une
        page d'une autre origine ne peut poser sans une requête préalable CORS
        que ce service ne satisfait jamais. Un formulaire ou une image
        glissés ailleurs ne portent que le cookie — ils ne passent pas.
        """
        if token:
            return self.check_token(token)
        if depuis_interface and self.session_valide(sid):
            return "session"
        raise HTTPException(status_code=401, detail="Bearer owner key required")


# ── La garde des cookies ───────────────────────────────────────────────
#
# `sspcloud.fr` n'est pas dans la liste des suffixes publics : tout service
# d'un autre utilisateur sous `*.user.lab.sspcloud.fr` est donc « même site »
# que l'Atelier, et `SameSite=Lax` le laisse joindre notre cookie à ses
# requêtes. Seule l'origine exacte départage l'interface d'un voisin.

# L'en-tête que pose l'interface, et elle seule (voir `check_api`).
ENTETE_INTERFACE = "x-atelier-interface"

METHODES_SURES = frozenset({"GET", "HEAD", "OPTIONS"})

# Les GET qui agissent. `EventSource` ne sait faire que GET, et l'envoi d'un
# message passe par là : sans garde, un lien posé chez un voisin lançait un
# tour au nom du propriétaire.
GET_QUI_AGISSENT = (re.compile(r"^/v1/sessions/[^/]+/events/?$"),)


def _entetes(scope: dict[str, Any]) -> dict[str, str]:
    vus: dict[str, str] = {}
    for cle, valeur in scope.get("headers") or []:
        nom = cle.decode("latin-1").lower()
        texte = valeur.decode("latin-1")
        vus[nom] = f"{vus[nom]}; {texte}" if nom == "cookie" and nom in vus else texte
    return vus


def origines_de(entetes: dict[str, str], scheme: str, public_url: str) -> set[str]:
    """Les origines sous lesquelles ce service se sait atteint."""
    origines = set()
    if public_url:
        origines.add(public_url.strip().rstrip("/"))
    hote = (entetes.get("x-forwarded-host") or entetes.get("host") or "").split(",")[0].strip()
    schema = (entetes.get("x-forwarded-proto") or scheme or "http").split(",")[0].strip()
    if hote:
        origines.add(f"{schema}://{hote}")
    return origines


def raison_du_refus(
    methode: str, chemin: str, entetes: dict[str, str], origines: set[str]
) -> str | None:
    """Pourquoi une requête portant le cookie doit être refusée — ou rien."""
    site = entetes.get("sec-fetch-site")
    origine = entetes.get("origin")
    if methode not in METHODES_SURES:
        if site == "same-origin":
            return None
        if site is None and origine is not None and origine in origines:
            return None
        return "requête d'une autre origine refusée"
    if any(m.match(chemin) for m in GET_QUI_AGISSENT):
        if site in ("same-origin", "none"):
            return None
        return "requête d'une autre origine refusée"
    return None


class GardeDesCookies:
    """Middleware ASGI : ce que le cookie de session a le droit d'autoriser.

    Une requête authentifiée par la clé au porteur n'est pas concernée : un
    navigateur ne pose pas cet en-tête pour le compte d'une autre origine.
    Une requête qui porte le cookie, elle, doit venir de l'Atelier même dès
    qu'elle écrit (`Sec-Fetch-Site: same-origin`, ou à défaut un `Origin`
    exactement égal au nôtre), ou qu'elle est l'un des GET qui agissent.

    Elle migre aussi l'ancien cookie : présenté seul, il est lu comme le
    nouveau pour cette requête, puis remplacé dans la réponse.
    """

    def __init__(self, app: Any, public_url: str = "", duree: int = OwnerAuth.DUREE_SESSION) -> None:
        self.app = app
        self.public_url = public_url
        self.duree = duree

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        from starlette.requests import cookie_parser

        from mcp_gateway.atelier.vscode_bridge import COOKIE_ANCIEN, COOKIE_NAME

        entetes = _entetes(scope)
        cookies = cookie_parser(entetes.get("cookie", ""))
        ancien = cookies.get(COOKIE_ANCIEN) if COOKIE_NAME not in cookies else None
        if ancien:
            # Un seul en-tête `cookie` : Starlette ne lit que le premier.
            scope = dict(scope)
            fusion = f"{entetes.get('cookie', '')}; {COOKIE_NAME}={ancien}".encode("latin-1")
            scope["headers"] = [
                *((k, v) for k, v in scope.get("headers") or [] if k.lower() != b"cookie"),
                (b"cookie", fusion),
            ]
        avec_cookie = bool(cookies.get(COOKIE_NAME) or ancien)
        porteur = bearer_from_header(entetes.get("authorization")) is not None

        if scope["type"] == "http" and avec_cookie and not porteur:
            raison = raison_du_refus(
                scope.get("method", "GET"),
                scope.get("path", ""),
                entetes,
                origines_de(entetes, scope.get("scheme", "http"), self.public_url),
            )
            if raison:
                corps = json.dumps({"detail": raison}).encode("utf-8")
                await send(
                    {
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(corps)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": corps})
                return

        if not (ancien and scope["type"] == "http"):
            await self.app(scope, receive, send)
            return

        remplacement = [
            (
                b"set-cookie",
                (
                    f"{COOKIE_NAME}={ancien}; HttpOnly; Secure; SameSite=Lax; "
                    f"Path=/; Max-Age={self.duree}"
                ).encode("latin-1"),
            ),
            (b"set-cookie", f'{COOKIE_ANCIEN}=""; Max-Age=0; Path=/'.encode("latin-1")),
        ]

        async def envoyer(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                deja = [k for k, v in message.get("headers") or [] if k.lower() == b"set-cookie"
                        and v.startswith(COOKIE_NAME.encode())]
                if not deja:
                    message = dict(message)
                    message["headers"] = [*(message.get("headers") or []), *remplacement]
            await send(message)

        await self.app(scope, receive, envoyer)
