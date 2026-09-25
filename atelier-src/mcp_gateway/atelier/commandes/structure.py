"""La structure type d'un projet de l'Atelier (`docs/structure-projet.md`, lot G).

Deux choses, et rien d'autre :

- le schéma de `.atelier/projet.json` (`coherence-croisee.md` §1.2), validé
  strictement : un champ inconnu, un type faux ou un chemin qui sort du projet
  sont refusés, pas ignorés ;
- le gabarit posé à la création : `CLAUDE.md`, `ETAT.md`, `README.md`,
  `docs/cahier-des-charges.md`, `docs/decisions/`, `.gitignore`.

Les champs que wikichat lit (`titre`, `description`, `slug`, `fichiers.etat`,
`fichiers.decisions`) et les rubriques d'`ETAT.md` qu'il découpe (« À décider »,
« Demandé à l'Atelier ») sont un contrat : ne pas les renommer
(`wikichat/src/projet-fichiers.mjs`).

Ce module n'importe aucun magasin : `projects.py` s'en sert pour lire un titre,
les commandes pour créer et modifier.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

CHEMIN = Path(".atelier") / "projet.json"
VERSION = 1

GABARITS = ("application", "donnees", "service-mcp", "document", "vide")
Gabarit = Literal["application", "donnees", "service-mcp", "document", "vide"]

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


class ErreurProjetJson(ValueError):
    """`projet.json` absent de ce qu'on attend : illisible, ou hors schéma."""


def _relatif_dans_le_projet(valeur: str) -> str:
    chemin = PurePosixPath(valeur.replace("\\", "/"))
    if not valeur.strip() or chemin.is_absolute() or ".." in chemin.parts:
        raise ValueError(f"chemin hors du projet : {valeur!r}")
    return str(chemin)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Fichiers(_Strict):
    etat: str = "ETAT.md"
    cahier: str = "docs/cahier-des-charges.md"
    decisions: str = "docs/decisions"

    @field_validator("etat", "cahier", "decisions")
    @classmethod
    def _dans_le_projet(cls, v: str) -> str:
        return _relatif_dans_le_projet(v)


class CommandesDuProjet(_Strict):
    """Seule source des commandes du projet (M5)."""

    preparer: str | None = None
    tests: str | None = None
    verifier: str | None = None


class GabaritDuProjet(_Strict):
    nom: Gabarit
    version: int = Field(default=1, ge=1)


class Creation(_Strict):
    par: str = Field(min_length=1, max_length=200)
    le: str = Field(min_length=10, max_length=40)


class VueEpinglee(_Strict):
    """Une vue épinglée au projet. `vue` est le chemin dans la création (`/` pour
    sa racine) ou le nom d'une vue de connecteur ; `titre` est ce qu'affiche
    l'onglet du panneau."""

    artefact: str | None = None
    connecteur: str | None = None
    vue: str = Field(min_length=1, max_length=300)
    titre: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _une_seule_origine(self) -> "VueEpinglee":
        if (self.artefact is None) == (self.connecteur is None):
            raise ValueError("une vue épinglée vient d'un artefact ou d'un connecteur, exactement")
        return self


class ProjetJson(_Strict):
    """`.atelier/projet.json` : la déclaration machine du projet."""

    version: Literal[1] = 1
    slug: str
    titre: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    famille: str | None = None
    gabarit: GabaritDuProjet | None = None
    fichiers: Fichiers = Field(default_factory=Fichiers)
    commandes: CommandesDuProjet = Field(default_factory=CommandesDuProjet)
    chemins_proteges: list[str] = Field(default_factory=list)
    vues_epinglees: list[VueEpinglee] = Field(default_factory=list)
    creation: Creation | None = None

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not _SLUG.match(v):
            raise ValueError("slug : minuscules, chiffres et tirets, 40 caractères au plus")
        return v

    @field_validator("titre")
    @classmethod
    def _titre(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("titre vide")
        return v.strip()

    @field_validator("chemins_proteges")
    @classmethod
    def _proteges(cls, v: list[str]) -> list[str]:
        return [_relatif_dans_le_projet(c) for c in v]

    def en_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


def valider(donnees: Any) -> ProjetJson:
    """Valide un `projet.json` déjà lu. Lève `ErreurProjetJson` avec la cause."""
    if not isinstance(donnees, dict):
        raise ErreurProjetJson("projet.json doit être un objet JSON")
    try:
        return ProjetJson.model_validate(donnees)
    except ValidationError as exc:
        causes = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '(racine)'} : {e['msg']}" for e in exc.errors()
        )
        raise ErreurProjetJson(f"projet.json invalide — {causes}") from None


