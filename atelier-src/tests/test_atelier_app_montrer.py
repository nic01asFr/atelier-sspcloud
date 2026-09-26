"""`bin/atelier-app montrer` et `ouvrir-navigateur` : les créations sans MCP.

Le script parle à un vrai Atelier de test, servi par uvicorn sur un port
local : mêmes routes (`/v1/commandes`), même catalogue, mêmes gardes que les
outils `atelier_montrer` et `atelier_navigateur_ouvrir` en profil code. La
conversation vient de `ATELIER_SESSION`, ou de `CLAUDE_CODE_SESSION_ID` hors
de l'Atelier ; le projet vient d'elle.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Iterator

import httpx
import pytest
import uvicorn

from mcp_gateway.atelier.api import build_app
from mcp_gateway.atelier.config import AtelierSettings

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "atelier-app"

pytestmark = pytest.mark.skipif(
    any(shutil.which(o) is None for o in ("sh", "curl", "python3")), reason="sh, curl et python3 requis"
)


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Atelier:
    def __init__(self, settings: AtelierSettings, port: int) -> None:
        self.settings = settings
        self.url = f"http://127.0.0.1:{port}"
        self.cle = settings.owner_key_path.read_text(encoding="utf-8").strip()

    def api(self, methode: str, chemin: str, **kw) -> httpx.Response:  # noqa: ANN003
        return httpx.request(
            methode, self.url + chemin, headers={"Authorization": f"Bearer {self.cle}"}, timeout=20, **kw
        )

    def conversation(self, slug: str) -> str:
        r = self.api("POST", "/v1/sessions", json={"slug": slug, "kind": "code"})
        assert r.status_code == 200, r.text
        return r.json()["session_id"]

    def lancer(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        base = {k: v for k, v in os.environ.items() if k not in ("ATELIER_SESSION", "CLAUDE_CODE_SESSION_ID")}
        return subprocess.run(
            ["sh", SCRIPT.as_posix(), *args],
            env={**base, "ATELIER_WORK": self.settings.work_dir.as_posix(), "ATELIER_URL": self.url, **env},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )


@pytest.fixture()
def atelier(tmp_path: Path) -> Iterator[Atelier]:
    settings = AtelierSettings(
        work_dir=tmp_path / "work", apps_public_url="https://apps.test", public_url="https://atelier.test"
    )
    settings.ensure_dirs()
    for slug, nom in (("demo", "site"), ("autre", "secret")):
        dossier = settings.projects_dir / slug / "artifacts" / nom
        dossier.mkdir(parents=True)
        (dossier / "index.html").write_text(f"<h1>{slug}/{nom}</h1>", encoding="utf-8")
    port = _port_libre()
    serveur = uvicorn.Server(
        uvicorn.Config(build_app(settings=settings, use_fake=True), host="127.0.0.1", port=port, log_level="warning")
    )
    fil = threading.Thread(target=serveur.run, daemon=True)
    fil.start()
    fin = time.monotonic() + 20
    while not serveur.started and time.monotonic() < fin:
        time.sleep(0.05)
    assert serveur.started
    a = Atelier(settings, port)
    for slug in ("demo", "autre"):
        a.api("POST", "/v1/projects", json={"slug": slug, "kind": "code"})
    try:
        yield a
    finally:
        serveur.should_exit = True
        fil.join(10)


def test_montrer_ouvre_la_creation_dans_le_panneau_de_la_conversation(atelier: Atelier) -> None:
    conv = atelier.conversation("demo")
    r = atelier.lancer("montrer", "site", "index.html", ATELIER_SESSION=conv)
    assert r.returncode == 0, r.stderr + r.stdout
    corps = json.loads(r.stdout)
    assert corps["statut"] == "fait"
    assert corps["resultat"]["vue"]["projet"] == "demo"
    vues = atelier.api("GET", f"/v1/panneau/{conv}").json()["vues"]
    assert [v["nom"] for v in vues] == ["site"]


def test_montrer_une_creation_absente_echoue(atelier: Atelier) -> None:
    conv = atelier.conversation("demo")
    r = atelier.lancer("montrer", "secret", ATELIER_SESSION=conv)
    assert r.returncode == 1
    assert json.loads(r.stdout)["statut"] in ("refus", "erreur")


def test_ouvrir_navigateur_rend_une_adresse_bornee_au_projet(atelier: Atelier) -> None:
    conv = atelier.conversation("demo")
    r = atelier.lancer("ouvrir-navigateur", "site", ATELIER_SESSION=conv)
    assert r.returncode == 0, r.stderr + r.stdout
    resultat = json.loads(r.stdout)["resultat"]
    assert resultat["portee"] == "demo"
    assert resultat["adresse"].startswith("https://apps.test/_atelier/entree?code=")


def test_hors_de_l_atelier_la_conversation_du_cli_suffit(atelier: Atelier) -> None:
    conv = atelier.conversation("demo")
    store_rec = atelier.api("GET", f"/v1/sessions/{conv}").json()
    assert store_rec["session_id"] == conv
    # Une conversation de l'Atelier reprise dans VS Code : le CLI l'appelle par son identifiant.
    fiche = atelier.settings.sessions_dir / f"{conv}.json"
    donnees = json.loads(fiche.read_text(encoding="utf-8"))
    donnees["claude_session_id"] = "cli-0f1e2d3c"
    fiche.write_text(json.dumps(donnees), encoding="utf-8")
    r = atelier.lancer("montrer", "site", CLAUDE_CODE_SESSION_ID="cli-0f1e2d3c")
    assert r.returncode == 0, r.stderr + r.stdout
    assert json.loads(r.stdout)["resultat"]["vue"]["projet"] == "demo"


def test_sans_conversation_rien_ne_part(atelier: Atelier) -> None:
    r = atelier.lancer("montrer", "site")
    assert r.returncode == 2
    assert "conversation inconnue" in r.stderr


def test_une_conversation_inconnue_est_refusee(atelier: Atelier) -> None:
    r = atelier.lancer("ouvrir-navigateur", "site", ATELIER_SESSION="inventee-42")
    assert r.returncode == 1
    assert "le projet ne peut pas être établi" in r.stdout


def test_le_projet_est_celui_de_la_conversation(atelier: Atelier) -> None:
    """Une conversation d'`autre` ne montre pas une création de `demo` : elle n'existe pas chez elle."""
    conv = atelier.conversation("autre")
    r = atelier.lancer("montrer", "site", ATELIER_SESSION=conv)
    assert r.returncode == 1
    r = atelier.lancer("montrer", "secret", ATELIER_SESSION=conv)
    assert r.returncode == 0, r.stderr + r.stdout
    assert json.loads(r.stdout)["resultat"]["vue"]["projet"] == "autre"


def test_l_aide_nomme_les_deux_sous_commandes(atelier: Atelier) -> None:
    r = atelier.lancer()
    assert r.returncode == 2
    assert "montrer" in r.stdout and "ouvrir-navigateur" in r.stdout
