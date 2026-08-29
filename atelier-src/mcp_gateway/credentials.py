"""Credentials pod pour serveurs catalogue org (override .env)."""
from __future__ import annotations

import json
import os
import re
import sqlite3
from typing import Any

from mcp_gateway.catalog import ServerSpec
from mcp_gateway.config import settings


def migrate_credentials_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS server_credentials (
            server_id TEXT PRIMARY KEY,
            bearer TEXT NOT NULL DEFAULT '',
            headers_json TEXT NOT NULL DEFAULT '{}',
            url_override TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(server_credentials)")}
    if "url_override" not in cols:
        conn.execute(
            "ALTER TABLE server_credentials ADD COLUMN url_override TEXT NOT NULL DEFAULT ''"
        )
    conn.commit()


def _env_token(spec: ServerSpec | None, server_id: str) -> str:
    token = ""
    if spec and spec.auth_env:
        token = os.environ.get(spec.auth_env, "")
    if not token:
        fallback = {
            "compute": settings.bearer_compute,
            "qgis": settings.bearer_qgis,
            "llm": settings.bearer_llm,
        }
        token = fallback.get(server_id, "")
    return token.strip()


def _server_needs_auth(spec: ServerSpec | None) -> bool:
    if not spec:
        return False
    return bool(spec.auth_required or spec.auth_env)


def _get_stored_row(conn: sqlite3.Connection | None, server_id: str) -> sqlite3.Row | None:
    if not conn:
        return None
    migrate_credentials_schema(conn)
    return conn.execute(
        "SELECT bearer, headers_json, url_override FROM server_credentials WHERE server_id = ?",
        (server_id,),
    ).fetchone()


def resolve_server_url(
    conn: sqlite3.Connection | None,
    server_id: str,
    spec: ServerSpec | None,
) -> tuple[str, bool]:
    default = spec.url if spec else ""
    if not spec or not spec.url_editable:
        return default, False
    row = _get_stored_row(conn, server_id)
    override = (row["url_override"] or "").strip() if row else ""
    if override:
        return override, True
    return default, False


def credential_meta(
    conn: sqlite3.Connection | None,
    server_id: str,
    spec: ServerSpec | None,
) -> dict[str, Any]:
    migrate_credentials_schema(conn) if conn else None
    row = _get_stored_row(conn, server_id) if conn else None
    stored_bearer = bool(row and (row["bearer"] or "").strip())
    stored_headers = False
    if row and row["headers_json"]:
        try:
            hdrs = json.loads(row["headers_json"] or "{}")
            stored_headers = bool(hdrs)
        except json.JSONDecodeError:
            stored_headers = False

    effective_url, url_override = resolve_server_url(conn, server_id, spec)
    env_token = _env_token(spec, server_id)
    if not _server_needs_auth(spec):
        return {
            "auth_env": None,
            "auth_hint": spec.auth_hint if spec else "",
            "auth_required": False,
            "configured": True,
            "source": "stored" if url_override else "none",
            "has_bearer": False,
            "has_headers": False,
            "auth_not_needed": True,
            "url_editable": bool(spec and spec.url_editable),
            "url_default": spec.url if spec else "",
            "url_override": url_override,
            "effective_url": effective_url,
        }

    if stored_bearer or stored_headers or url_override:
        source = "stored"
    elif env_token:
        source = "env"
    else:
        source = "none"

    return {
        "auth_env": spec.auth_env if spec else None,
        "auth_hint": spec.auth_hint if spec else "",
        "auth_required": spec.auth_required if spec else False,
        "configured": source != "none" or url_override,
        "source": source,
        "has_bearer": stored_bearer or bool(env_token),
        "has_headers": stored_headers,
        "url_editable": bool(spec and spec.url_editable),
        "url_default": spec.url if spec else "",
        "url_override": url_override,
        "effective_url": effective_url,
    }


def resolve_server_headers(
    conn: sqlite3.Connection | None,
    server_id: str,
    spec: ServerSpec | None,
) -> dict[str, str]:
    headers: dict[str, str] = {}
    row = _get_stored_row(conn, server_id)
    if row:
        if row["headers_json"]:
            try:
                raw = json.loads(row["headers_json"])
                if isinstance(raw, dict):
                    headers.update({str(k): str(v) for k, v in raw.items()})
            except json.JSONDecodeError:
                pass
        bearer = (row["bearer"] or "").strip()
        if bearer:
            headers["Authorization"] = (
                bearer if bearer.startswith("Bearer ") else f"Bearer {bearer}"
            )

    if "Authorization" not in headers and "authorization" not in headers:
        token = _env_token(spec, server_id)
        if token:
            headers["Authorization"] = (
                token if token.startswith("Bearer ") else f"Bearer {token}"
            )
    return headers


def _validate_url(url: str) -> None:
    if not url:
        return
    if not re.search(r"https?://", url):
        raise ValueError("URL invalide — doit commencer par http:// ou https://")


def set_server_credentials(
    conn: sqlite3.Connection,
    server_id: str,
    *,
    bearer: str | None = "",
    headers: dict[str, str] | None = None,
    url: str | None = None,
    url_editable: bool = False,
) -> dict[str, Any]:
    migrate_credentials_schema(conn)
    headers_json = json.dumps(headers or {}, ensure_ascii=False)
    url_value = ""
    if url_editable and url is not None:
        url_value = url.strip()
        _validate_url(url_value)

    existing = _get_stored_row(conn, server_id)
    if url is None and existing:
        url_value = existing["url_override"] or ""

    # `None` : la clé n'a pas été retouchée. On ne la préremplit plus dans le
    # formulaire — la vider serait donc l'effacer sans l'avoir voulu. Pour
    # l'effacer, il y a DELETE.
    if bearer is None:
        bearer = (existing["bearer"] if existing else "") or ""

    conn.execute(
        """INSERT INTO server_credentials (server_id, bearer, headers_json, url_override, updated_at)
           VALUES (?, ?, ?, ?, datetime('now'))
           ON CONFLICT(server_id) DO UPDATE SET
             bearer = excluded.bearer,
             headers_json = excluded.headers_json,
             url_override = excluded.url_override,
             updated_at = datetime('now')""",
        (server_id, bearer.strip(), headers_json, url_value),
    )
    conn.commit()
    return {"server_id": server_id, "saved": True}


def delete_server_credentials(conn: sqlite3.Connection, server_id: str) -> bool:
    migrate_credentials_schema(conn)
    cur = conn.execute("DELETE FROM server_credentials WHERE server_id = ?", (server_id,))
    conn.commit()
    return cur.rowcount > 0


def get_server_credentials_masked(conn: sqlite3.Connection, server_id: str) -> dict[str, Any]:
    migrate_credentials_schema(conn)
    row = _get_stored_row(conn, server_id)
    if not row:
        return {
            "server_id": server_id,
            "bearer": "",
            "headers": {},
            "url": "",
            "url_override": False,
        }
    headers: dict[str, str] = {}
    try:
        raw = json.loads(row["headers_json"] or "{}")
        if isinstance(raw, dict):
            headers = {str(k): str(v) for k, v in raw.items()}
    except json.JSONDecodeError:
        pass
    bearer = row["bearer"] or ""
    url_override = (row["url_override"] or "").strip()
    # Le champ en clair a disparu, et le nom de la fonction cesse de mentir :
    # elle rendait « bearer » à côté de « bearer_masked », si bien que toute
    # ouverture de la fiche d'un connecteur livrait le jeton amont — à qui
    # tenait la clé, mais aussi à tout jeton OAuth, qui n'a aucune portée.
    # L'interface n'en a pas besoin : elle affiche le masque et n'envoie une
    # valeur que lorsqu'on en saisit une neuve.
    return {
        "server_id": server_id,
        "headers": _sans_secrets(headers),
        "url": url_override,
        "url_override": bool(url_override),
        "bearer_present": bool(bearer),
        "bearer_masked": ("••••" + bearer[-4:]) if len(bearer) > 4 else ("••••" if bearer else ""),
    }


# Un en-tête personnalisé porte souvent le secret que « bearer » ne porte pas :
# c'est ainsi qu'un serveur perso déclare son jeton. Le masquer au même titre.
_ENTETES_SECRETES = ("authorization", "token", "secret", "key", "cookie", "password")


def _sans_secrets(headers: dict[str, str]) -> dict[str, str]:
    masques = {}
    for cle, valeur in (headers or {}).items():
        if any(marque in cle.lower() for marque in _ENTETES_SECRETES):
            v = str(valeur)
            masques[cle] = ("••••" + v[-4:]) if len(v) > 4 else "••••"
        else:
            masques[cle] = valeur
    return masques