def lire(racine: Path) -> ProjetJson | None:
    """Le `projet.json` du projet, validé ; None s'il n'y en a pas."""
    chemin = Path(racine) / CHEMIN
    if not chemin.is_file():
        return None
    try:
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ErreurProjetJson(f"projet.json illisible : {exc}") from None
    return valider(donnees)


def titre_declare(racine: Path) -> str:
    """Le titre que le projet se donne, sans jamais lever.

    Pour l'affichage : un `projet.json` invalide ne doit pas faire disparaître
    un projet de la liste. On prend son titre s'il en a un, sinon rien.
    """
    try:
        donnees = json.loads((Path(racine) / CHEMIN).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    titre = donnees.get("titre") if isinstance(donnees, dict) else None
    return titre.strip() if isinstance(titre, str) else ""


def ecrire(racine: Path, projet: ProjetJson) -> Path:
    """Écrit `projet.json`, de façon atomique. Rend son chemin."""
    chemin = Path(racine) / CHEMIN
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_suffix(".json.tmp")
    temporaire.write_text(
        json.dumps(projet.en_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporaire, chemin)
    return chemin


def slugifier(texte: str) -> str:
    """Le même slug que wikichat (`slugifier` de `projet-fichiers.mjs`)."""
    sans_accent = "".join(
        c for c in unicodedata.normalize("NFD", str(texte or "")) if unicodedata.category(c) != "Mn"
    )
    slug = re.sub(r"[^a-z0-9]+", "-", sans_accent.lower()).strip("-")
    return slug[:40].strip("-")


# ── Le gabarit ──────────────────────────────────────────────────────────

# Les rubriques qu'un lecteur (wikichat, la carte, l'Assistant) cherche par
# leur nom. Les changer casse le contrat.
RUBRIQUE_A_DECIDER = "À décider"
RUBRIQUE_DEMANDE = "Demandé à l'Atelier"

_PROCHAINE_ETAPE = {
    "application": "écrire le cahier des charges, puis une première page dans artifacts/",
    "donnees": "écrire le cahier des charges et nommer les sources de données",
    "service-mcp": "écrire le cahier des charges et la liste des outils du service",
    "document": "écrire le plan du document",
    "vide": "écrire le cahier des charges",
}


def _aujourd_hui() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def fichiers_du_gabarit(projet: ProjetJson, objectif: str) -> dict[str, str]:
    """Le contenu de chaque fichier du gabarit, par chemin relatif.

    `CLAUDE.md` ne porte ni état, ni date, ni adresse (`structure-projet.md`) :
    sa première ligne importe le contexte généré, et le socle
    (`~/work/projects/CLAUDE.md`) est lu en parent par Claude Code. L'importer
    en plus le chargerait deux fois.
    """
    nom = projet.gabarit.nom if projet.gabarit else "vide"
    but = objectif.strip() or projet.description or "à préciser"
    jour = _aujourd_hui()
    par = projet.creation.par if projet.creation else "l'Atelier"
    return {
        "CLAUDE.md": "\n".join(
            [
                "@.atelier/contexte.md",
                "",
                f"# {projet.titre}",
                "",
                f"{but}",
                "",
                "## Fil de lecture",
                "",
                "1. `ETAT.md` : où en est le projet. C'est le seul endroit de l'état.",
                "2. `docs/cahier-des-charges.md` : ce qui est voulu ; il prime sur tout.",
                "3. `docs/decisions/` : pourquoi c'est ainsi.",
                "",
                "Les règles communes (le socle, `~/work/projects/CLAUDE.md`) sont lues"
                " avant ce fichier.",
                "",
                "## Règles propres au projet",
                "",
                "- (aucune pour l'instant)",
                "",
                "## En fin de lot",
                "",
                "Réécrire `ETAT.md` (pas le compléter), consigner les décisions dans"
                " `docs/decisions/NNNN-titre.md`, puis commiter.",
                "",
            ]
        ),
        "ETAT.md": "\n".join(
            [
                f"# État — {projet.titre}",
                "",
                "Lot courant : ouverture du projet.",
                f"Dernière vérification : {jour}, structure posée par l'Atelier.",
                f"Prochaine étape : {_PROCHAINE_ETAPE.get(nom, _PROCHAINE_ETAPE['vide'])}.",
                "",
                f"## {RUBRIQUE_A_DECIDER}",
                "",
                "- rien",
                "",
                f"## {RUBRIQUE_DEMANDE}",
                "",
                "- rien",
                "",
                "## Fait et vérifié",
                "",
                f"- {jour} : structure type posée ({nom}).",
                "",
                "## Non vérifié",
                "",
                "- rien",
                "",
                "## Écarts",
                "",
                "- rien",
                "",
            ]
        ),
        "README.md": "\n".join([f"# {projet.titre}", "", but, ""]),
        "docs/cahier-des-charges.md": "\n".join(
            [
                "# Cahier des charges",
                "",
                "L'intention de la personne. Ce document prime sur tout le reste.",
                "",
                "## Objectif",
                "",
                but,
                "",
                "## Ce qui est attendu",
                "",
                "- à préciser",
                "",
            ]
        ),
        "docs/decisions/0001-structure-type.md": "\n".join(
            [
                "# Suivre la structure type de l'Atelier",
                "",
                "- Statut : acceptée",
                f"- Date : {jour}",
                "",
                "## Contexte",
                "",
                f"Projet ouvert par {par}, gabarit « {nom} ».",
                "",
                "## Décision",
                "",
                "L'état vit dans `ETAT.md` seul ; la déclaration machine dans"
                " `.atelier/projet.json` ; les décisions ici, une par fichier.",
                "",
                "## Conséquences",
                "",
                "Un agent reprend le projet en lisant `ETAT.md`, sans rien chercher ailleurs.",
                "",
            ]
        ),
    }


def poser_le_gabarit(racine: Path, projet: ProjetJson, objectif: str) -> list[str]:
    """Écrit `projet.json` et le gabarit. Ne remplace jamais un fichier présent.

    Rend les chemins écrits : c'est la preuve de ce qui a été posé.
    """
    from mcp_gateway.atelier.git_repos import GITIGNORE

    racine = Path(racine)
    racine.mkdir(parents=True, exist_ok=True)
    ecrits: list[str] = []
    contenus = {**fichiers_du_gabarit(projet, objectif), ".gitignore": GITIGNORE}
    for relatif, contenu in contenus.items():
        chemin = racine / relatif
        if chemin.exists():
            continue
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(contenu, encoding="utf-8")
        ecrits.append(relatif)
    if not (racine / CHEMIN).exists():
        ecrire(racine, projet)
        ecrits.append(str(PurePosixPath(*CHEMIN.parts)))
    return sorted(ecrits)


def verifier_la_structure(racine: Path) -> dict[str, Any]:
    """Ce qui est en place, ce qui manque : la preuve qu'on rend après création."""
    racine = Path(racine)
    projet: ProjetJson | None = None
    erreur = ""
    try:
        projet = lire(racine)
    except ErreurProjetJson as exc:
        erreur = str(exc)
    fichiers = projet.fichiers if projet else Fichiers()
    etat = racine / fichiers.etat
    texte_etat = etat.read_text(encoding="utf-8") if etat.is_file() else ""
    return {
        "projet_json": projet is not None,
        "projet_json_erreur": erreur,
        "etat": etat.is_file(),
        "rubriques": {
            RUBRIQUE_A_DECIDER: f"## {RUBRIQUE_A_DECIDER}" in texte_etat,
            RUBRIQUE_DEMANDE: f"## {RUBRIQUE_DEMANDE}" in texte_etat,
        },
        "claude_md_importe_le_contexte": (racine / "CLAUDE.md").is_file()
        and (racine / "CLAUDE.md").read_text(encoding="utf-8").startswith("@.atelier/contexte.md"),
        "decisions": (racine / fichiers.decisions).is_dir(),
        "gitignore": (racine / ".gitignore").is_file(),
    }


__all__ = [
    "CHEMIN",
    "ErreurProjetJson",
    "GABARITS",
    "ProjetJson",
    "RUBRIQUE_A_DECIDER",
    "RUBRIQUE_DEMANDE",
    "ecrire",
    "fichiers_du_gabarit",
    "lire",
    "poser_le_gabarit",
    "slugifier",
    "titre_declare",
    "valider",
    "verifier_la_structure",
]
