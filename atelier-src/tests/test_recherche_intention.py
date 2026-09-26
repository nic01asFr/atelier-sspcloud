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




# ── Les commandes de création (vague 2) ─────────────────────────────────


@pytest.mark.parametrize(
    "demande, attendu",
    [
        ("créer un agent", "atelier_agent_creer"),
        ("create a scheduled agent", "atelier_agent_creer"),
        ("désactiver l'agent", "atelier_agent_desactiver"),
        ("ajouter un connecteur", "atelier_connecteur_ajouter"),
        ("add a connector", "atelier_connecteur_ajouter"),
        ("retirer le connecteur", "atelier_connecteur_retirer"),
        ("choisir les connecteurs du projet", "atelier_connecteur_choisir"),
        ("lier des projets", "atelier_projets_lier"),
        ("link projects", "atelier_projets_lier"),
        ("structurer le projet", "atelier_projet_structurer"),
        ("migrate the project structure", "atelier_projet_structurer"),
    ],
)
def test_les_commandes_de_creation_se_trouvent_par_l_intention(atelier, demande: str, attendu: str) -> None:  # noqa: ANN001
    """Les vraies déclarations du catalogue, parmi les autres commandes et quelques outils du pool."""
    from mcp_gateway.tool_search import search_tools

    outils = [
        {"name": d["name"], "description": d["description"], "server": "atelier"}
        for d in atelier.app.state.commandes._definitions_completes()  # noqa: SLF001
    ] + OUTILS
    trouves = [t["name"] for t in search_tools(outils, query=demande, limit=3)]
    assert trouves and trouves[0] == attendu, trouves
