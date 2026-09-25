"""Le serveur MCP de l'Atelier (`atelier_*`) est dans tout projet, sur toute surface.

Audit du 25 septembre (Lecteur Grist) : les outils de l'Atelier manquaient
aux quatre surfaces, parce que le `.mcp.json` du projet ne l'avait pas coché,
alors que l'interface affichait « Accès aux outils » actif.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.mcp_sync import (
    apply_mcp_overlay,
    compute_binding_merged,
    materialize_mcp_config,
    materialize_session_mcp,
    project_binding_state,
    write_project_binding,
)


def _projet_sans_atelier(tmp_path: Path) -> Path:
    projet = tmp_path / "projet"
    projet.mkdir()
    (projet / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"maison": {"type": "http", "url": "http://maison/mcp"}}}),
        encoding="utf-8",
    )
    return projet


def test_un_projet_qui_ne_l_a_pas_coche_l_a_quand_meme(reglages: AtelierSettings, tmp_path: Path) -> None:
    projet = _projet_sans_atelier(tmp_path)
    serveurs = compute_binding_merged(reglages, kind="code", cwd=projet)
    atelier = serveurs["atelier"]
    assert atelier["url"] == f"http://127.0.0.1:{reglages.port}/mcp"
    assert atelier["headers"]["Authorization"] == "Bearer ${ATELIER_MCP_KEY}"
    assert "X-Atelier-Conversation" in atelier["headers"]


def test_le_fichier_effectif_porte_la_conversation(reglages: AtelierSettings, tmp_path: Path) -> None:
    projet = _projet_sans_atelier(tmp_path)
    chemin = materialize_session_mcp(reglages, "conv-7", kind="code", cwd=projet)
    atelier = json.loads(chemin.read_text(encoding="utf-8"))["mcpServers"]["atelier"]
    assert atelier["headers"]["X-Atelier-Conversation"] == "conv-7"
    assert atelier["headers"]["Authorization"] == "Bearer ${ATELIER_MCP_KEY}"


def test_une_conversation_ne_peut_pas_s_en_priver(reglages: AtelierSettings, tmp_path: Path) -> None:
    projet = _projet_sans_atelier(tmp_path)
    serveurs = compute_binding_merged(reglages, kind="code", cwd=projet)
    reste = apply_mcp_overlay(serveurs, {"atelier": False, "maison": False})
    assert "atelier" in reste and "maison" not in reste


def test_la_portee_utilisateur_le_porte(reglages: AtelierSettings) -> None:
    materialize_mcp_config(reglages)
    serveurs = json.loads((Path.home() / ".claude.json").read_text(encoding="utf-8"))["mcpServers"]
    assert serveurs["atelier"]["headers"]["X-Atelier-Conversation"] == "${ATELIER_SESSION:-poste}"
    assert serveurs["atelier"]["headers"]["Authorization"] == "Bearer ${ATELIER_MCP_KEY}"


def test_un_choix_de_connecteurs_le_garde(reglages: AtelierSettings, tmp_path: Path) -> None:
    projet = tmp_path / "projet"
    projet.mkdir()
    write_project_binding(reglages, projet, [])
    serveurs = json.loads((projet / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert list(serveurs) == ["atelier"]


def test_l_interface_montre_ce_que_l_agent_recoit(reglages: AtelierSettings, tmp_path: Path) -> None:
    projet = _projet_sans_atelier(tmp_path)
    etat = project_binding_state(reglages, projet)
    atelier = next(c for c in etat if c["id"] == "atelier")
    assert atelier["active"] is True and atelier["fixe"] is True
    assert atelier["active"] == ("atelier" in compute_binding_merged(reglages, kind="code", cwd=projet))
