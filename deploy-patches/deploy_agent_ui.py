"""Deploy changed Agent UI files to proj-claude-code via MCP Onyxia."""
import base64
import json
import pathlib
import urllib.request

MCP_URL = "https://user-nic01asfr-passerelle-mcp.user.lab.sspcloud.fr/mcp"
SESSION = "proj-claude-code"
ROOT = pathlib.Path(__file__).resolve().parent.parent / "atelier-src/mcp_gateway/atelier"
BASE = "/home/onyxia/work/atelier-src/mcp_gateway/atelier"
FILES = [
    "web/js/views/agent.js",
    "web/js/controllers/agent.js",
    "web/js/views/connectors.js",
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
    "sessions.py",
    "gateway_tools.py",
    "session_mcp.py",
    "mcp_sync.py",
    "stdio_probe.py",
    "mcp_endpoint.py",
    "wikichat_ensure.py",
    "wikichat_projects.py",
    "pilote_overview.py",
    "harness.py",
    "web/js/app.js",
    "web/css/app.css",
    "web/index.html",
]

# Notre version de wikichat (voir wikichat-atelier/README.md) : elle vit hors
# de l'arbre du service, mais se deploie avec lui — sinon elle ne survivrait
# pas a une recreation du pod.
DEPOT = pathlib.Path(__file__).resolve().parent.parent
HORS_ARBRE = [
    (
        DEPOT / "wikichat-atelier/src/pilote.mjs",
        "/home/onyxia/work/wikichat/src/src/pilote.mjs",
    ),
]


def token() -> str:
    mcp_json = pathlib.Path(r"C:\Users\Omen\.cursor\mcp.json").read_text(encoding="utf-8")
    return json.loads(mcp_json)["mcpServers"]["Onyxia nic01asfr"]["headers"]["Authorization"].replace(
        "Bearer ", ""
    )


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

    # touch no restart needed for static; verify app.js contains shell3
    verify = (
        "from pathlib import Path\n"
        "p=Path('/home/onyxia/work/atelier-src/mcp_gateway/atelier/web/js/app.js')\n"
        "t=p.read_text()\n"
        "print('shell3' in t, 'openCreate' in Path('/home/onyxia/work/atelier-src/mcp_gateway/atelier/web/js/controllers/agent.js').read_text(), p.stat().st_size)\n"
    )
    r = mcp_call("exec", {"session_id": SESSION, "lang": "python", "code": verify}, rid)
    print("VERIFY", text_result(r))


if __name__ == "__main__":
    main()
