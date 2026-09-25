"""La recherche d'outils comprend les mots de la personne (mesures de la vague 1)."""

from __future__ import annotations

import pytest


# ── La recherche d'outils comprend les mots de la personne ──────────────


OUTILS = [
    {"name": "wikichat__search_knowledge", "description": "Search the cross-project knowledge base (axes)."},
    {"name": "wikichat__recall", "description": "Recall a value stored with remember."},
    {"name": "wikichat__list_channels", "description": "List channels."},
    {"name": "gateway_list_compositions", "description": "Liste les compositions promues."},
    {"name": "qgis__export_pdf", "description": "Exporter la carte en PDF."},
]


@pytest.mark.parametrize("demande", ["connaissance", "ma mémoire", "retrouve dans mes connaissances"])
def test_connaissance_et_memoire_trouvent_search_knowledge(demande: str) -> None:
    from mcp_gateway.tool_search import search_tools

    trouves = [t["name"] for t in search_tools(OUTILS, query=demande, limit=3)]
    assert "wikichat__search_knowledge" in trouves, trouves
    assert "qgis__export_pdf" not in trouves


def test_connaissance_met_search_knowledge_en_tete() -> None:
    from mcp_gateway.tool_search import search_tools

    assert search_tools(OUTILS, query="connaissance")[0]["name"] == "wikichat__search_knowledge"


def test_les_creations_ne_menent_pas_aux_compositions() -> None:
    from mcp_gateway.tool_search import search_tools

    outils = OUTILS + [{"name": "atelier_artefacts", "description": "Les artefacts d'un projet."}]
    assert search_tools(outils, query="mes créations")[0]["name"] == "atelier_artefacts"


