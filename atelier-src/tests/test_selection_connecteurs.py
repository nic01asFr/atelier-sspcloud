"""La sélection de connecteurs d'un projet vit dans son `.mcp.json`, pour toutes les surfaces.

Avant : l'Atelier calculait le fichier effectif de ses tours, et masquait dans
VS Code, par `disabledMcpServers`, ce que la dernière conversation ouverte
n'avait pas — figé pour tout le dossier jusqu'à la prochaine ouverture.
Maintenant : le `.mcp.json` du projet porte (en références) exactement ce que
reçoit l'agent, approuvé dans `~/.claude.json` ; VS Code, le terminal et le
tour de l'Atelier lisent le même ensemble.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
from mcp_gateway.atelier.mcp_sync import (
    MARQUE_HERITAGE,
    herite_du_pool,
    lier_le_projet,
    lier_tous_les_projets,
    materialize_session_mcp,
    write_project_binding,
)
from mcp_gateway.atelier.vscode_handoff import prepare_vscode_handoff
from mcp_gateway.db import connect


def _pool(reglages: AtelierSettings, **serveurs: dict) -> None:
    conn = connect(reglages.gateway_db_path)
    try:
        store = IntegratedMcpStore(conn)
        for nom, cfg in serveurs.items():
            store.upsert(nom, cfg)
    finally:
        conn.close()


def _serveurs(projet: Path) -> dict:
    return json.loads((projet / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]


def _entree(projet: Path) -> dict:
    return json.loads((Path.home() / ".claude.json").read_text(encoding="utf-8"))["projects"][str(projet)]


def test_la_liaison_ecrit_ce_que_recoit_le_tour(reglages: AtelierSettings) -> None:
    _pool(
        reglages,
        qgis={"type": "http", "url": "http://qgis/mcp", "headers": {"Authorization": "Bearer jeton-qgis-1234567890"}},
        llm={"type": "http", "url": "http://llm/mcp"},
    )
    projet = reglages.projects_dir / "p"
    noms = lier_le_projet(reglages, projet)
    effectif = json.loads(
        materialize_session_mcp(reglages, "c1", kind="code", cwd=projet).read_text(encoding="utf-8")
    )["mcpServers"]
    assert set(noms) == set(_serveurs(projet)) == set(effectif) == {"atelier", "qgis", "llm"}
    assert "jeton-qgis" not in (projet / ".mcp.json").read_text(encoding="utf-8")
    assert _entree(projet)["enabledMcpjsonServers"] == sorted(noms)


def test_un_projet_qui_herite_suit_le_pool(reglages: AtelierSettings) -> None:
    _pool(reglages, qgis={"type": "http", "url": "http://qgis/mcp"})
    projet = reglages.projects_dir / "p"
    lier_le_projet(reglages, projet)
    assert herite_du_pool(projet) and (projet / MARQUE_HERITAGE).is_file()
    _pool(reglages, n8n={"type": "http", "url": "http://n8n/mcp"})
    lier_tous_les_projets(reglages)
    assert set(_serveurs(projet)) == {"atelier", "qgis", "n8n"}


def test_un_choix_explicite_ne_suit_plus_le_pool(reglages: AtelierSettings) -> None:
    _pool(reglages, qgis={"type": "http", "url": "http://qgis/mcp"}, llm={"type": "http", "url": "http://llm/mcp"})
    projet = reglages.projects_dir / "p"
    lier_le_projet(reglages, projet)
    write_project_binding(reglages, projet, ["qgis"])
    assert not herite_du_pool(projet)
    _pool(reglages, n8n={"type": "http", "url": "http://n8n/mcp"})
    lier_le_projet(reglages, projet)
    assert set(_serveurs(projet)) == {"atelier", "qgis"}
    assert _entree(projet)["enabledMcpjsonServers"] == ["atelier", "qgis"]


def test_l_ouverture_dans_vscode_ne_fige_plus_rien(reglages: AtelierSettings) -> None:
    """L'ancien masque est levé pour ce que le projet a choisi, et n'est plus écrit."""
    _pool(reglages, qgis={"type": "http", "url": "http://qgis/mcp"}, llm={"type": "http", "url": "http://llm/mcp"})
    projet = reglages.projects_dir / "p"
    projet.mkdir(parents=True)
    (Path.home() / ".claude.json").write_text(
        json.dumps({"userID": "moi", "projects": {str(projet): {"disabledMcpServers": ["qgis", "llm", "tiers"]}}}),
        encoding="utf-8",
    )
    write_project_binding(reglages, projet, ["qgis"])
    reglages.llm_key_path.parent.mkdir(parents=True, exist_ok=True)
    reglages.llm_key_path.write_text("factice", encoding="utf-8")
    prepare_vscode_handoff(reglages, "p", "c1", projet)
    entree = _entree(projet)
    # qgis est choisi : plus masqué. Les autres ne sont pas dans le projet :
    # leur mention ne change rien et reste telle quelle.
    assert entree["disabledMcpServers"] == ["llm", "tiers"]
    assert entree["enabledMcpjsonServers"] == ["atelier", "qgis"]
    assert json.loads((Path.home() / ".claude.json").read_text(encoding="utf-8"))["userID"] == "moi"


def test_un_claude_json_illisible_n_est_pas_ecrase(reglages: AtelierSettings) -> None:
    (Path.home() / ".claude.json").write_text("{pas du json", encoding="utf-8")
    projet = reglages.projects_dir / "p"
    lier_le_projet(reglages, projet)
    assert (Path.home() / ".claude.json").read_text(encoding="utf-8") == "{pas du json"


def test_la_declaration_propre_au_projet_est_gardee(reglages: AtelierSettings) -> None:
    """Un helper d'en-têtes, un paramètre d'identité : le projet les a écrits, ils restent."""
    projet = reglages.projects_dir / "p"
    projet.mkdir(parents=True)
    propre = {
        "type": "http",
        "url": "http://qgis/mcp?profil=${QGIS_PROFIL:-}",
        "headersHelper": "node /srv/qgis-helper.mjs",
    }
    (projet / ".mcp.json").write_text(json.dumps({"mcpServers": {"qgis": propre}}), encoding="utf-8")
    _pool(reglages, qgis={"type": "http", "url": "http://qgis/mcp"})
    lier_le_projet(reglages, projet)
    assert _serveurs(projet)["qgis"] == propre


def test_l_entree_wikichat_d_un_projet_devient_le_pont(reglages: AtelierSettings) -> None:
    """Sauf wikichat : `?agent=atelier` ou `${WIKICHAT_AGENT:-}` cèdent au pont stdio.

    Contrat wikichat (`docs/hooks-et-dialogue.md` §8) : la connexion porte la
    conversation (`CLAUDE_CODE_SESSION_ID`), et `atelier` n'est plus un nom.
    """
    from mcp_gateway.atelier.wikichat_mcp import declaration_wikichat

    projet = reglages.projects_dir / "p"
    projet.mkdir(parents=True)
    propre = {"type": "sse", "url": "http://127.0.0.1:3777/sse?agent=${WIKICHAT_AGENT:-}"}
    (projet / ".mcp.json").write_text(json.dumps({"mcpServers": {"wikichat": propre}}), encoding="utf-8")
    _pool(reglages, wikichat={"type": "sse", "url": "http://127.0.0.1:3777/sse?agent=atelier"})
    lier_le_projet(reglages, projet)
    assert _serveurs(projet)["wikichat"] == declaration_wikichat(reglages)
    assert "agent=" not in (projet / ".mcp.json").read_text(encoding="utf-8")
    write_project_binding(reglages, projet, ["wikichat"])
    assert _serveurs(projet)["wikichat"] == declaration_wikichat(reglages)
