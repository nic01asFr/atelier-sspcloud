"""Flux OAuth 2.1 pour les clients MCP distants (Claude, Cursor).

Patron repris de `sspcloud_mcp.oauth` / qgis-mcp-hub, avec deux écarts :
les jetons émis sont distincts de la clé maître (donc révocables un par un),
et l'état est persisté en SQLite plutôt qu'en JSON.

Endpoints :
  GET  /.well-known/oauth-authorization-server   (RFC 8414)
  GET  /.well-known/oauth-protected-resource     (RFC 9728)
  POST /register                                 (RFC 7591 — DCR)
  GET  /authorize                                (code + PKCE S256)
  POST /authorize/confirm
  POST /oauth/token
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import secrets
import sqlite3
import time
import urllib.parse

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from mcp_gateway.auth import (
    client_name,
    grant_exists,
    issue_token,
    migrate_auth_schema,
    open_owner_session,
    owner_session_valid,
    registered_redirect_uris,
    remember_grant,
    resolve_owner_key,
    est_le_proprietaire,
)

router = APIRouter(tags=["oauth"])

AUTH_CODE_TTL = 600
# Le cookie ne porte plus la clé maître : son nom le disait, il gardait un
# secret permanent dans le navigateur pendant quatre-vingt-dix jours.
COOKIE_NAME = "gateway_owner_session"
SESSION_TTL_SECONDS = 12 * 3600
_pending_codes: dict[str, dict] = {}


def _base_url(request: Request) -> str:
    configured = (request.app.state.settings.host_url or "").rstrip("/")
    if configured:
        return configured
    return str(request.base_url).rstrip("/")


def _db(request: Request) -> sqlite3.Connection:
    conn = request.app.state.db
    migrate_auth_schema(conn)
    return conn


def _owner_key(request: Request) -> str:
    return resolve_owner_key(request.app.state.db, request.app.state.settings)


def _clean_expired_codes() -> None:
    now = time.time()
    for key in [k for k, v in _pending_codes.items() if v["expires"] < now]:
        del _pending_codes[key]


@router.get("/.well-known/oauth-authorization-server")
def authorization_server_metadata(request: Request) -> dict:
    base = _base_url(request)
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/register",
        "grant_types_supported": ["authorization_code", "client_credentials"],
        "response_types_supported": ["code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "none"],
    }


@router.get("/.well-known/oauth-protected-resource")
def protected_resource_metadata(request: Request) -> dict:
    base = _base_url(request)
    return {
        "resource": base,
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["mcp"],
    }


@router.post("/register")
async def register(request: Request) -> JSONResponse:
    """Dynamic Client Registration — clients publics (PKCE), sans secret."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    conn = _db(request)
    client_id = secrets.token_urlsafe(16)
    redirect_uris = body.get("redirect_uris") or []
    conn.execute(
        "INSERT INTO oauth_clients (client_id, redirect_uris, client_name) VALUES (?, ?, ?)",
        (client_id, json.dumps(redirect_uris), str(body.get("client_name") or "")),
    )
    conn.commit()
    return JSONResponse(
        {
            "client_id": client_id,
            "client_id_issued_at": int(time.time()),
            "redirect_uris": redirect_uris,
            "grant_types": body.get("grant_types") or ["authorization_code"],
            "response_types": body.get("response_types") or ["code"],
            "token_endpoint_auth_method": "none",
        },
        status_code=201,
    )


def _issue_code(
    conn: sqlite3.Connection,
    *,
    client_id: str,
    code_challenge: str,
    redirect_uri: str,
    state: str,
) -> RedirectResponse:
    code = secrets.token_urlsafe(32)
    _pending_codes[code] = {
        "client_id": client_id,
        "code_challenge": code_challenge,
        "redirect_uri": redirect_uri,
        "expires": time.time() + AUTH_CODE_TTL,
    }
    params = {"code": code}
    if state:
        params["state"] = state
    return RedirectResponse(f"{redirect_uri}?{urllib.parse.urlencode(params)}", status_code=302)


