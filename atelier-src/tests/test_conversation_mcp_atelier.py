"""La porte `/mcp` de l'Atelier apprend de quelle conversation vient l'appel.

Les outils `atelier_artefact_*` refusent d'agir sur l'artefact d'une autre
conversation ; il leur faut savoir qui appelle. L'agent le passait en
argument `auteur`, quand il y pensait. La déclaration de l'Atelier porte
désormais `X-Atelier-Conversation`, par référence comme le navigateur :
`${ATELIER_SESSION:-poste}` dans le `.mcp.json` du projet, la conversation
résolue dans le fichier effectif d'un tour, et `ATELIER_SESSION` dans
l'environnement du processus.

Côté outils, l'en-tête lu par `/mcp` devient l'auteur : test_apps_outils.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.harness import ClaudeHarness
from mcp_gateway.atelier.mcp_sync import (
    SERVICE_ATELIER,
    declaration_atelier,
    materialize_session_mcp,
    write_project_binding,
)

ENTETE = "X-Atelier-Conversation"


def _projet(tmp_path: Path) -> Path:
    projet = tmp_path / "projet"
    projet.mkdir()
    return projet


def _effectif(chemin: Path) -> dict:
    return json.loads(chemin.read_text(encoding="utf-8"))["mcpServers"]


def test_la_declaration_porte_la_conversation_par_reference(reglages: AtelierSettings) -> None:
    d = declaration_atelier(reglages)
    assert d["headers"][ENTETE] == "${ATELIER_SESSION:-poste}"
    assert d["headers"]["Authorization"] == "Bearer ${ATELIER_MCP_KEY}"


def test_le_mcp_json_du_projet_garde_la_reference(reglages: AtelierSettings, tmp_path: Path) -> None:
    """VS Code lit ce fichier sans conversation : il tombe sur « poste »."""
    projet = _projet(tmp_path)
    write_project_binding(reglages, projet, [SERVICE_ATELIER])
    ecrit = json.loads((projet / ".mcp.json").read_text(encoding="utf-8"))
    assert ecrit["mcpServers"][SERVICE_ATELIER]["headers"][ENTETE] == "${ATELIER_SESSION:-poste}"


def test_le_fichier_effectif_d_un_tour_nomme_la_conversation(
    reglages: AtelierSettings, tmp_path: Path
) -> None:
    projet = _projet(tmp_path)
    write_project_binding(reglages, projet, [SERVICE_ATELIER])
    chemin = materialize_session_mcp(reglages, "conv-42", kind="code", cwd=projet)
    atelier = _effectif(chemin)[SERVICE_ATELIER]
    assert atelier["headers"][ENTETE] == "conv-42"
    # La clé reste une référence : c'est le client qui la développe.
    assert atelier["headers"]["Authorization"] == "Bearer ${ATELIER_MCP_KEY}"


def test_un_ancien_mcp_json_recoit_la_declaration_du_profil(reglages: AtelierSettings, tmp_path: Path) -> None:
    """Écrit avant les en-têtes : l'entrée `atelier` devient celle du profil, partout.

    Le serveur `atelier` n'est pas un choix du projet : son adresse suit le port
    du service, et ses en-têtes (conversation, profil) sont ceux du contrat.
    """
    projet = _projet(tmp_path)
    ancien = {
        "mcpServers": {
            SERVICE_ATELIER: {
                "type": "http",
                "url": "http://127.0.0.1:9999/mcp",
                "headers": {"Authorization": "Bearer ${ATELIER_MCP_KEY}"},
            }
        }
    }
    (projet / ".mcp.json").write_text(json.dumps(ancien), encoding="utf-8")
    chemin = materialize_session_mcp(reglages, "conv-ancienne", kind="code", cwd=projet)
    atelier = _effectif(chemin)[SERVICE_ATELIER]
    assert atelier["headers"][ENTETE] == "conv-ancienne"
    assert atelier["headers"]["X-Atelier-Profil"] == "code"
    assert atelier["url"] == f"http://127.0.0.1:{reglages.port}/mcp"


def test_un_en_tete_deja_ecrit_n_est_pas_double(reglages: AtelierSettings, tmp_path: Path) -> None:
    projet = _projet(tmp_path)
    ecrit = {
        "mcpServers": {
            SERVICE_ATELIER: {
                "type": "http",
                "url": "http://127.0.0.1:8787/mcp",
                "headers": {"x-atelier-conversation": "${ATELIER_SESSION}"},
            }
        }
    }
    (projet / ".mcp.json").write_text(json.dumps(ecrit), encoding="utf-8")
    chemin = materialize_session_mcp(reglages, "conv-7", kind="code", cwd=projet)
    entetes = _effectif(chemin)[SERVICE_ATELIER]["headers"]
    assert [k for k in entetes if k.lower() == ENTETE.lower()] == [ENTETE]
    assert entetes[ENTETE] == "conv-7"


def test_l_environnement_du_tour_porte_la_conversation(reglages: AtelierSettings) -> None:
    assert ClaudeHarness(reglages)._env("agent", None, "conv-42")["ATELIER_SESSION"] == "conv-42"


def test_une_conversation_heritee_du_poste_ne_passe_pas(reglages: AtelierSettings, monkeypatch) -> None:
    """Sans conversation, pas d'`ATELIER_SESSION` d'emprunt : le repli « poste » s'applique."""
    monkeypatch.setenv("ATELIER_SESSION", "une-autre")
    assert "ATELIER_SESSION" not in ClaudeHarness(reglages)._env()
    assert ClaudeHarness(reglages)._env("", None, "la-mienne")["ATELIER_SESSION"] == "la-mienne"
