"""Authentification gateway — clé propriétaire (owner_lock) et jetons OAuth.

Modèle : un pod par utilisateur. Le propriétaire détient une clé maître
(`GATEWAY_OWNER_KEY`) ; les clients MCP distants obtiennent des jetons dédiés
via le flux OAuth (voir `mcp_gateway.oauth`), révocables sans toucher à la
clé maître.

Surfaces protégées quand `owner_lock` est actif : `/mcp` et `/api/v1/*`.
Restent publics : `/health`, le widget statique et les endpoints du flux OAuth.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import stat
import time
from pathlib import Path

from mcp_gateway.config import Settings

OWNER_KEY_META = "owner_key"
TOKEN_TTL_SECONDS = 90 * 24 * 3600

PUBLIC_PREFIXES = (
    "/health",
    "/widget",
    "/.well-known/",
    "/authorize",
    "/oauth/",
    "/register",
    "/favicon.ico",
    # Claude Code colle `…/mcp` : il interpolé le chemin dans le well-known
    # (RFC 9728 / RFC 8414) et cherche `/mcp/authorize`. Sans ces préfixes,
    # le verrou propriétaire recouvre le flux d'autorisation.
    "/mcp/.well-known/",
    "/mcp/authorize",
)


# Ce qu'un porteur a le droit de faire. La clé maître ouvre tout ; un jeton
# OAuth ne vaut que pour /mcp — c'est ce que les métadonnées RFC 9728
# annonçaient déjà (« scopes_supported: ["mcp"] ») sans que rien ne le vérifie.
PORTEE_PROPRIETAIRE = "owner"
PORTEE_MCP = "mcp"


def migrate_auth_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS oauth_clients (
            client_id TEXT PRIMARY KEY,
            redirect_uris TEXT NOT NULL DEFAULT '[]',
            client_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS oauth_tokens (
            token TEXT PRIMARY KEY,
            client_id TEXT NOT NULL DEFAULT '',
            label TEXT NOT NULL DEFAULT '',
            expires_at REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- Le navigateur du propriétaire portait la clé maître elle-même dans
        -- un cookie de 90 jours. Elle est désormais remplacée par un
        -- identifiant de session sans pouvoir propre, révocable, et qui ne
        -- vaut que pour reconnaître le propriétaire devant /authorize.
        CREATE TABLE IF NOT EXISTS oauth_sessions (
            sid TEXT PRIMARY KEY,
            expires_at REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- Ce que le propriétaire a déjà accordé, et à qui. Sans cette trace,
        -- un client jamais vu obtenait un code au premier passage.
        CREATE TABLE IF NOT EXISTS oauth_grants (
            client_id TEXT NOT NULL,
            redirect_uri TEXT NOT NULL,
            granted_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (client_id, redirect_uri)
        );
        """
    )
    conn.commit()


def registered_redirect_uris(conn: sqlite3.Connection, client_id: str) -> list[str] | None:
    """Adresses de retour déclarées par ce client, ou None s'il est inconnu.

    La table était écrite à l'enregistrement et relue nulle part : n'importe
    quel `client_id` inventé passait, avec n'importe quelle destination.
    """
    import json as _json

    if not client_id:
        return None
    row = conn.execute(
        "SELECT redirect_uris FROM oauth_clients WHERE client_id = ?", (client_id,)
    ).fetchone()
    if not row:
        return None
    try:
        uris = _json.loads(row["redirect_uris"] or "[]")
    except ValueError:
        return []
    return [str(u) for u in uris] if isinstance(uris, list) else []


def client_name(conn: sqlite3.Connection, client_id: str) -> str:
    row = conn.execute(
        "SELECT client_name FROM oauth_clients WHERE client_id = ?", (client_id,)
    ).fetchone()
    return (row["client_name"] if row else "") or ""


def open_owner_session(conn: sqlite3.Connection, ttl_seconds: int) -> str:
    sid = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO oauth_sessions (sid, expires_at) VALUES (?, ?)",
        (sid, time.time() + ttl_seconds),
    )
    conn.commit()
    return sid


def owner_session_valid(conn: sqlite3.Connection, sid: str) -> bool:
    if not sid:
        return False
    conn.execute("DELETE FROM oauth_sessions WHERE expires_at < ?", (time.time(),))
    conn.commit()
    row = conn.execute(
        "SELECT expires_at FROM oauth_sessions WHERE sid = ?", (sid,)
    ).fetchone()
    return bool(row and row["expires_at"] > time.time())


def close_owner_session(conn: sqlite3.Connection, sid: str) -> bool:
    """Ferme une session côté serveur, et pas seulement dans le navigateur.

    Sans cela, se déconnecter n'enlevait qu'un cookie : le même identifiant
    rejoué depuis ailleurs restait valable jusqu'à son expiration.
    """
    if not sid:
        return False
    curseur = conn.execute("DELETE FROM oauth_sessions WHERE sid = ?", (sid,))
    conn.commit()
    return curseur.rowcount > 0


