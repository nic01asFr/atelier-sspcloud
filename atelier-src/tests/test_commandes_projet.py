"""La structure type d'un projet, posée et tenue par les commandes.

Éprouvé sur un vrai dépôt git : ce que `atelier_projet_creer` garantit (dépôt,
commit d'ouverture, `projet.json` valide, `ETAT.md` lisible par wikichat),
son inverse (ranger, pas supprimer), et `atelier_projet_modifier`, qui ne
commite que `projet.json`.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from mcp_gateway.atelier.commandes import structure
from mcp_gateway.atelier.commandes.catalogue import FAIT, REFUSE, contexte_interface
from mcp_gateway.atelier.commandes.modele import ORIGINE_MCP, Contexte

besoin_de_git = pytest.mark.skipif(shutil.which("git") is None, reason="git absent")


def _git(chemin: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(chemin), *args], capture_output=True, text=True).stdout.strip()


def _executer(atelier: Any, nom: str, arguments: dict[str, Any], ctx: Contexte | None = None) -> Any:
    ctx = ctx or Contexte(acteur="conversation:essai", origine=ORIGINE_MCP)
    return asyncio.run(atelier.app.state.commandes.executer(nom, arguments, ctx))


# ── Le schéma de projet.json ────────────────────────────────────────────


def test_projet_json_valide_passe() -> None:
    p = structure.valider({"version": 1, "slug": "lecteur-grist", "titre": "Lecteur Grist"})
    assert p.fichiers.etat == "ETAT.md"
    assert p.en_json()["slug"] == "lecteur-grist"


@pytest.mark.parametrize(
    "donnees",
    [
        {"slug": "a", "titre": "A", "inconnu": 1},
        {"slug": "A B", "titre": "A"},
        {"slug": "a", "titre": ""},
        {"slug": "a", "titre": "A", "version": 2},
        {"slug": "a", "titre": "A", "fichiers": {"etat": "../ailleurs.md"}},
        {"slug": "a", "titre": "A", "chemins_proteges": ["/etc"]},
        {"slug": "a", "titre": "A", "vues_epinglees": [{"vue": "v"}]},
        {"slug": "a", "titre": 3},
    ],
)
def test_projet_json_hors_schema_est_refuse(donnees: dict[str, Any]) -> None:
    with pytest.raises(structure.ErreurProjetJson):
        structure.valider(donnees)


def test_le_slug_est_celui_de_wikichat() -> None:
    assert structure.slugifier("Lecteur Grist : l'été !") == "lecteur-grist-l-ete"


# ── atelier_projet_creer ────────────────────────────────────────────────


@besoin_de_git
def test_creer_pose_la_structure_le_depot_et_le_commit(atelier) -> None:  # noqa: ANN001
    reponse = _executer(
        atelier,
        "atelier_projet_creer",
        {"titre": "Carte des écoles", "objectif": "Montrer les écoles du quartier.", "gabarit": "application"},
    )
    assert reponse.statut == FAIT, reponse.charge
    slug = reponse.charge["projet"]
    assert slug == "carte-des-ecoles"
    racine = atelier.app.state.settings.projects_dir / slug

    declaration = structure.lire(racine)
    assert declaration is not None
    assert declaration.titre == "Carte des écoles"
    assert declaration.description == "Montrer les écoles du quartier."
    assert declaration.creation is not None and declaration.creation.par == "conversation:essai"
    # Les champs et rubriques que wikichat lit, sous leur nom.
    brut = json.loads((racine / ".atelier" / "projet.json").read_text(encoding="utf-8"))
    assert {"titre", "description", "slug", "fichiers"} <= set(brut)
    assert brut["fichiers"]["etat"] == "ETAT.md"
    etat = (racine / "ETAT.md").read_text(encoding="utf-8")
    assert "## À décider" in etat and "## Demandé à l'Atelier" in etat
    assert (racine / "CLAUDE.md").read_text(encoding="utf-8").startswith("@.atelier/contexte.md")
    assert list((racine / "docs" / "decisions").glob("0001-*.md"))

    # Un dépôt sur main, un commit d'ouverture qui emporte projet.json.
    assert _git(racine, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert _git(racine, "rev-list", "--count", "HEAD") == "1"
    assert _git(racine, "log", "-1", "--pretty=%s") == "Ouvrir le projet"
    suivis = _git(racine, "ls-files").splitlines()
    assert ".atelier/projet.json" in suivis and "ETAT.md" in suivis and "CLAUDE.md" in suivis
    assert ".mcp.json" not in suivis

    carte = reponse.charge["carte"]
    assert carte["voir"]["lien"] == f"/?slug={slug}"
    assert carte["annuler"]["arguments"] == {"action": carte["action"]}
    assert carte["preuve"]["commit"]["commit"]
    assert carte["preuve"]["structure"]["rubriques"] == {"À décider": True, "Demandé à l'Atelier": True}

    ligne = atelier.app.state.journal_unique.lire(commande="atelier_projet_creer")[0]
    assert ligne["resultat"] == FAIT and ligne["objet"] == {"type": "projet", "id": slug}
    assert ligne["action"]["inverse"] == {"commande": "atelier_projet_ranger", "arguments": {"projet": slug}}

    titres = {p.slug: p.title for p in atelier.app.state.projects.list_projects()}
    assert titres[slug] == "Carte des écoles"


@besoin_de_git
def test_le_meme_titre_donne_un_autre_slug(atelier) -> None:  # noqa: ANN001
    premier = _executer(atelier, "atelier_projet_creer", {"titre": "Essai"}).charge["projet"]
    second = _executer(atelier, "atelier_projet_creer", {"titre": "Essai"}).charge["projet"]
    assert (premier, second) == ("essai", "essai-2")
    refus = _executer(atelier, "atelier_projet_creer", {"titre": "X", "slug": "essai"})
    assert refus.statut == REFUSE


def test_creer_refuse_un_gabarit_ou_un_connecteur_inconnu(atelier) -> None:  # noqa: ANN001
    assert _executer(atelier, "atelier_projet_creer", {"titre": "A", "gabarit": "fusee"}).statut == REFUSE
    reponse = _executer(atelier, "atelier_projet_creer", {"titre": "A", "connecteurs": ["inexistant"]})
    assert reponse.statut == REFUSE
    assert not (atelier.app.state.settings.projects_dir / "a").exists()


@besoin_de_git
def test_annuler_la_creation_range_sans_supprimer(atelier) -> None:  # noqa: ANN001
    cree = _executer(atelier, "atelier_projet_creer", {"titre": "À ranger"})
    slug, action = cree.charge["projet"], cree.charge["carte"]["action"]
    annule = _executer(atelier, "atelier_annuler", {"action": action})
    assert annule.statut == FAIT, annule.charge
    visibles = {p.slug for p in atelier.app.state.projects.list_projects()}
    tous = {p.slug: p for p in atelier.app.state.projects.list_projects(include_archived=True)}
    assert slug not in visibles and tous[slug].archived
    assert (atelier.app.state.settings.projects_dir / slug / "ETAT.md").is_file()
    # Une action ne s'annule qu'une fois.
    assert _executer(atelier, "atelier_annuler", {"action": action}).statut == REFUSE
    # Et l'annulation elle-même se défait : ressortir.
    ressorti = _executer(atelier, "atelier_annuler", {"action": annule.charge["carte"]["action"]})
    assert ressorti.statut == REFUSE  # atelier_annuler n'a pas d'inverse
    assert _executer(atelier, "atelier_projet_ressortir", {"projet": slug}).statut == FAIT
    assert slug in {p.slug for p in atelier.app.state.projects.list_projects()}


# ── atelier_projet_modifier ─────────────────────────────────────────────


@besoin_de_git
def test_modifier_ne_commite_que_projet_json_et_s_annule(atelier) -> None:  # noqa: ANN001
    slug = _executer(atelier, "atelier_projet_creer", {"titre": "Avant"}).charge["projet"]
    racine = atelier.app.state.settings.projects_dir / slug
    (racine / "travail-en-cours.txt").write_text("pas fini", encoding="utf-8")

    reponse = _executer(atelier, "atelier_projet_modifier", {"projet": slug, "titre": "Après", "description": "Neuf."})
    assert reponse.statut == FAIT, reponse.charge
    assert reponse.charge["avant"] == {"titre": "Avant", "description": ""}
    assert structure.lire(racine).titre == "Après"
    assert _git(racine, "show", "--name-only", "--pretty=format:", "HEAD").split() == [".atelier/projet.json"]
    assert "travail-en-cours.txt" in _git(racine, "status", "--porcelain")
    assert {p.slug: p.title for p in atelier.app.state.projects.list_projects()}[slug] == "Après"

    annule = _executer(atelier, "atelier_annuler", {"action": reponse.charge["carte"]["action"]})
    assert annule.statut == FAIT, annule.charge
    assert structure.lire(racine).titre == "Avant"
    assert structure.lire(racine).description == ""


def test_modifier_refuse_sans_rien_a_changer_ou_projet_inconnu(atelier) -> None:  # noqa: ANN001
    assert _executer(atelier, "atelier_projet_modifier", {"projet": "nulle-part", "titre": "x"}).statut == REFUSE
    (atelier.app.state.settings.projects_dir / "vide").mkdir(parents=True)
    assert _executer(atelier, "atelier_projet_modifier", {"projet": "vide"}).statut == REFUSE


@besoin_de_git
def test_renommer_par_l_interface_suit_projet_json(atelier) -> None:  # noqa: ANN001
    """`projet.json` prime à l'affichage : renommer doit l'écrire aussi."""
    slug = _executer(atelier, "atelier_projet_creer", {"titre": "Premier nom"}).charge["projet"]
    atelier.app.state.projects.patch(slug, title="Second nom")
    racine = atelier.app.state.settings.projects_dir / slug
    assert structure.lire(racine).titre == "Second nom"
    assert _git(racine, "log", "-1", "--pretty=%s") == "Renommer le projet"


def test_publier_est_reserve_a_la_personne(atelier) -> None:  # noqa: ANN001
    (atelier.app.state.settings.projects_dir / "p").mkdir(parents=True)
    reponse = _executer(atelier, "atelier_projet_publier", {"projet": "p"})
    assert reponse.statut == REFUSE and "réservée" in reponse.charge["erreur"]
    # La personne passe la classe ; c'est GitHub, absent ici, qui refuse.
    reponse = _executer(atelier, "atelier_projet_publier", {"projet": "p"}, contexte_interface())
    assert "réservée" not in str(reponse.charge)


def test_le_gitignore_garde_projet_json_et_ignore_le_reste_de_atelier() -> None:
    from mcp_gateway.atelier.git_repos import GITIGNORE, LIGNES_DE_L_ATELIER

    lignes = GITIGNORE.splitlines()
    for attendue in (".atelier/*", "!.atelier/projet.json", "!.atelier/env.json"):
        assert attendue in lignes and attendue in LIGNES_DE_L_ATELIER
