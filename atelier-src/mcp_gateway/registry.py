"""Registre perso MCP — format JSON compatible BigMCP / Cursor mcpServers."""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Literal

RuntimeKind = Literal["remote", "stdio"]


@dataclass
class RegistryServer:
    server_id: str
    config: dict[str, Any]
    runtime: RuntimeKind
    url: str | None
    transport: str
    name: str
    description: str
    prefix: str
    headers: dict[str, str] = field(default_factory=dict)
    auth_header: str | None = None
    supported: bool = True
    error: str | None = None


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "server"


def _infer_transport(url: str) -> str:
    if url.rstrip("/").endswith("/sse"):
        return "sse"
    return "streamable-http"


def _headers_from_config(config: dict[str, Any]) -> dict[str, str]:
    raw = config.get("headers") or {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def _auth_from_config(headers: dict[str, str]) -> str | None:
    auth = headers.get("Authorization") or headers.get("authorization")
    if not auth:
        return None
    return str(auth)


def build_registry_config_from_simple(
    *,
    server_id: str,
    url: str,
    name: str = "",
    description: str = "",
    prefix: str = "",
    bearer: str = "",
) -> dict[str, Any]:
    """Construit un bloc mcpServers à partir d'un formulaire guidé."""
    meta: dict[str, Any] = {"name": name.strip() or server_id}
    if description.strip():
        meta["description"] = description.strip()
    if prefix.strip():
        meta["prefix"] = prefix.strip()
    cfg: dict[str, Any] = {"url": url.strip(), "_metadata": meta}
    token = bearer.strip()
    if token:
        auth = token if token.lower().startswith("bearer ") else f"Bearer {token}"
        cfg["headers"] = {"Authorization": auth}
    return cfg


def normalize_server_config(server_id: str, config: dict[str, Any]) -> RegistryServer:
    meta = config.get("_metadata") if isinstance(config.get("_metadata"), dict) else {}
    name = str(meta.get("name") or server_id)
    description = str(meta.get("description") or "")
    prefix = _slug(str(meta.get("prefix") or server_id))

    if config.get("url"):
        url = str(config["url"]).strip()
        transport = _infer_transport(url)
        headers = _headers_from_config(config)
        return RegistryServer(
            server_id=server_id,
            config=config,
            runtime="remote",
            url=url,
            transport=transport,
            name=name,
            description=description,
            prefix=prefix,
            headers=headers,
            auth_header=_auth_from_config(headers),
            supported=True,
        )

    if config.get("command"):
        # Stdio : matérialisé pour Claude Code CLI ; le pool gateway ne sonde pas ces upstreams.
        return RegistryServer(
            server_id=server_id,
            config=config,
            runtime="stdio",
            url=None,
            transport="stdio",
            name=name,
            description=description,
            prefix=prefix,
            supported=True,
        )

    raise ValueError(f"Config '{server_id}' : url ou command requis")


def parse_registry_import(raw: str | dict[str, Any]) -> dict[str, RegistryServer]:
    """Parse un bloc mcpServers BigMCP / Cursor."""
    data = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(data, dict):
        raise ValueError("JSON invalide : objet attendu")

    servers_block: dict[str, Any]
    if "mcpServers" in data and isinstance(data["mcpServers"], dict):
        servers_block = data["mcpServers"]
    elif all(isinstance(v, dict) for v in data.values()):
        servers_block = data
    else:
        raise ValueError('Format attendu : { "mcpServers": { "id": { ... } } }')

    if not servers_block:
        raise ValueError("Aucun serveur dans le registre")

    out: dict[str, RegistryServer] = {}
    for server_id, cfg in servers_block.items():
        if not isinstance(cfg, dict):
            raise ValueError(f"Config '{server_id}' invalide")
        out[server_id] = normalize_server_config(server_id, cfg)
    return out


def export_registry(servers: list[RegistryServer]) -> dict[str, Any]:
    """Le registre tel qu'on l'affiche — sans les secrets qu'il transporte.

    Un serveur perso déclare son jeton dans le bloc `headers` de sa config.
    Renvoyer la config telle quelle livrait donc l'Authorization complète à
    chaque affichage du catalogue.
    """
    block: dict[str, Any] = {}
    for srv in servers:
        block[srv.server_id] = config_sans_secrets(srv.config)
    return {"mcpServers": block}


_ENTETES_SECRETES = ("authorization", "token", "secret", "key", "cookie", "password")


def config_sans_secrets(config: dict[str, Any]) -> dict[str, Any]:
    """Copie d'une config de serveur perso, en-têtes sensibles masqués."""
    if not isinstance(config, dict):
        return config
    propre = dict(config)
    entetes = propre.get("headers")
    if isinstance(entetes, dict):
        propre["headers"] = {
            cle: (
                ("••••" + str(val)[-4:]) if len(str(val)) > 4 else "••••"
            )
            if any(marque in cle.lower() for marque in _ENTETES_SECRETES)
            else val
            for cle, val in entetes.items()
        }
    return propre


def legacy_row_to_config(row: sqlite3.Row) -> dict[str, Any]:
    meta = {"name": row["name"], "prefix": row["prefix"]}
    return {
        "url": row["mcp_url"],
        "_metadata": meta,
    }


def row_to_registry_server(row: sqlite3.Row) -> RegistryServer:
    if row["config_json"]:
        cfg = json.loads(row["config_json"])
        return normalize_server_config(row["server_id"] or row["id"], cfg)
    return normalize_server_config(row["server_id"] or row["id"], legacy_row_to_config(row))


def migrate_sidecars_schema(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sidecars)").fetchall()}
    if "config_json" not in cols:
        conn.execute("ALTER TABLE sidecars ADD COLUMN config_json TEXT")
    if "server_id" not in cols:
        conn.execute("ALTER TABLE sidecars ADD COLUMN server_id TEXT")
    conn.commit()

    rows = conn.execute("SELECT * FROM sidecars WHERE config_json IS NULL OR config_json = ''").fetchall()
    for row in rows:
        sid = row["server_id"] or row["id"]
        cfg = legacy_row_to_config(row)
        conn.execute(
            "UPDATE sidecars SET server_id = ?, config_json = ? WHERE id = ?",
            (sid, json.dumps(cfg, ensure_ascii=False), row["id"]),
        )
    conn.commit()


def list_registry_servers(conn: sqlite3.Connection) -> list[RegistryServer]:
    migrate_sidecars_schema(conn)
    rows = conn.execute("SELECT * FROM sidecars ORDER BY created_at DESC").fetchall()
    servers: list[RegistryServer] = []
    for row in rows:
        try:
            servers.append(row_to_registry_server(row))
        except ValueError as exc:
            servers.append(
                RegistryServer(
                    server_id=row["server_id"] or row["id"],
                    config={},
                    runtime="remote",
                    url=None,
                    transport="streamable-http",
                    name=row["name"],
                    description="",
                    prefix=row["prefix"],
                    supported=False,
                    error=str(exc),
                )
            )
    return servers


def upsert_registry_server(conn: sqlite3.Connection, server: RegistryServer) -> None:
    migrate_sidecars_schema(conn)
    conn.execute(
        """INSERT INTO sidecars (id, server_id, name, mcp_url, transport, prefix, config_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             server_id = excluded.server_id,
             name = excluded.name,
             mcp_url = excluded.mcp_url,
             transport = excluded.transport,
             prefix = excluded.prefix,
             config_json = excluded.config_json""",
        (
            server.server_id,
            server.server_id,
            server.name,
            server.url or "",
            server.transport,
            server.prefix,
            json.dumps(server.config, ensure_ascii=False),
        ),
    )
    conn.commit()


def delete_registry_server(conn: sqlite3.Connection, server_id: str) -> bool:
    migrate_sidecars_schema(conn)
    cur = conn.execute(
        "DELETE FROM sidecars WHERE server_id = ? OR id = ?",
        (server_id, server_id),
    )
    conn.commit()
    return cur.rowcount > 0


def import_registry(conn: sqlite3.Connection, raw: str | dict[str, Any]) -> list[RegistryServer]:
    parsed = parse_registry_import(raw)
    for server in parsed.values():
        upsert_registry_server(conn, server)
    return list_registry_servers(conn)


def get_registry_server(conn: sqlite3.Connection, server_id: str) -> RegistryServer | None:
    for entry in list_registry_servers(conn):
        if entry.server_id == server_id:
            return entry
    return None


MASQUE = "••••"


def update_registry_server_config(
    conn: sqlite3.Connection, server_id: str, config: dict[str, Any]
) -> RegistryServer:
    """Enregistre une config, en rendant à un masque la valeur qu'il cachait.

    L'interface affiche la config sans ses secrets — sinon toute ouverture de
    la fiche livre le jeton. Elle renvoie donc ce qu'elle a reçu, masques
    compris, et sans cette restauration on écraserait la clé par des points.
    """
    config = _rendre_les_secrets(conn, server_id, config)
    server = normalize_server_config(server_id, config)
    upsert_registry_server(conn, server)
    return server


def _rendre_les_secrets(
    conn: sqlite3.Connection, server_id: str, config: dict[str, Any]
) -> dict[str, Any]:
    entetes = (config or {}).get("headers")
    if not isinstance(entetes, dict) or not any(
        isinstance(v, str) and v.startswith(MASQUE) for v in entetes.values()
    ):
        return config
    ancien = get_registry_server(conn, server_id)
    anciens_entetes = (ancien.config.get("headers") or {}) if ancien else {}
    rendu = dict(config)
    rendu["headers"] = {
        cle: (anciens_entetes.get(cle, "") if isinstance(val, str) and val.startswith(MASQUE) else val)
        for cle, val in entetes.items()
    }
    return rendu


def registry_pool_key(server_id: str) -> str:
    return f"registry:{server_id}"
