"""Aucun secret de connecteur dans un fichier que l'Atelier écrit dans un projet.

Le `.mcp.json` d'un projet recopiait les déclarations du pool avec leurs
en-têtes `Authorization`, et le .gitignore posé par l'Atelier disait qu'il se
versionnait : un jeton de la passerelle est parti sur GitHub. Le fichier ne
porte plus que des références `${ATELIER_MCP_…}`, dont les valeurs arrivent
par l'environnement des sessions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from pathlib import Path

import httpx
from starlette.requests import Request

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
from mcp_gateway.atelier.git_repos import GITIGNORE, LIGNES_DE_L_ATELIER, etat
from mcp_gateway.atelier.harness import ClaudeHarness
from mcp_gateway.atelier.mcp_secrets import nom_de_variable
from mcp_gateway.atelier.mcp_sync import write_project_binding
from mcp_gateway.atelier.vscode_handoff import claude_extension_env, environnement_du_claude_vscode
from mcp_gateway.db import connect

JETON = "jeton-de-la-passerelle-0123456789"
VARIABLE = "ATELIER_MCP_ONYXIA_AUTHORIZATION"


def _pool(reglages: AtelierSettings) -> None:
    conn = connect(reglages.gateway_db_path)
    try:
        IntegratedMcpStore(conn).upsert(
            "Onyxia",
            {
                "type": "http",
                "url": "https://passerelle.exemple/mcp",
                "headers": {"Authorization": f"Bearer {JETON}"},
            },
        )
    finally:
        conn.close()


def _cle_atelier(reglages: AtelierSettings) -> str:
    reglages.owner_key_path.parent.mkdir(parents=True, exist_ok=True)
    reglages.owner_key_path.write_text("cle-proprietaire-secrete", encoding="utf-8")
    return "cle-proprietaire-secrete"


def _lire(projet: Path) -> dict:
    return json.loads((projet / ".mcp.json").read_text(encoding="utf-8"))


def test_le_nom_de_variable_se_deduit_du_service_et_de_l_en_tete() -> None:
    assert nom_de_variable("Onyxia", "Authorization") == VARIABLE
    assert nom_de_variable("n8n-prod", "X-Api-Key") == "ATELIER_MCP_N8N_PROD_X_API_KEY"
    assert nom_de_variable("outil", "API_TOKEN", dans_env=True) == "ATELIER_MCP_OUTIL_ENV_API_TOKEN"


def test_le_mcp_json_ecrit_ne_porte_aucun_secret_en_clair(reglages, tmp_path) -> None:
    _pool(reglages)
    cle = _cle_atelier(reglages)
    projet = tmp_path / "projet"
    projet.mkdir()
    write_project_binding(reglages, projet, ["atelier", "Onyxia"])

    texte = (projet / ".mcp.json").read_text(encoding="utf-8")
    assert JETON not in texte and cle not in texte
    serveurs = _lire(projet)["mcpServers"]
    assert serveurs["Onyxia"]["headers"]["Authorization"] == f"Bearer ${{{VARIABLE}}}"
    assert serveurs["Onyxia"]["url"] == "https://passerelle.exemple/mcp"
    assert serveurs["atelier"]["headers"]["Authorization"] == "Bearer ${ATELIER_MCP_KEY}"


def test_les_variables_sont_dans_l_environnement_des_sessions(reglages) -> None:
    _pool(reglages)
    cle = _cle_atelier(reglages)
    env = ClaudeHarness(reglages)._env()
    assert env[VARIABLE] == JETON, "le schéma reste dans le fichier, le jeton seul dans la variable"
    assert env["ATELIER_MCP_KEY"] == cle


def test_les_variables_sont_donnees_a_l_extension_vs_code(reglages) -> None:
    _pool(reglages)
    # Le processus les reçoit par l'enveloppeur (claude-env.sh) ; les réglages
    # de code-server, utilisateur comme dossier, n'en portent aucune.
    processus = environnement_du_claude_vscode(reglages)
    assert processus[VARIABLE] == JETON
    reglages_vscode = {e["name"] for e in claude_extension_env(reglages)}
    assert VARIABLE not in reglages_vscode


def test_un_mcp_json_existant_est_migre_a_la_reecriture(reglages, tmp_path) -> None:
    _pool(reglages)
    _cle_atelier(reglages)
    projet = tmp_path / "projet"
    projet.mkdir()
    ancien = {
        "mcpServers": {
            "atelier": {
                "type": "http",
                "url": "http://127.0.0.1:8787/mcp",
                "headers": {"Authorization": "Bearer ancienne-cle-en-clair"},
            },
            "Onyxia": {
                "type": "http",
                "url": "https://passerelle.exemple/mcp",
                "headers": {"authorization": "Bearer ancien-jeton-en-clair"},
            },
        }
    }
    (projet / ".mcp.json").write_text(json.dumps(ancien), encoding="utf-8")
    write_project_binding(reglages, projet, ["atelier", "Onyxia"])

    texte = (projet / ".mcp.json").read_text(encoding="utf-8")
    assert "en-clair" not in texte
    serveurs = _lire(projet)["mcpServers"]
    assert serveurs["Onyxia"]["headers"]["authorization"] == f"Bearer ${{{VARIABLE}}}"
    assert serveurs["atelier"]["headers"]["Authorization"] == "Bearer ${ATELIER_MCP_KEY}"


def test_un_en_tete_tiers_est_preserve_et_signale(reglages, tmp_path, caplog) -> None:
    """Un service que l'Atelier ne sert pas : on n'aurait rien à mettre dans la variable."""
    _pool(reglages)
    projet = tmp_path / "projet"
    projet.mkdir()
    tiers = {
        "type": "http",
        "url": "https://tiers.exemple/mcp",
        "headers": {"X-Api-Key": "cle-du-tiers", "Accept": "application/json"},
    }
    onyxia = {
        "type": "http",
        "url": "https://passerelle.exemple/mcp",
        "headers": {"Authorization": f"Bearer {JETON}", "X-Mon-Token": "a-moi"},
    }
    (projet / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"tiers": tiers, "Onyxia": onyxia}}), encoding="utf-8"
    )
    # Le service tiers n'est pas dans le pool : il ne reste que parce que le
    # projet le déclare déjà.
    with caplog.at_level(logging.WARNING, logger="atelier.mcp_sync"):
        write_project_binding(reglages, projet, ["tiers", "Onyxia"])

    serveurs = _lire(projet)["mcpServers"]
    assert serveurs["tiers"]["headers"] == tiers["headers"]
    assert serveurs["Onyxia"]["headers"]["X-Mon-Token"] == "a-moi"
    assert serveurs["Onyxia"]["headers"]["Authorization"] == f"Bearer ${{{VARIABLE}}}"
    journal = caplog.text
    assert "tiers" in journal and "X-Api-Key" in journal
    assert "X-Mon-Token" in journal
    assert "cle-du-tiers" not in journal, "on signale l'en-tête, jamais sa valeur"


def test_le_gitignore_de_l_atelier_ignore_le_mcp_json() -> None:
    assert ".mcp.json" in GITIGNORE.splitlines()
    assert ".mcp.json" in LIGNES_DE_L_ATELIER


def _depot(chemin: Path) -> None:
    chemin.mkdir()
    subprocess.run(["git", "init", "-q", str(chemin)], check=True)


def test_la_liaison_complete_le_gitignore_d_un_projet_existant(reglages, tmp_path) -> None:
    _pool(reglages)
    projet = tmp_path / "projet"
    _depot(projet)
    (projet / ".gitignore").write_text("# à moi\n.venv/\n", encoding="utf-8")
    write_project_binding(reglages, projet, ["Onyxia"])
    lignes = (projet / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert lignes[:2] == ["# à moi", ".venv/"]
    assert ".mcp.json" in lignes


def test_un_mcp_json_deja_suivi_est_signale_sans_etre_de_suivi(reglages, tmp_path, caplog) -> None:
    _pool(reglages)
    projet = tmp_path / "projet"
    _depot(projet)
    (projet / ".mcp.json").write_text('{"mcpServers": {}}', encoding="utf-8")
    subprocess.run(["git", "-C", str(projet), "add", ".mcp.json"], check=True)
    subprocess.run(
        ["git", "-C", str(projet), "-c", "user.name=t", "-c", "user.email=t@t",
         "commit", "-q", "--no-verify", "-m", "avant la règle"],
        check=True,
    )
    assert etat(projet).to_dict()["mcp_json_tracked"] is True

    with caplog.at_level(logging.WARNING, logger="atelier.mcp_sync"):
        write_project_binding(reglages, projet, ["Onyxia"])
    assert "suivi par git" in caplog.text
    suivis = subprocess.run(
        ["git", "-C", str(projet), "ls-files", ".mcp.json"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert suivis.strip() == ".mcp.json", "l'Atelier ne réécrit pas l'index de la personne"


def test_le_proxy_pilote_ne_relaie_ni_authorization_ni_cookie(reglages, monkeypatch) -> None:
    from mcp_gateway.atelier import wikichat_pilote_proxy

    recus: dict[str, str] = {}

    async def requete(self, methode, cible, headers=None, content=None):  # noqa: ANN001
        recus.update(headers or {})
        return httpx.Response(200, content=b"ok", headers={"content-type": "text/plain"})

    monkeypatch.setattr(httpx.AsyncClient, "request", requete)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/pilote",
        "query_string": b"",
        "headers": [
            (b"authorization", b"Bearer cle-proprietaire"),
            (b"cookie", b"atelier_session=abc"),
            (b"accept", b"text/html"),
        ],
    }

    async def recevoir():
        return {"type": "http.request", "body": b"", "more_body": False}

    reponse = asyncio.run(
        wikichat_pilote_proxy.proxy_wikichat_pilote(Request(scope, recevoir), reglages)
    )
    assert reponse.status_code == 200
    noms = {k.lower() for k in recus}
    assert "authorization" not in noms and "cookie" not in noms
    assert recus.get("accept") == "text/html"
