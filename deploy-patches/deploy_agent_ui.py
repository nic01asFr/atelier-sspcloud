"""Deploy changed Agent UI files to proj-claude-code via MCP Onyxia."""
import base64
import json
import os
import pathlib
import urllib.request

# Le pod visé et la façon de l'atteindre. Ces valeurs décrivent une
# installation, pas le produit : elles se donnent par l'environnement, avec
# un repli sur celle de l'auteur pour que le script reste utilisable tel quel.
MCP_URL = os.environ.get(
    "ATELIER_MCP_URL", "https://user-nic01asfr-passerelle-mcp.user.lab.sspcloud.fr/mcp"
)
SESSION = os.environ.get("ATELIER_MCP_SESSION", "proj-claude-code")
ROOT = pathlib.Path(__file__).resolve().parent.parent / "atelier-src/mcp_gateway/atelier"
BASE = "/home/onyxia/work/atelier-src/mcp_gateway/atelier"
# Tous les fichiers du service, sans exception : une liste tenue à la main
# laissait quinze modules hors déploiement, dont les changements ne
# partaient jamais — en silence, ce qui est le pire des cas.
FILES = [
    "web/js/views/agent.js",
    "web/js/controllers/agent.js",
    "web/js/views/connectors.js",
    "web/js/views/composition-builder.js",
    "web/js/controllers/connectors.js",
    "web/js/views/code-tree.js",
    "web/js/views/code-chat.js",
    "web/js/controllers/chat.js",
    "web/js/controllers/projects.js",
    "web/js/controllers/sessions.js",
    "web/js/controllers/auth.js",
    "web/js/state.js",
    "web/js/api.js",
    "web/js/ui/tool-picker.js",
    "web/js/ui/tool-variant.js",
    "web/js/ui/modal.js",
    "web/js/views/composer-mcp.js",
    "web/js/controllers/composer-mcp.js",
    "api.py",
    "projects.py",
    "git_repos.py",
    "sessions.py",
    "gateway_tools.py",
    "session_mcp.py",
    "mcp_sync.py",
    "stdio_probe.py",
    "mcp_endpoint.py",
    "wikichat_ensure.py",
    "wikichat_projects.py",
    "project_context.py",
    "enrichissements.py",
    "ui_settings.py",
    "vscode_proxy.py",
    "vscode_handoff.py",
    "decrire_connecteur.py",
    "llm.py",
    "pilote_overview.py",
    "harness.py",
    "web/js/app.js",
    "web/css/app.css",
    "web/index.html",
    "__init__.py",
    "app.py",
    "auth.py",
    "claude_home.py",
    "config.py",
    "events.py",
    "gateway_mcp.py",
    "gateway_overview.py",
    "gateway_runtime.py",
    "mcp_registry.py",
    "models_catalog.py",
    "pilote_client.py",
    "session_attachments.py",
    "vscode_bridge.py",
    "web/js/controllers/composer-input.js",
    "web/js/core/dom.js",
    "web/js/core/router.js",
    "web/js/services/catalog.js",
    "web/js/services/vscode.js",
    "web/js/ui/auto-grow-textarea.js",
    "web/js/ui/code-highlight.js",
    "web/js/ui/context-menu.js",
    "web/js/ui/markdown.js",
    "web/js/ui/message-render.js",
    "web/js/views/shell.js",
    "wikichat_pilote_proxy.py",
]

# Notre version de wikichat (voir wikichat-atelier/README.md) : elle vit hors
# de l'arbre du service, mais se deploie avec lui — sinon elle ne survivrait
# pas a une recreation du pod.
DEPOT = pathlib.Path(__file__).resolve().parent.parent
# Le reste du paquet : passerelle, catalogue, authentification. Il n'était
# pas déployé du tout — les corrections qu'on y portait restaient sur la
# machine, sans que rien ne le signale.
PAQUET = [
    "__init__.py",
    "api.py",
    "auth.py",
    "bundles.py",
    "catalog.py",
    "catalog_sync.py",
    "compositions/__init__.py",
    "compositions/executor.py",
    "compositions/refs.py",
    "compositions/service.py",
    "compositions/validate.py",
    "config.py",
    "credentials.py",
    "db.py",
    "main.py",
    "mcp/__init__.py",
    "mcp/gateway.py",
    "mcp/instructions.py",
    "mcp/tools_registry.py",
    "mcp_fields.py",
    "meta_tools_defs.py",
    "notifications.py",
    "oauth.py",
    "profile_tools.py",
    "profiles.py",
    "registry.py",
    "server_enable.py",
    "tool_cache.py",
    "tool_hints.py",
    "tool_search.py",
    "tools_exposure.py",
    "tools_hub.py",
    "upstream/__init__.py",
    "upstream/client.py",
    "upstream/pool.py",
    "upstream/transports.py",
    "upstream_hints.py",
]

