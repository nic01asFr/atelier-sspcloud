"""Activation utilisateur des serveurs catalogue org et registre perso (SQLite pod)."""
from __future__ import annotations

import sqlite3

SCOPE_ORG = "org"
SCOPE_REGISTRY = "registry"


def migrate_server_enable_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS server_enabled (
            scope TEXT NOT NULL,
            server_id TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (scope, server_id)
        )
        """
    )
    conn.commit()


def is_enabled(conn: sqlite3.Connection | None, scope: str, server_id: str) -> bool:
    if not conn:
        return True
    migrate_server_enable_schema(conn)
    row = conn.execute(
        "SELECT enabled FROM server_enabled WHERE scope = ? AND server_id = ?",
        (scope, server_id),
    ).fetchone()
    if row is None:
        return True
    return bool(row["enabled"])


def is_org_enabled(conn: sqlite3.Connection | None, server_id: str) -> bool:
    return is_enabled(conn, SCOPE_ORG, server_id)


def is_registry_enabled(conn: sqlite3.Connection | None, server_id: str) -> bool:
    return is_enabled(conn, SCOPE_REGISTRY, server_id)


def set_enabled(conn: sqlite3.Connection, scope: str, server_id: str, enabled: bool) -> bool:
    migrate_server_enable_schema(conn)
    conn.execute(
        """INSERT INTO server_enabled (scope, server_id, enabled, updated_at)
           VALUES (?, ?, ?, datetime('now'))
           ON CONFLICT(scope, server_id) DO UPDATE SET
             enabled = excluded.enabled,
             updated_at = excluded.updated_at""",
        (scope, server_id, 1 if enabled else 0),
    )
    conn.commit()
    return enabled


def filter_enabled_org(conn: sqlite3.Connection | None, server_ids: list[str]) -> list[str]:
    return [sid for sid in server_ids if is_org_enabled(conn, sid)]
