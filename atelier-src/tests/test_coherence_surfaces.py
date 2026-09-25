"""Test de cohérence : ce que reçoit l'agent d'un projet, selon la surface.

Pour un projet de test, on compare (a) le fichier effectif d'un tour de
l'Atelier et l'environnement du harnais, (b) `~/.claude.json` + `.mcp.json` et
l'environnement de VS Code ou du shell : mêmes serveurs, `atelier` présent des
deux côtés, mêmes identifiants une fois les références développées, et aucune
valeur secrète en clair dans un fichier que lit Claude Code.

La même comparaison tourne sur le pod avec le vrai binaire `claude` :
`bin/atelier-verifier-coherence`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_gateway.atelier.coherence import comparer, secrets_en_clair, surface_atelier, surface_vscode
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
from mcp_gateway.atelier.mcp_sync import materialize_mcp_config, write_project_binding
from mcp_gateway.db import connect

JETON_QGIS = "ghp_" + "Q" * 36
JETON_N8N = "cle-n8n-0123456789abcdef"


def _installer(reglages: AtelierSettings) -> Path:
    conn = connect(reglages.gateway_db_path)
    try:
        store = IntegratedMcpStore(conn)
        store.upsert(
            "qgis",
            {"type": "http", "url": "http://qgis/mcp", "headers": {"Authorization": f"Bearer {JETON_QGIS}"}},
        )
        store.upsert("n8n", {"type": "http", "url": "http://n8n/mcp", "headers": {"X-Api-Key": JETON_N8N}})
        store.upsert("wikichat", {"type": "sse", "url": "http://127.0.0.1:3777/sse?agent=atelier"})
    finally:
        conn.close()
    reglages.owner_key_path.parent.mkdir(parents=True, exist_ok=True)
    reglages.owner_key_path.write_text("cle-proprietaire-0123456789", encoding="utf-8")
    reglages.llm_key_path.write_text("cle-llm-0123456789", encoding="utf-8")
    materialize_mcp_config(reglages)
    projet = reglages.projects_dir / "essai"
    projet.mkdir(parents=True)
    return projet


@pytest.mark.parametrize("choix", [None, ["qgis"], []])
def test_les_surfaces_recoivent_la_meme_chose(reglages: AtelierSettings, choix) -> None:
    """Projet qui hérite du pool, projet restreint, projet sans connecteur."""
    projet = _installer(reglages)
    if choix is not None:
        write_project_binding(reglages, projet, choix)
    atelier = surface_atelier(reglages, projet, "conv-coherence")
    vscode = surface_vscode(reglages, projet)
    assert comparer(reglages, projet, atelier, vscode) == []
    attendu = {"atelier"} | ({"qgis", "n8n", "wikichat"} if choix is None else set(choix))
    assert set(atelier["serveurs"]) == attendu


def test_un_ecart_est_vu(reglages: AtelierSettings) -> None:
    """Le test ne passe pas à vide : un serveur ajouté d'un seul côté est signalé."""
    projet = _installer(reglages)
    atelier = surface_atelier(reglages, projet, "conv-coherence")
    vscode = surface_vscode(reglages, projet)
    vscode["serveurs"] = {k: v for k, v in vscode["serveurs"].items() if k != "atelier"}
    ecarts = comparer(reglages, projet, atelier, vscode)
    assert any("serveurs différents" in e for e in ecarts)
    assert any("`atelier` manque" in e for e in ecarts)


def test_un_secret_en_clair_est_vu(reglages: AtelierSettings) -> None:
    projet = _installer(reglages)
    surface_atelier(reglages, projet, "conv-coherence")
    fuite = projet / ".mcp.json"
    donnees = json.loads(fuite.read_text(encoding="utf-8"))
    donnees["mcpServers"]["qgis"]["headers"]["Authorization"] = f"Bearer {JETON_QGIS}"
    fuite.write_text(json.dumps(donnees), encoding="utf-8")
    trouves = secrets_en_clair([fuite], {"ATELIER_MCP_QGIS_AUTHORIZATION": JETON_QGIS})
    assert any("valeur de ATELIER_MCP_QGIS_AUTHORIZATION" in t for t in trouves)
    assert any("motif de jeton" in t for t in trouves)
    assert JETON_QGIS[:10] not in "".join(trouves), "on dit où, jamais la valeur"


def test_une_variable_non_fournie_est_vue(reglages: AtelierSettings) -> None:
    projet = _installer(reglages)
    atelier = surface_atelier(reglages, projet, "conv-coherence")
    vscode = surface_vscode(reglages, projet)
    vscode["env"] = {k: v for k, v in vscode["env"].items() if k != "ATELIER_MCP_KEY"}
    ecarts = comparer(reglages, projet, atelier, vscode)
    assert any("VS Code : variables non fournies ['ATELIER_MCP_KEY']" in e for e in ecarts)
