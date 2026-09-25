"""L'exécuteur en vrai processus (`python -m mcp_gateway.gardiens`), contre des services factices."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

RACINE = Path(__file__).resolve().parents[1]


def port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def service_factice(chemin: str) -> ThreadingHTTPServer:
    class G(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200 if self.path == chemin else 404)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a) -> None:
            return

    srv = ThreadingHTTPServer(("127.0.0.1", 0), G)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def attendre(url: str, delai: float = 20.0) -> dict:
    fin = time.monotonic() + delai
    derniere = None
    while time.monotonic() < fin:
        try:
            with urlopen(url, timeout=2) as r:
                return json.loads(r.read())
        except Exception as exc:  # noqa: BLE001
            derniere = exc
            time.sleep(0.3)
    raise AssertionError(f"{url} ne répond pas : {derniere}")


def test_l_executeur_tourne_contre_des_services_factices(tmp_path: Path) -> None:
    relais = service_factice("/_relais/sante")
    wikichat = service_factice("/api/health")
    work = tmp_path / "work"
    (work / ".claude").mkdir(parents=True)
    (work / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "node wikichat-hook.mjs stop"}]}]}}))
    declaration = tmp_path / "gardiens.json"
    declaration.write_text(json.dumps({"reglages": {}, "controles": [
        {"id": "sante.atelier", "gardien": "sante", "portee": "pod", "quand": {"toutes_les_min": 1}, "commande": ["interne", "sante.service"], "delai_s": 5, "params": {"service": "atelier"}},
        {"id": "sante.relais", "gardien": "sante", "portee": "pod", "quand": {"toutes_les_min": 1}, "commande": ["interne", "sante.service"], "delai_s": 5, "params": {"service": "relais"}},
        {"id": "sante.wikichat", "gardien": "sante", "portee": "pod", "quand": {"toutes_les_min": 1}, "commande": ["interne", "sante.service"], "delai_s": 5, "params": {"service": "wikichat"}},
        {"id": "entretien.automates", "gardien": "entretien", "portee": "pod", "quand": {"toutes_les_min": 15}, "commande": ["interne", "entretien.automates"], "delai_s": 20},
    ]}))
    port = port_libre()
    env = {
        **os.environ,
        "ATELIER_WORK": str(work),
        "ATELIER_WORK_DIR": str(work),
        "ATELIER_PORT": str(port_libre()),  # l'Atelier est « tombé »
        "ATELIER_RELAIS_LLM_PORT": str(relais.server_address[1]),
        "WIKICHAT_PORT": str(wikichat.server_address[1]),
        "WIKICHAT_HOME": str(tmp_path / "wikichat"),
        "ATELIER_GARDIENS_PORT": str(port),
        "ATELIER_GARDIENS_DECLARATION": str(declaration),
        "ATELIER_GARDIENS_GESTES": "0",
    }
    proc = subprocess.Popen([sys.executable, "-m", "mcp_gateway.gardiens"], cwd=str(RACINE), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        sante = attendre(f"http://127.0.0.1:{port}/sante")
        assert sante["controles"] == 4 and sante["interrupteurs"]["gestes"] is False
        fin = time.monotonic() + 20
        while time.monotonic() < fin:
            etat = attendre(f"http://127.0.0.1:{port}/etat")
            if all(c["derniere"] for c in etat["controles"]):
                break
            time.sleep(0.5)
        par_id = {c["id"]: c["etat"] for c in etat["controles"]}
        # Sous Linux, l'inventaire lit le vrai /proc : les services factices de ce
        # test y écoutent sans être déclarés, ce qu'il signale à raison en
        # « attention ». Sous Windows, /proc n'existe pas et il rend « ok ».
        automates = par_id.pop("entretien.automates")
        assert automates in ("ok", "attention")
        assert par_id == {"sante.atelier": "alerte", "sante.relais": "ok", "sante.wikichat": "ok"}
        alertes = [a["empreinte"] for a in etat["alertes_ouvertes"] if a["niveau"] == "alerte"]
        assert alertes == ["sante.atelier:ne-repond-pas"]
        journal = list((work / ".atelier-etat" / "gardiens" / "journal").glob("*.jsonl"))
        assert journal and len(journal[0].read_text(encoding="utf-8").splitlines()) >= 4
        reglages = json.loads((work / ".claude" / "settings.json").read_text())
        assert "mcp_gateway.gardiens.garde_bash" in json.dumps(reglages["hooks"]["PreToolUse"])
        assert reglages["hooks"]["Stop"][0]["hooks"][0]["command"] == "node wikichat-hook.mjs stop"
    finally:
        proc.terminate()
        proc.wait(10)
        relais.shutdown()
        wikichat.shutdown()


def test_interrupteur_general(tmp_path: Path) -> None:
    env = {**os.environ, "ATELIER_GARDIENS": "0", "ATELIER_WORK": str(tmp_path), "ATELIER_WORK_DIR": str(tmp_path)}
    fini = subprocess.run([sys.executable, "-m", "mcp_gateway.gardiens"], cwd=str(RACINE), env=env, capture_output=True, text=True, timeout=30)
    assert fini.returncode == 0
    assert "ATELIER_GARDIENS=0" in fini.stdout + fini.stderr
    assert not (tmp_path / ".atelier-etat").exists()
