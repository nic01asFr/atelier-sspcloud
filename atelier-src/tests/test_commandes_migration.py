"""La migration vers la structure type, éprouvée sur une copie du Lecteur Grist.

La copie (`copie_lecteur_grist.py`) reprend du pod, à l'octet près, le
`CLAUDE.md` (non suivi par git) et le `.gitignore` (qui ignore `.atelier/`
entier) de `projet-sans-nom-5`. On y vérifie l'aperçu à blanc, qu'aucun
fichier n'est remplacé, le commit unique, et que l'inverse rend le dépôt tel
qu'il était.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from copie_lecteur_grist import EMPREINTE_CLAUDE_MD, EMPREINTE_GITIGNORE, FIXTURE, copier_le_lecteur_grist
from mcp_gateway.atelier.commandes import profils, structure
from mcp_gateway.atelier.commandes.catalogue import APERCU, FAIT, REFUSE, contexte_interface
from mcp_gateway.atelier.commandes.migration import claude_md_migre, gitignore_migre
from mcp_gateway.atelier.commandes.modele import ORIGINE_MCP, Contexte

besoin_de_git = pytest.mark.skipif(shutil.which("git") is None, reason="git absent")

SLUG = "projet-sans-nom-5"
ARGUMENTS = {"projet": SLUG, "titre": "Lecteur Grist", "description": "Un document .grist devenu application."}


def _git(racine: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(racine), *args], capture_output=True, text=True, check=True).stdout.strip()


def _sha(chemin: Path) -> str:
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def _modele() -> Contexte:
    return Contexte(acteur="conversation:assistant-1", origine=ORIGINE_MCP)


def _executer(atelier: Any, nom: str, arguments: dict[str, Any], ctx: Contexte | None = None) -> Any:
    return asyncio.run(atelier.app.state.commandes.executer(nom, arguments, ctx or _modele()))


def _migrer(atelier: Any, arguments: dict[str, Any] | None = None) -> Any:
    arguments = arguments or ARGUMENTS
    apercu = _executer(atelier, "atelier_projet_structurer", arguments)
    assert apercu.statut == APERCU, apercu.charge
    return _executer(atelier, "atelier_projet_structurer", {**arguments, "confirmation": apercu.charge["confirmation"]})


def _instantane(racine: Path) -> dict[str, str]:
    return {
        p.relative_to(racine).as_posix(): _sha(p)
        for p in sorted(racine.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(racine).parts
    }


@pytest.fixture()
def lecteur(atelier: Any) -> Path:
    return copier_le_lecteur_grist(atelier.app.state.settings.projects_dir / SLUG)


# ── Déclaration ─────────────────────────────────────────────────────────


def test_classe_inverse_et_profil(atelier: Any) -> None:
    catalogue = atelier.app.state.commandes
    structurer = catalogue.commande("atelier_projet_structurer")
    destructurer = catalogue.commande("atelier_projet_destructurer")
    assert (structurer.classe, structurer.inverse) == ("engageante", "atelier_projet_destructurer")
    assert (destructurer.classe, destructurer.inverse) == ("reversible", "atelier_projet_structurer")
    assert structurer.classe_pour({"a_blanc": True}) == "lecture"
    definitions = catalogue._definitions_completes()  # noqa: SLF001
    code = {d["name"] for d in profils.definitions_du_profil(definitions, "code")}
    assistant = {d["name"] for d in profils.definitions_du_profil(definitions, "assistant")}
    for nom in ("atelier_projet_structurer", "atelier_projet_destructurer"):
        assert nom not in code and nom in assistant


def test_la_copie_est_celle_du_pod(lecteur: Path) -> None:
    assert _sha(lecteur / "CLAUDE.md") == EMPREINTE_CLAUDE_MD
    assert _sha(lecteur / ".gitignore") == EMPREINTE_GITIGNORE
    assert (FIXTURE / "CLAUDE.md").stat().st_size == 13590


# ── Les fonctions pures ─────────────────────────────────────────────────


def test_le_gitignore_ancien_est_complete_sans_doublon() -> None:
    ancien = (FIXTURE / "gitignore").read_text(encoding="utf-8")
    nouveau, remplacees, ajoutees = gitignore_migre(ancien)
    lignes = nouveau.splitlines()
    assert remplacees == [".atelier/"] and ajoutees == []
    assert ".atelier/" not in lignes
    i = lignes.index(".atelier/*")
    assert lignes[i : i + 3] == [".atelier/*", "!.atelier/projet.json", "!.atelier/env.json"]
    assert gitignore_migre(nouveau)[0] == nouveau, "une seconde passe ne change rien"


def test_claude_md_garde_son_contenu_et_importe_le_contexte() -> None:
    ancien = (FIXTURE / "CLAUDE.md").read_text(encoding="utf-8")
    nouveau = claude_md_migre(ancien)
    assert nouveau is not None
    assert nouveau.startswith("@.atelier/contexte.md\n\n<!-- consignes:projet -->")
    assert "<!-- atelier:contexte -->" not in nouveau
    assert nouveau.endswith(ancien.split("<!-- /atelier:contexte -->", 1)[1].lstrip("\n"))
    assert claude_md_migre(nouveau) is None


# ── À blanc ─────────────────────────────────────────────────────────────


@besoin_de_git
def test_a_blanc_rend_le_plan_sans_rien_ecrire(atelier: Any, lecteur: Path) -> None:
    avant = _instantane(lecteur)
    head = _git(lecteur, "rev-parse", "HEAD")
    reponse = _executer(atelier, "atelier_projet_structurer", {**ARGUMENTS, "a_blanc": True})
    assert reponse.statut == FAIT, reponse.charge
    plan = reponse.charge
    assert plan["a_blanc"] is True
    assert [c["chemin"] for c in plan["creer"]] == [
        ".atelier/projet.json",
        "ETAT.md",
        "docs/cahier-des-charges.md",
        "docs/decisions/0001-structure-type.md",
    ]
    assert [m["chemin"] for m in plan["modifier"]] == [".gitignore", "CLAUDE.md"]
    assert {"chemin": "readme.md", "raison": "déjà là, jamais écrasé"} in plan["garder"]
    assert "CLAUDE.md" in plan["suivre_par_git"]
    assert any("CLAUDE.md garde" in r for r in plan["remarques"])
    assert "-.atelier/" in plan["modifier"][0]["diff"]
    # Rien d'écrit, rien de commité, rien au journal (lecture).
    assert _instantane(lecteur) == avant
    assert _git(lecteur, "rev-parse", "HEAD") == head
    assert not atelier.app.state.commandes.journal.lire(commande="atelier_projet_structurer", limite=5)


@besoin_de_git
def test_l_apercu_de_l_engageante_est_le_meme_plan(atelier: Any, lecteur: Path) -> None:
    avant = _instantane(lecteur)
    apercu = _executer(atelier, "atelier_projet_structurer", ARGUMENTS)
    assert apercu.statut == APERCU
    a_blanc = _executer(atelier, "atelier_projet_structurer", {**ARGUMENTS, "a_blanc": True}).charge
    assert apercu.charge["apercu"] == {k: v for k, v in a_blanc.items() if k != "a_blanc"}
    assert _instantane(lecteur) == avant
    ligne = atelier.app.state.commandes.journal.lire(commande="atelier_projet_structurer", limite=1)[0]
    assert ligne["resultat"] == "apercu"


# ── Migrer ──────────────────────────────────────────────────────────────


@besoin_de_git
def test_migrer_pose_la_structure_sans_rien_remplacer(atelier: Any, lecteur: Path) -> None:
    # Du travail en cours, qui ne doit pas partir dans le commit de la migration.
    (lecteur / "index.html").write_text("(travail en cours)\n", encoding="utf-8")
    head = _git(lecteur, "rev-parse", "HEAD")
    readme = _sha(lecteur / "readme.md")

    reponse = _migrer(atelier)
    assert reponse.statut == FAIT, reponse.charge

    # Un commit, avec les seuls fichiers de la migration.
    assert _git(lecteur, "rev-parse", "HEAD~1") == head
    assert sorted(_git(lecteur, "show", "--name-only", "--pretty=format:", "HEAD").split()) == [
        ".atelier/projet.json",
        ".gitignore",
        "CLAUDE.md",
        "ETAT.md",
        "docs/cahier-des-charges.md",
        "docs/decisions/0001-structure-type.md",
    ]
    assert "Atelier-Commande: atelier_projet_structurer" in _git(lecteur, "log", "-1", "--pretty=%B")
    assert _git(lecteur, "status", "--porcelain", "--", "index.html") == "M index.html"

    # Rien de remplacé : readme.md intact, pas de second README.
    assert _sha(lecteur / "readme.md") == readme
    assert [p.name for p in lecteur.iterdir() if p.name.lower() == "readme.md"] == ["readme.md"]
    # CLAUDE.md gardé, suivi, qui importe le contexte.
    claude = (lecteur / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude.startswith("@.atelier/contexte.md\n") and "# Lecteur Grist" in claude
    assert "CLAUDE.md" in _git(lecteur, "ls-files").split("\n")
    # projet.json suivi et valide ; le reste de .atelier/ ignoré.
    fiche = structure.lire(lecteur)
    assert fiche is not None and (fiche.slug, fiche.titre) == (SLUG, "Lecteur Grist")
    assert _git(lecteur, "ls-files", ".atelier") == ".atelier/projet.json"
    assert (lecteur / ".atelier" / "contexte.md").is_file()
    assert _git(lecteur, "check-ignore", ".atelier/contexte.md", ".atelier/OPEN_CLAUDE_SESSION.md")
    etat = (lecteur / "ETAT.md").read_text(encoding="utf-8")
    assert "Lot courant : reprise dans la structure type." in etat and "## À décider" in etat

    preuve = reponse.charge["carte"]["preuve"]
    assert preuve["projet_json_suivi"] is True and preuve["contexte"] is True
    assert all(preuve["structure"][k] for k in ("projet_json", "etat", "decisions", "gitignore", "claude_md_importe_le_contexte"))
    ligne = atelier.app.state.commandes.journal.lire(commande="atelier_projet_structurer", limite=1)[0]
    assert ligne["resultat"] == "fait" and ligne["action"]["classe"] == "engageante"
    assert ligne["action"]["inverse"]["commande"] == "atelier_projet_destructurer"

    # Une seconde migration n'a plus rien à poser.
    deuxieme = _executer(atelier, "atelier_projet_structurer", {**ARGUMENTS, "a_blanc": True})
    assert deuxieme.charge["rien_a_faire"] is True


@besoin_de_git
def test_annuler_rend_le_depot_tel_qu_il_etait(atelier: Any, lecteur: Path) -> None:
    avant = _instantane(lecteur)
    suivis = _git(lecteur, "ls-files")
    reponse = _migrer(atelier)
    assert reponse.statut == FAIT, reponse.charge
    assert reponse.charge["carte"]["annuler"]["inverse"] == "atelier_projet_destructurer"

    annule = _executer(atelier, "atelier_annuler", {"action": reponse.action})
    assert annule.statut == FAIT, annule.charge
    apres = _instantane(lecteur)
    apres.pop(".atelier/contexte.md", None)  # régénéré à chaque tour, ignoré par git
    assert apres == avant
    assert _sha(lecteur / "CLAUDE.md") == EMPREINTE_CLAUDE_MD
    assert _sha(lecteur / ".gitignore") == EMPREINTE_GITIGNORE
    assert _git(lecteur, "ls-files") == suivis, "CLAUDE.md redevient non suivi"
    assert not (lecteur / "docs").exists()
    assert _git(lecteur, "log", "-1", "--pretty=%s") == "Défaire la structure type"
    assert _git(lecteur, "status", "--porcelain", "--untracked-files=no") == ""


@besoin_de_git
def test_l_inverse_refuse_si_un_fichier_a_change(atelier: Any, lecteur: Path) -> None:
    reponse = _migrer(atelier)
    (lecteur / "ETAT.md").write_text("# État repris à la main\n", encoding="utf-8")
    refus = _executer(atelier, "atelier_annuler", {"action": reponse.action})
    assert refus.statut == REFUSE and "ETAT.md" in refus.charge["erreur"]
    assert (lecteur / "docs" / "cahier-des-charges.md").is_file(), "rien n'est défait"


@besoin_de_git
def test_ce_qui_existe_est_garde_et_la_decision_prend_le_numero_suivant(atelier: Any, lecteur: Path) -> None:
    (lecteur / "ETAT.md").write_text("# État\n\nDéjà tenu.\n", encoding="utf-8")
    (lecteur / "docs" / "decisions").mkdir(parents=True)
    (lecteur / "docs" / "decisions" / "0001-moteur-asm.md").write_text("# asm.js\n", encoding="utf-8")
    reponse = _migrer(atelier)
    assert reponse.statut == FAIT, reponse.charge
    assert (lecteur / "ETAT.md").read_text(encoding="utf-8") == "# État\n\nDéjà tenu.\n"
    assert (lecteur / "docs" / "decisions" / "0002-structure-type.md").is_file()
    assert "ETAT.md" not in reponse.charge["ecrits"]


def test_projet_inconnu_ou_assistant_refuse(atelier: Any) -> None:
    for slug in ("absent", atelier.app.state.settings.assistant_slug):
        reponse = _executer(atelier, "atelier_projet_structurer", {"projet": slug, "a_blanc": True})
        assert reponse.statut == REFUSE


@besoin_de_git
def test_la_personne_confirme_l_apercu_d_un_agent(atelier: Any, lecteur: Path) -> None:
    apercu = _executer(atelier, "atelier_projet_structurer", ARGUMENTS)
    reponse = asyncio.run(atelier.app.state.commandes.confirmer(apercu.charge["confirmation"], contexte_interface()))
    assert reponse.statut == FAIT, reponse.charge
    assert structure.lire(lecteur) is not None