_FORM_TEMPLATE = """<!DOCTYPE html><html lang="fr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Passerelle — Autorisation</title>
<link rel="icon" type="image/svg+xml" href="/widget/favicon.svg">
<style>
body{{font-family:system-ui,sans-serif;background:#f8fafc;color:#0f172a;display:flex;
justify-content:center;align-items:center;min-height:100vh;margin:0}}
.card{{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:2rem;max-width:420px;width:100%}}
h1{{font-size:1.25rem;margin:0 0 .5rem}}
p{{color:#475569;font-size:.9rem;margin:0 0 1rem}}
input,button{{width:100%;box-sizing:border-box;padding:.65rem;border-radius:8px;
border:1px solid #cbd5e1;font-size:1rem}}
button{{background:#2563eb;color:#fff;border:none;margin-top:.75rem;cursor:pointer}}
.err{{color:#b91c1c;font-size:.85rem;margin-bottom:.75rem}}
</style></head>
<body><div class="card">
<h1>Autoriser cet accès</h1>
<p><strong>{demandeur}</strong> demande à utiliser votre passerelle.<br>
Il sera renvoyé vers <code>{destination}</code>.</p>
{error}
<form action="/authorize/confirm?{query}" method="POST">
{champ_cle}
<button type="submit">{action}</button>
</form></div></body></html>"""

# Le champ n'apparaît que lorsque le propriétaire n'est pas déjà reconnu :
# une session ouverte évite de retaper la clé, mais jamais l'accord explicite.
_CHAMP_CLE = (
    '<input name="owner_key" type="password" required '
    'placeholder="Clé d\'accès de la passerelle" autofocus/>'
)

_REFUS_TEMPLATE = """<!DOCTYPE html><html lang="fr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Demande refusée</title>
<link rel="icon" type="image/svg+xml" href="/widget/favicon.svg">
<style>
body{{font-family:system-ui,sans-serif;background:#f8fafc;color:#0f172a;display:flex;
justify-content:center;align-items:center;min-height:100vh;margin:0}}
.card{{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:2rem;max-width:420px}}
h1{{font-size:1.15rem;margin:0 0 .5rem}}
p{{color:#475569;font-size:.9rem;margin:0}}
</style></head>
<body><div class="card">
<h1>Demande d'accès refusée</h1>
<p>{motif}</p>
</div></body></html>"""


def _authorize_query(params: dict[str, str]) -> str:
    return urllib.parse.urlencode({k: v for k, v in params.items() if v})


def _check_client(conn: sqlite3.Connection, client_id: str, redirect_uri: str) -> str:
    """Vérifie que ce client existe et que cette destination est la sienne.

    Sans ce contrôle, un `client_id` jamais enregistré obtenait un code de
    retour vers l'adresse de son choix : il suffisait de l'inventer. PKCE
    n'y change rien — c'est l'appelant qui choisit le défi, donc il détient
    le vérifieur.

    Retourne un motif de refus, ou une chaîne vide si tout est en règle.
    """
    if not redirect_uri:
        return "Adresse de retour absente."
    declarees = registered_redirect_uris(conn, client_id)
    if declarees is None:
        return "Ce client n'est pas enregistré auprès de cette passerelle."
    if redirect_uri not in declarees:
        return "Cette adresse de retour n'est pas celle déclarée par ce client."
    return ""


@router.get("/authorize", response_model=None)
def authorize(request: Request):
    _clean_expired_codes()
    conn = _db(request)
    q = request.query_params
    redirect_uri = q.get("redirect_uri", "")
    state = q.get("state", "")
    code_challenge = q.get("code_challenge", "")
    client_id = q.get("client_id", "")

    refus = _check_client(conn, client_id, redirect_uri)
    if refus:
        # Refuser ici, jamais en redirigeant : renvoyer l'erreur à une adresse
        # non vérifiée reviendrait à confirmer qu'elle est utilisable.
        return HTMLResponse(
            _REFUS_TEMPLATE.format(motif=html.escape(refus)), status_code=400
        )
    if not code_challenge:
        return HTMLResponse(
            _REFUS_TEMPLATE.format(
                motif="Ce client doit fournir un défi PKCE (code_challenge)."
            ),
            status_code=400,
        )

    # Le cookie ne porte plus la clé maître mais une session sans pouvoir
    # propre, et il ne suffit plus à lui seul : le couple client + destination
    # doit avoir été approuvé une première fois. Sinon une page tierce qui
    # amène le navigateur du propriétaire ici repartait avec un code.
    sid = request.cookies.get(COOKIE_NAME, "")
    if owner_session_valid(conn, sid) and grant_exists(conn, client_id, redirect_uri):
        return _issue_code(
            conn,
            client_id=client_id,
            code_challenge=code_challenge,
            redirect_uri=redirect_uri,
            state=state,
        )

    query = _authorize_query(
        {
            "response_type": q.get("response_type", "code"),
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": q.get("code_challenge_method", "S256"),
        }
    )
    connu = owner_session_valid(conn, sid)
    return HTMLResponse(
        _FORM_TEMPLATE.format(
            error="",
            query=html.escape(query),
            demandeur=html.escape(client_name(conn, client_id) or client_id),
            destination=html.escape(redirect_uri),
            champ_cle="" if connu else _CHAMP_CLE,
            action="Autoriser" if connu else "Vérifier et autoriser",
        )
    )