def remember_grant(conn: sqlite3.Connection, client_id: str, redirect_uri: str) -> None:
    conn.execute(
        """INSERT INTO oauth_grants (client_id, redirect_uri) VALUES (?, ?)
           ON CONFLICT(client_id, redirect_uri) DO NOTHING""",
        (client_id, redirect_uri),
    )
    conn.commit()


def grant_exists(conn: sqlite3.Connection, client_id: str, redirect_uri: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM oauth_grants WHERE client_id = ? AND redirect_uri = ?",
        (client_id, redirect_uri),
    ).fetchone()
    return bool(row)


def _meta_get(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM gateway_meta WHERE key = ?", (key,)).fetchone()
    return (row["value"] if row else "") or ""


def _meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """INSERT INTO gateway_meta (key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        (key, value),
    )
    conn.commit()


def resolve_owner_key(conn: sqlite3.Connection, cfg: Settings) -> str:
    """Clé maître : variable d'environnement, sinon valeur persistée, sinon générée.

    La génération automatique évite qu'un déploiement avec `owner_lock` actif mais
    sans clé configurée démarre sans protection. La clé retenue est toujours
    persistée, y compris lorsqu'elle vient de l'environnement : c'est la seule
    manière pour le propriétaire de la retrouver depuis son pod s'il l'a perdue.
    """
    configured = (cfg.owner_key or "").strip()
    if configured:
        if _meta_get(conn, OWNER_KEY_META) != configured:
            _meta_set(conn, OWNER_KEY_META, configured)
        return configured
    stored = _meta_get(conn, OWNER_KEY_META)
    if stored:
        return stored
    generated = secrets.token_urlsafe(32)
    _meta_set(conn, OWNER_KEY_META, generated)
    return generated


def owner_key_file(cfg: Settings) -> Path:
    """Emplacement du fichier de récupération, à côté de la base."""
    return Path(cfg.db_path).resolve().parent / "owner_key.txt"


def write_owner_key_file(cfg: Settings, key: str) -> Path | None:
    """Dépose la clé dans le pod pour que le propriétaire puisse la relire.

    Écrit en 0600 : lisible par le compte qui fait tourner le service, pas au-delà.
    Un échec (volume en lecture seule, permissions) n'empêche pas le démarrage —
    la clé reste récupérable en base.
    """
    path = owner_key_file(cfg)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{key}\n", encoding="utf-8")
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        return path
    except OSError:
        return None


def _ajouter_colonne_portee(conn: sqlite3.Connection) -> None:
    """Ajoute `scope` aux bases antérieures, sans les recréer.

    Les jetons déjà émis n'avaient pas de portée : ils prennent « mcp », qui
    est ce que le flux OAuth délivre. Un jeton en place cesse donc d'ouvrir
    /api/v1 au prochain démarrage — c'est l'objet du correctif, et cela vaut
    d'être su plutôt que découvert.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(oauth_tokens)")}
    if "scope" not in cols:
        conn.execute(
            f"ALTER TABLE oauth_tokens ADD COLUMN scope TEXT NOT NULL DEFAULT '{PORTEE_MCP}'"
        )
        conn.commit()


def issue_token(
    conn: sqlite3.Connection,
    *,
    client_id: str = "",
    label: str = "",
    ttl: int = TOKEN_TTL_SECONDS,
    scope: str = PORTEE_MCP,
) -> str:
    migrate_auth_schema(conn)
    _ajouter_colonne_portee(conn)
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO oauth_tokens (token, client_id, label, expires_at, scope)"
        " VALUES (?, ?, ?, ?, ?)",
        (token, client_id, label, time.time() + ttl, scope),
    )
    conn.commit()
    return token


def revoke_token(conn: sqlite3.Connection, token: str) -> bool:
    migrate_auth_schema(conn)
    cur = conn.execute("DELETE FROM oauth_tokens WHERE token = ?", (token,))
    conn.commit()
    return cur.rowcount > 0


def revoquer_tous_les_jetons(conn: sqlite3.Connection) -> int:
    """Retire tous les jetons émis. Rend combien sont tombés.

    Appelé quand la clé maître est renouvelée : elle se renouvelle parce
    qu'elle a fui, et ce qu'elle a accordé ne doit pas lui survivre.
    """
    migrate_auth_schema(conn)
    cur = conn.execute("DELETE FROM oauth_tokens")
    conn.commit()
    return cur.rowcount


# Un client s'enregistre sans rien prouver — le flux le veut ainsi, et la vraie
# porte est le consentement. Mais rien ne bornait la table : elle grossissait
# sans fin, sous le nom que l'appelant choisit, et personne ne la regardait.
PLAFOND_CLIENTS = 50
DELAI_CLIENT_INERTE_S = 24 * 3600


def purger_clients_inertes(
    conn: sqlite3.Connection, delai_s: int = DELAI_CLIENT_INERTE_S
) -> int:
    """Efface les clients que le propriétaire n'a jamais reconnus.

    Un client sans accord et sans jeton n'est qu'une ligne déposée par un
    inconnu : passé le délai, elle ne dit plus rien d'utile. Ce qui a été
    accordé une fois, ou qui porte un jeton, reste — c'est une trace.
    """
    migrate_auth_schema(conn)
    cur = conn.execute(
        """
        DELETE FROM oauth_clients
         WHERE created_at < datetime('now', ?)
           AND client_id NOT IN (SELECT client_id FROM oauth_grants)
           AND client_id NOT IN (SELECT client_id FROM oauth_tokens)
        """,
        (f"-{int(delai_s)} seconds",),
    )
    conn.commit()
    return cur.rowcount


