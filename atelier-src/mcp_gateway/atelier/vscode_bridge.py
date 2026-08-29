"""Handoff Atelier → code-server (pod dédié) sans resaisie du mot de passe."""

from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.ui_settings import load_ui_settings, resolve_vscode_url

log = logging.getLogger("atelier.vscode_bridge")

COOKIE_NAME = "atelier_owner"
VSCODE_PASSWORD_FILE = "vscode_password"


def vscode_password_path(settings: AtelierSettings) -> Path:
    return settings.secrets_dir / VSCODE_PASSWORD_FILE


def load_vscode_password(settings: AtelierSettings) -> str | None:
    path = vscode_password_path(settings)
    if not path.is_file():
        return None
    key = path.read_text(encoding="utf-8").strip()
    return key or None


def save_vscode_password(settings: AtelierSettings, password: str | None) -> None:
    path = vscode_password_path(settings)
    if password is None or password == "":
        if path.is_file():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(password.strip() + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def cookie_domain_for(vscode_url: str, atelier_host: str | None) -> str | None:
    """Domaine parent partagé atelier ↔ vscode (ex. .user.lab.sspcloud.fr)."""
    try:
        vs_host = urlparse(vscode_url).hostname or ""
    except Exception:  # noqa: BLE001
        return None
    if not vs_host or not atelier_host:
        return None
    vs_parts = vs_host.split(".")
    at_parts = atelier_host.split(".")
    # besoin d'au moins *.user.lab.sspcloud.fr
    if len(vs_parts) < 4 or len(at_parts) < 4:
        return None
    # suffixe commun à partir de user.lab...
    for i in range(len(vs_parts)):
        suffix = ".".join(vs_parts[i:])
        if atelier_host.endswith(suffix) and suffix.count(".") >= 2:
            return "." + suffix
    return None


def folder_abs(settings: AtelierSettings, slug: str) -> str:
    return str((settings.projects_dir / slug).resolve())


def workbench_url(vscode_url: str, folder: str, session_id: str | None) -> str:
    base = vscode_url.rstrip("/")
    q = f"folder={quote(folder, safe='')}"
    # hint pour reprises manuelles / futurs helpers in-IDE
    if session_id:
        q += f"&atelier_session={quote(session_id, safe='')}"
    return f"{base}/?{q}"


def claude_extension_uri(session_id: str) -> str:
    return f"vscode://anthropic.claude-code/open?session={quote(session_id, safe='')}"


def write_resume_sidecar(settings: AtelierSettings, slug: str, session_id: str) -> Path:
    """Fichier markdown + tâche folderOpen pour tenter l’URI extension dans code-server."""
    root = settings.projects_dir / slug / ".atelier"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "OPEN_CLAUDE_SESSION.md"
    uri = claude_extension_uri(session_id)
    path.write_text(
        "\n".join(
            [
                "# Session Atelier",
                "",
                f"Session: `{session_id}`",
                "",
                f"[Ouvrir l’extension Claude Code sur cette session]({uri})",
                "",
                "Si le lien ne s’ouvre pas : Palette de commandes → Claude Code → reprendre la session.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    vscode_dir = settings.projects_dir / slug / ".vscode"
    vscode_dir.mkdir(parents=True, exist_ok=True)
    tasks = vscode_dir / "tasks.json"
    # runOn folderOpen : tente d’ouvrir l’URI dans l’instance code-server (pas le desktop)
    cmd = f"code-server --open-url '{uri}' || true"
    tasks.write_text(
        "{\n"
        '  "version": "2.0.0",\n'
        '  "tasks": [\n'
        "    {\n"
        '      "label": "Atelier: Claude Code session",\n'
        '      "type": "shell",\n'
        f'      "command": {cmd!r},\n'
        '      "problemMatcher": [],\n'
        '      "presentation": { "reveal": "silent", "panel": "shared", "showReuseMessage": false },\n'
        '      "runOptions": { "runOn": "folderOpen" }\n'
        "    }\n"
        "  ]\n"
        "}\n",
        encoding="utf-8",
    )
    return path


async def fetch_code_server_session_cookie(
    vscode_url: str,
    password: str,
    *,
    href: str,
) -> tuple[str, str] | None:
    """
    POST /login côté serveur. Retourne (cookie_name, cookie_value) ou None.
    """
    login = vscode_url.rstrip("/") + "/login"
    async with httpx.AsyncClient(follow_redirects=False, timeout=20.0) as client:
        resp = await client.post(
            login,
            data={"password": password, "base": ".", "href": href},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    # Succès typique : 302 + Set-Cookie
    if "set-cookie" not in resp.headers and not resp.cookies:
        log.warning("vscode login: no cookies status=%s", resp.status_code)
        return None
    # httpx cookies
    for name, value in resp.cookies.items():
        if value:
            return name, value
    # header brut
    raw = resp.headers.get("set-cookie") or ""
    if "=" in raw:
        part = raw.split(";", 1)[0]
        name, _, value = part.partition("=")
        if name and value:
            return name.strip(), value.strip()
    return None


def bridge_status(settings: AtelierSettings) -> dict[str, Any]:
    from mcp_gateway.atelier.vscode_proxy import resolve_vscode_password

    vs = resolve_vscode_url(settings)
    pw = resolve_vscode_password(settings)
    internal = (settings.vscode_internal_url or "").strip()
    mode = (settings.vscode_upstream_auth or "atelier").strip().lower()
    # Prêt côté produit : proxy Atelier configuré ; upstream auth:none = opérationnel
    ready = bool(internal) and (mode == "atelier" or pw)
    return {
        "vscode_url": vs,
        "password_configured": bool(pw),
        "ready": ready,
        "ui": load_ui_settings(settings),
    }


def auto_submit_login_html(
    *,
    vscode_url: str,
    password: str,
    href: str,
    session_id: str | None,
) -> str:
    """Fallback si le Set-Cookie cross-subdomain est refusé par le navigateur."""
    action = html.escape(vscode_url.rstrip("/") + "/login", quote=True)
    pw = html.escape(password, quote=True)
    href_e = html.escape(href, quote=True)
    _ = session_id  # session portée par href (?atelier_session=) + sidecar MD
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <title>Ouverture VS Code…</title>
  <style>
    body {{ font-family: system-ui, sans-serif; background:#0f1419; color:#e7ecf1;
           display:flex; min-height:100vh; align-items:center; justify-content:center; }}
    p {{ opacity:.8 }}
  </style>
</head>
<body>
  <p>Connexion à VS Code…</p>
  <form id="f" method="post" action="{action}">
    <input type="hidden" name="password" value="{pw}" />
    <input type="hidden" name="base" value="." />
    <input type="hidden" name="href" value="{href_e}" />
  </form>
  <script>document.getElementById("f").submit();</script>
</body>
</html>
"""
