from __future__ import annotations

import sqlite3
from pathlib import Path

from mcp_gateway.config import settings
from mcp_gateway.credentials import migrate_credentials_schema
from mcp_gateway.registry import migrate_sidecars_schema
from mcp_gateway.server_enable import migrate_server_enable_schema
from mcp_gateway.profiles import migrate_user_profiles_schema
from mcp_gateway.tool_cache import migrate_tool_cache_schema

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS sidecars (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    mcp_url TEXT NOT NULL,
    transport TEXT NOT NULL DEFAULT 'streamable-http',
    prefix TEXT NOT NULL,
    auth_ref TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS compositions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'temporary',
    definition_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    promoted_at TEXT
);

CREATE TABLE IF NOT EXISTS composition_runs (
    id TEXT PRIMARY KEY,
    composition_id TEXT NOT NULL,
    status TEXT NOT NULL,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (composition_id) REFERENCES compositions(id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event TEXT NOT NULL,
    detail_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS gateway_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_pins (
    tool_name TEXT PRIMARY KEY,
    use_count INTEGER NOT NULL DEFAULT 0,
    pinned INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    migrate_sidecars_schema(conn)
    migrate_credentials_schema(conn)
    migrate_server_enable_schema(conn)
    migrate_user_profiles_schema(conn)
    migrate_tool_cache_schema(conn)
    return conn


def log_audit(conn: sqlite3.Connection, event: str, detail: dict | None = None) -> None:
    import json

    conn.execute(
        "INSERT INTO audit_log (event, detail_json) VALUES (?, ?)",
        (event, json.dumps(detail or {}, ensure_ascii=False)),
    )
    conn.commit()