def compter_clients(conn: sqlite3.Connection) -> int:
    migrate_auth_schema(conn)
    row = conn.execute("SELECT COUNT(*) AS n FROM oauth_clients").fetchone()
    return int(row["n"] if row else 0)


def lister_clients(conn: sqlite3.Connection) -> list[dict]:
    """Qui s'est enregistré, qui a été accordé, qui détient un jeton.

    Sans cette vue, le propriétaire ne pouvait ni voir ni révoquer ce qu'il
    avait branché : la seule sortie était de renouveler la clé, ce qui coupe
    tout le reste avec.
    """
    migrate_auth_schema(conn)
    _ajouter_colonne_portee(conn)
    rows = conn.execute(
        """
        SELECT c.client_id, c.client_name, c.redirect_uris, c.created_at,
               (SELECT COUNT(*) FROM oauth_grants g
                 WHERE g.client_id = c.client_id) AS accords,
               (SELECT COUNT(*) FROM oauth_tokens t
                 WHERE t.client_id = c.client_id
                   AND t.expires_at > ?) AS jetons
          FROM oauth_clients c
         ORDER BY c.created_at DESC
        """,
        (time.time(),),
    ).fetchall()
    clients = []
    for row in rows:
        try:
            uris = json.loads(row["redirect_uris"] or "[]")
        except (TypeError, ValueError):
            uris = []
        clients.append(
            {
                "client_id": row["client_id"],
                "nom": row["client_name"] or "",
                "destinations": uris if isinstance(uris, list) else [],
                "enregistre_le": row["created_at"],
                "accorde": bool(row["accords"]),
                "jetons": int(row["jetons"] or 0),
            }
        )
    return clients


def revoquer_client(conn: sqlite3.Connection, client_id: str) -> bool:
    """Retire un client, ses jetons et l'accord qu'il avait obtenu.

    Les trois ensemble : laisser l'accord derrière lui rendrait la
    réautorisation silencieuse au client suivant qui reprendrait son
    identifiant.
    """
    migrate_auth_schema(conn)
    cur = conn.execute("DELETE FROM oauth_clients WHERE client_id = ?", (client_id,))
    conn.execute("DELETE FROM oauth_tokens WHERE client_id = ?", (client_id,))
    conn.execute("DELETE FROM oauth_grants WHERE client_id = ?", (client_id,))
    conn.commit()
    return cur.rowcount > 0


def _portee_du_jeton(conn: sqlite3.Connection, token: str) -> str | None:
    migrate_auth_schema(conn)
    _ajouter_colonne_portee(conn)
    row = conn.execute(
        "SELECT expires_at, scope FROM oauth_tokens WHERE token = ?", (token,)
    ).fetchone()
    if not row:
        return None
    if row["expires_at"] < time.time():
        conn.execute("DELETE FROM oauth_tokens WHERE token = ?", (token,))
        conn.commit()
        return None
    return str(row["scope"] or PORTEE_MCP)


def portee_du_porteur(
    conn: sqlite3.Connection, token: str, owner_key: str
) -> str | None:
    """Ce que ce porteur a le droit de faire — ou rien s'il n'est pas reconnu.

    La distinction manquait : un jeton OAuth donné à un assistant distant valait
    la clé maître, donc lisait les identifiants de tous les services amont et
    reconfigurait la passerelle. Le seul geste que le flux OAuth prétend
    accorder est pourtant l'accès à /mcp.
    """
    token = (token or "").strip()
    if not token:
        return None
    if owner_key and secrets.compare_digest(token, owner_key):
        return PORTEE_PROPRIETAIRE
    return _portee_du_jeton(conn, token)


def est_le_proprietaire(conn: sqlite3.Connection, token: str, owner_key: str) -> bool:
    """Seule la clé maître ouvre l'administration et le consentement OAuth."""
    return portee_du_porteur(conn, token, owner_key) == PORTEE_PROPRIETAIRE


def validate_credential(conn: sqlite3.Connection, token: str, owner_key: str) -> bool:
    """Vrai si le jeton est la clé maître ou un jeton OAuth encore valide."""
    return portee_du_porteur(conn, token, owner_key) is not None


def bearer_from_header(header_value: str | None) -> str:
    if not header_value:
        return ""
    value = header_value.strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return value


def client_key(token: str | None) -> str:
    """Identifiant stable d'un client, dérivé de son jeton.

    Sert à retrouver ses préférences entre deux sessions MCP. Le jeton lui-même
    n'est jamais conservé : seul son condensé circule.
    """
    token = (token or "").strip()
    if not token:
        return ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]


def is_public_path(path: str) -> bool:
    if path == "/":
        return True
    return path.startswith(PUBLIC_PREFIXES)
