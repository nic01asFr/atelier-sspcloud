"""`atelier_projets_lier` : les relations entre projets, écrites dans wikichat.

wikichat est remplacé par un faux qui tient `set_project_meta` (qui remplace
la liste des relations) et `declare_project`, et publie ses relations comme
la cartographie (`GET /api/cartographie`, arêtes `relation`). On éprouve que
la commande garde les autres relations, qu'elle s'annule, et qu'elle déclare
d'abord un projet que wikichat ne connaît pas.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mcp_gateway.atelier.commandes import profils
from mcp_gateway.atelier.commandes.catalogue import FAIT, REFUSE
from mcp_gateway.atelier.commandes.creations import ServicesCreations
from mcp_gateway.atelier.commandes.modele import ORIGINE_MCP, Contexte

REFUS = "❌"


class FauxWikichat:
    def __init__(self, projets: list[str]) -> None:
        self.relations: dict[str, list[dict[str, Any]]] = {p: [] for p in projets}
        self.appels: list[tuple[str, dict[str, Any]]] = []

    async def outil(self, nom: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.appels.append((nom, arguments))
        if nom == "wikichat__set_project_meta":
            if arguments["project"] not in self.relations:
                texte = f'{REFUS} Projet "{arguments["project"]}" introuvable. Crée-le via declare_project() d\'abord.'
            else:
                self.relations[arguments["project"]] = list(arguments["relations"])
                texte = f'Meta mise à jour : "{arguments["project"]}"\n  Relations : {len(arguments["relations"])} link(s)'
            return {"content": [{"type": "text", "text": texte}]}
        if nom == "wikichat__declare_project":
            self.relations.setdefault(arguments["name"], [])
            return {"content": [{"type": "text", "text": "Projet déclaré"}]}
        raise AssertionError(nom)

    async def cartographie(self) -> dict[str, Any]:
        noeuds = [{"id": p, "nom": p} for p in self.relations]
        aretes = [
            {"id": f"relation:{p}>{r['project']}:{r['type']}", "type": "relation", "de": p, "vers": r["project"],
             "sous_type": r["type"], "note": r.get("note"), "source": "set_project_meta"}
            for p, rs in self.relations.items()
            for r in rs
        ]
        return {"version": 1, "noeuds": noeuds, "aretes": aretes, "limites": {"relations_sans_cible": 0}}


@pytest.fixture()
def wikichat(atelier: Any) -> FauxWikichat:
    settings = atelier.app.state.settings
    for slug in ("carte", "lecteur-grist", "donnees"):
        (settings.projects_dir / slug).mkdir(parents=True, exist_ok=True)
    faux = FauxWikichat(["carte", "lecteur-grist", "donnees"])
    faux.relations["carte"] = [{"type": "sibling-of", "project": "donnees", "note": "même quartier"}]
    atelier.app.state.creations = ServicesCreations(outil_wikichat=faux.outil, cartographie=faux.cartographie)
    return faux


def _executer(atelier: Any, arguments: dict[str, Any]) -> Any:
    ctx = Contexte(acteur="conversation:assistant-1", origine=ORIGINE_MCP)
    return asyncio.run(atelier.app.state.commandes.executer("atelier_projets_lier", arguments, ctx))


def test_classe_inverse_et_profil(atelier: Any) -> None:
    commande = atelier.app.state.commandes.commande("atelier_projets_lier")
    assert commande is not None
    assert (commande.classe, commande.inverse, commande.exposee_mcp) == ("reversible", "atelier_projets_lier", True)
    definitions = atelier.app.state.commandes._definitions_completes()  # noqa: SLF001
    assert "atelier_projets_lier" not in {d["name"] for d in profils.definitions_du_profil(definitions, "code")}
    assert "atelier_projets_lier" in {d["name"] for d in profils.definitions_du_profil(definitions, "assistant")}


def test_lier_garde_les_autres_relations_et_s_annule(atelier: Any, wikichat: FauxWikichat) -> None:
    reponse = _executer(atelier, {"projet": "carte", "vers": "lecteur-grist", "type": "depends-on", "note": "lit ses .grist"})
    assert reponse.statut == FAIT, reponse.charge
    assert wikichat.relations["carte"] == [
        {"type": "sibling-of", "project": "donnees", "note": "même quartier"},
        {"type": "depends-on", "project": "lecteur-grist", "note": "lit ses .grist"},
    ]
    assert wikichat.appels[-1][0] == "wikichat__set_project_meta"
    carte = reponse.charge["carte"]
    assert carte["preuve"]["relations_ecrites"] == 2 and carte["preuve"]["wikichat"].startswith("Meta mise à jour")
    ligne = atelier.app.state.commandes.journal.lire(commande="atelier_projets_lier", limite=1)[0]
    assert ligne["resultat"] == "fait" and ligne["action"]["classe"] == "reversible"
    assert ligne["action"]["inverse"]["arguments"] == {
        "projet": "carte",
        "relations": [{"type": "sibling-of", "project": "donnees", "note": "même quartier"}],
    }
    annule = asyncio.run(
        atelier.app.state.commandes.executer(
            "atelier_annuler", {"action": reponse.action}, Contexte(acteur="conversation:assistant-1", origine=ORIGINE_MCP)
        )
    )
    assert annule.statut == FAIT, annule.charge
    assert wikichat.relations["carte"] == [{"type": "sibling-of", "project": "donnees", "note": "même quartier"}]


def test_retirer_un_lien(atelier: Any, wikichat: FauxWikichat) -> None:
    reponse = _executer(atelier, {"projet": "carte", "vers": "donnees", "type": "sibling-of", "retirer": True})
    assert reponse.statut == FAIT, reponse.charge
    assert wikichat.relations["carte"] == []
    absent = _executer(atelier, {"projet": "carte", "vers": "donnees", "type": "sibling-of", "retirer": True})
    assert absent.statut == REFUSE and "aucun lien" in absent.charge["erreur"]


def test_un_projet_inconnu_de_wikichat_y_est_declare(atelier: Any, wikichat: FauxWikichat) -> None:
    (atelier.app.state.settings.projects_dir / "nouveau").mkdir()
    reponse = _executer(atelier, {"projet": "nouveau", "vers": "carte"})
    assert reponse.statut == FAIT, reponse.charge
    assert [a[0] for a in wikichat.appels] == [
        "wikichat__set_project_meta",
        "wikichat__declare_project",
        "wikichat__set_project_meta",
    ]
    assert wikichat.relations["nouveau"] == [{"type": "depends-on", "project": "carte"}]


@pytest.mark.parametrize(
    "arguments, motif",
    [
        ({"projet": "carte", "vers": "carte"}, "lui-même"),
        ({"projet": "carte", "vers": "absent"}, "projet inconnu"),
        ({"projet": "absent", "vers": "carte"}, "projet inconnu"),
        ({"projet": "carte", "vers": "donnees", "type": "aime"}, "type"),
        ({"projet": "carte", "relations": "tout"}, "relations"),
    ],
)
def test_lier_refuse(atelier: Any, wikichat: FauxWikichat, arguments: dict[str, Any], motif: str) -> None:
    reponse = _executer(atelier, arguments)
    assert reponse.statut == REFUSE and motif in reponse.charge["erreur"]
    assert not any(a[0] == "wikichat__set_project_meta" for a in wikichat.appels)


def test_sans_wikichat_la_commande_le_dit(atelier: Any) -> None:
    atelier.app.state.creations = ServicesCreations()
    reponse = _executer(atelier, {"projet": "carte", "vers": "donnees"})
    assert reponse.statut == REFUSE and "wikichat" in reponse.charge["erreur"]