HORS_ARBRE = [
    (
        DEPOT / "wikichat-atelier/src/pilote.mjs",
        "/home/onyxia/work/wikichat/src/src/pilote.mjs",
    ),
    (
        DEPOT / "atelier-src/vscode-extension/atelier-ouvre-claude/package.json",
        "/home/onyxia/.local/share/code-server/extensions/atelier-ouvre-claude/package.json",
    ),
    (
        DEPOT / "atelier-src/vscode-extension/atelier-ouvre-claude/extension.js",
        "/home/onyxia/.local/share/code-server/extensions/atelier-ouvre-claude/extension.js",
    ),
    (
        DEPOT / "atelier-src/mcp_gateway/upstream/transports.py",
        "/home/onyxia/work/atelier-src/mcp_gateway/upstream/transports.py",
    ),
    (
        DEPOT / "atelier-src/mcp_gateway/upstream/client.py",
        "/home/onyxia/work/atelier-src/mcp_gateway/upstream/client.py",
    ),
]


def token() -> str:
    """Le jeton d'accès au MCP Onyxia.

    Il vient de l'environnement quand il y est. Sinon on le lit dans la
    configuration MCP du poste — un chemin de machine, qui n'a rien à faire
    en dur dans un dépôt public, mais qui garde le script utilisable sans
    réglage préalable.
    """
    depuis_env = os.environ.get("ATELIER_MCP_TOKEN", "").strip()
    if depuis_env:
        return depuis_env
    defaut = pathlib.Path.home() / ".cursor" / "mcp.json"
    chemin = pathlib.Path(os.environ.get("ATELIER_MCP_CONFIG", "") or defaut)
    serveur = os.environ.get("ATELIER_MCP_SERVER", "Onyxia nic01asfr")
    config = json.loads(chemin.read_text(encoding="utf-8"))
    entete = config["mcpServers"][serveur]["headers"]["Authorization"]
    return entete.replace("Bearer ", "")


def mcp_call(name: str, arguments: dict, req_id: int = 1) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        MCP_URL,
        data=data,
        headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


def text_result(r: dict) -> str:
    try:
        return r["result"]["content"][0]["text"]
    except Exception:
        return json.dumps(r)


def main() -> None:
    rid = 1
    cibles = [(ROOT / rel, f"{BASE}/{rel}") for rel in FILES]
    cibles += [
        (ROOT.parent / rel, f"{BASE.rsplit(chr(47), 1)[0]}/{rel}") for rel in PAQUET
    ]
    cibles += [(src, dest) for src, dest in HORS_ARBRE]
    for source, dest in cibles:
        rel = source.name
        raw = source.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        chunk = 8000
        chunks = [b64[i : i + chunk] for i in range(0, len(b64), chunk)]
        r = mcp_call(
            "exec",
            {
                "session_id": SESSION,
                "lang": "python",
                "code": "import pathlib; pathlib.Path('/tmp/ui_deploy.b64').write_text('')",
            },
            rid,
        )
        rid += 1
        print("init", rel, text_result(r)[:80])
        for i, ch in enumerate(chunks):
            esc = ch.replace("\\", "\\\\").replace("'", "\\'")
            code = (
                "import pathlib\n"
                "p=pathlib.Path('/tmp/ui_deploy.b64')\n"
                f"p.write_text(p.read_text()+'{esc}')\n"
                f"print({i}, len(p.read_text()))"
            )
            r = mcp_call(
                "exec",
                {"session_id": SESSION, "lang": "python", "code": code},
                rid,
            )
            rid += 1
            out = text_result(r)
            if "Traceback" in out:
                print("FAIL", rel, i, out[:400])
                raise SystemExit(1)
            print(f"  chunk {i}/{len(chunks)-1}")
        decode = (
            "import base64, pathlib\n"
            f"p = pathlib.Path({dest!r})\n"
            "p.parent.mkdir(parents=True, exist_ok=True)\n"
            "p.write_bytes(base64.b64decode(pathlib.Path('/tmp/ui_deploy.b64').read_text()))\n"
            "print(p, p.stat().st_size)\n"
        )
        r = mcp_call(
            "exec",
            {"session_id": SESSION, "lang": "python", "code": decode},
            rid,
        )
        rid += 1
        print("OK", text_result(r)[:160])

    # Contrôle d'arrivée : quelques marqueurs des derniers correctifs, pour
    # que le déploiement dise s'il a vraiment posé ce qu'on croit.
    verify = (
        "from pathlib import Path\n"
        "r = Path('/home/onyxia/work/atelier-src/mcp_gateway/atelier')\n"
        "w = Path('/home/onyxia/.local/share/code-server/extensions/atelier-ouvre-claude')\n"
        "for nom, chemin, marqueur in (\n"
        "    ('handoff', r / 'vscode_handoff.py', 'MOTIF_MARQUE'),\n"
        "    ('sessions', r / 'sessions.py', 'adopter_conversations_claude'),\n"
        "    ('harness', r / 'harness.py', 'enregistrement_utilisateur'),\n"
        "    ('api.js', r / 'web/js/api.js', 'toolOutputText'),\n"
        "    ('extension', w / 'extension.js', 'primaryEditor.open'),\n"
        "):\n"
        "    ok = chemin.is_file() and marqueur in chemin.read_text(encoding='utf-8', errors='replace')\n"
        "    print(('OK   ' if ok else 'MANQUE '), nom)\n"
    )
    r = mcp_call("exec", {"session_id": SESSION, "lang": "python", "code": verify}, rid)
    print("VERIFY", text_result(r))


if __name__ == "__main__":
    main()