@router.post("/authorize/confirm", response_model=None)
def authorize_confirm(request: Request, owner_key: str = Form(default="")):
    conn = _db(request)
    q = request.query_params
    redirect_uri = q.get("redirect_uri", "")
    client_id = q.get("client_id", "")

    # Le contrôle du client est refait ici : la page précédente ne prouve rien,
    # ce point d'entrée est atteignable directement.
    refus = _check_client(conn, client_id, redirect_uri)
    if refus:
        return HTMLResponse(_REFUS_TEMPLATE.format(motif=html.escape(refus)), status_code=400)
    if not q.get("code_challenge", ""):
        return HTMLResponse(
            _REFUS_TEMPLATE.format(motif="Défi PKCE absent."), status_code=400
        )

    sid = request.cookies.get(COOKIE_NAME, "")
    reconnu = owner_session_valid(conn, sid)
    # Une session ouverte dispense de retaper la clé, jamais de consentir.
    # La clé maître, et elle seule : autoriser un client neuf est un geste
    # de propriétaire. Un jeton qui pourrait consentir se multiplierait.
    if not reconnu and not est_le_proprietaire(conn, owner_key, _owner_key(request)):
        query = _authorize_query(dict(q))
        return HTMLResponse(
            _FORM_TEMPLATE.format(
                error='<div class="err">Clé invalide.</div>',
                query=html.escape(query),
                demandeur=html.escape(client_name(conn, client_id) or client_id),
                destination=html.escape(redirect_uri),
                champ_cle=_CHAMP_CLE,
                action="Vérifier et autoriser",
            ),
            status_code=401,
        )

    remember_grant(conn, client_id, redirect_uri)
    response = _issue_code(
        conn,
        client_id=client_id,
        code_challenge=q.get("code_challenge", ""),
        redirect_uri=redirect_uri,
        state=q.get("state", ""),
    )
    if not reconnu:
        # Le cookie ne transporte plus la clé maître : un identifiant de
        # session sans pouvoir propre, révocable, et qui ne sert qu'ici.
        response.set_cookie(
            COOKIE_NAME,
            open_owner_session(conn, SESSION_TTL_SECONDS),
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/",
        )
    return response


def _pkce_ok(verifier: str, challenge: str) -> bool:
    # Un défi absent rendait « vrai » : il suffisait de ne pas en envoyer pour
    # que la vérification disparaisse. PKCE n'est pas une option de la
    # révision servie, et /authorize refuse désormais une demande sans défi.
    if not challenge or not verifier:
        return False
    digest = hashlib.sha256(verifier.encode()).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return secrets.compare_digest(computed, challenge)


@router.post("/oauth/token")
async def oauth_token(request: Request) -> JSONResponse:
    ctype = request.headers.get("content-type", "")
    raw = await request.body()
    if "application/json" in ctype:
        try:
            form = json.loads(raw.decode() or "{}")
        except Exception:
            form = {}
    else:
        form = {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode("utf-8", "replace")).items()}

    conn = _db(request)
    grant = form.get("grant_type", "")

    if grant == "authorization_code":
        code = form.get("code", "")
        pending = _pending_codes.pop(code, None)
        if not pending or pending["expires"] < time.time():
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        if not _pkce_ok(form.get("code_verifier", ""), pending.get("code_challenge", "")):
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        token = issue_token(conn, client_id=pending.get("client_id", ""), label="authorization_code")
        return JSONResponse(
            {"access_token": token, "token_type": "bearer", "expires_in": 90 * 24 * 3600}
        )

    if grant == "client_credentials":
        secret = form.get("client_secret", "")
        # `validate_credential` acceptait aussi un jeton déjà émis : son porteur
        # en frappait donc autant qu'il voulait, sur un point d'entrée public.
        # Révoquer ne fermait rien — le voleur en avait d'autres.
        if not est_le_proprietaire(conn, secret, _owner_key(request)):
            return JSONResponse({"error": "invalid_client"}, status_code=401)
        token = issue_token(conn, label="client_credentials")
        return JSONResponse(
            {"access_token": token, "token_type": "bearer", "expires_in": 90 * 24 * 3600}
        )

    return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
