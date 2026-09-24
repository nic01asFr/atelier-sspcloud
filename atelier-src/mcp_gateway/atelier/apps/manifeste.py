"""L'artefact d'un projet, et son manifeste `artifacts/<nom>/artefact.json`.

Une règle unique : **un artefact est un dossier `artifacts/<nom>/`, et une
adresse** — `https://<hôte des applications>/<projet>/<nom>/`. Ce que sert
cette adresse dépend de ce que le dossier contient :

- des fichiers seulement : le mode **autonome**. Ils sont servis en bac à
  sable, pages reliées entre elles par des adresses relatives ;
- un `artefact.json` de `type: "service"` : le mode **serveur**. La même
  adresse est relayée vers le processus que l'Atelier lance et surveille.

Passer d'un mode à l'autre ne change pas l'adresse. Le manifeste ne dit
jamais où écouter : le port est attribué par l'Atelier, seul superviseur des
processus. Un manifeste qui choisirait son port choisirait aussi ce que le
mandataire peut atteindre.

D'où des règles plus strictes qu'un simple schéma :

- `commande` est une liste d'arguments passée telle quelle à `exec`, jamais
  une ligne de shell. Seules quatre substitutions existent, `{port}`,
  `{prefixe}`, `{projet}` et `{socket}` (celle-ci pour `ecoute: unix`) ; une
  accolade inconnue est une faute de frappe qu'on signale.
- Aucun champ `port`, même ignoré : on le refuse nommément.
- `repertoire` part du dossier de l'artefact ; il peut remonter dans le
  projet (`"../.."` pour un service dont le code vit à la racine), jamais en
  sortir — liens symboliques compris.
- `secrets` ne porte que des références vers `~/work/.secrets/apps/<ref>`.
- `acces` ne connaît que `proprietaire` en version 1.
- Un artefact autonome peut déclarer `"type": "statique", "edition": true` :
  ses pages écrivent alors chez elles par `PUT` (sinon, lecture seule).

Le modèle est strict (pas de conversion de `"90"` en 90) et fermé (tout champ
inconnu est refusé) : un manifeste est écrit par des agents, et une clé mal
orthographiée qui passerait en silence laisserait croire à un réglage qui
n'existe pas. `artefact.json` et tout nom qui commence par un point ne sont
jamais servis, ni écrasables par une page.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

VERSION = 1

# Le dossier des artefacts d'un projet, et le manifeste d'un artefact.
DOSSIER_ARTEFACTS = "artifacts"
FICHIER_MANIFESTE = "artefact.json"
# Qui a créé l'artefact : un identifiant de conversation, en clair.
FICHIER_AUTEUR = ".auteur"

# Un nom finit dans une URL (`/<slug>/<nom>/`), un chemin de journal et une
# clé d'état. Minuscules, chiffres et tirets ; il commence par une lettre ou
# un chiffre, ce qui laisse `_atelier` hors d'atteinte : ce segment est
# réservé par l'hôte des applications.
_NOM = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")

# Une référence de secret est un nom de fichier dans `~/work/.secrets/apps`,
# sans séparateur ni `..` : elle ne doit pas pouvoir remonter l'arborescence.
_REF_SECRET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# Nom de variable d'environnement, en majuscules par convention.
_VARIABLE = re.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")

# Ce que l'Atelier pose lui-même dans l'environnement d'une application. Un
# manifeste ne peut pas les remplacer : le proxy et l'application doivent
# s'accorder sur leur valeur.
VARIABLES_RESERVEES = frozenset(
    {"PATH", "HOME", "LANG", "PORT", "VIRTUAL_ENV", "PYTHONUNBUFFERED"}
)
# Tout `ATELIER_*` est réservé : les variables du service n'ont rien à faire
# chez une application, et celles qu'on lui donne (`ATELIER_APP_*`) viennent
# de l'Atelier.
PREFIXE_RESERVE = "ATELIER_"

_SUBSTITUTION = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
SUBSTITUTIONS = ("port", "prefixe", "projet", "socket")


class ManifesteInvalide(ValueError):
    """Un manifeste qu'on ne lancera pas, avec la raison lisible."""


class ArtefactInconnu(LookupError):
    """Pas de dossier `artifacts/<nom>/` dans ce projet."""


def nom_valide(nom: str) -> bool:
    return bool(_NOM.match(nom or ""))


def _variable_autorisee(nom: str) -> str | None:
    """La raison du refus d'un nom de variable, ou None s'il passe."""
    if not _VARIABLE.match(nom):
        return f"nom de variable invalide : {nom!r} (majuscules, chiffres, _)"
    if nom.startswith(PREFIXE_RESERVE):
        return f"variable réservée à l'Atelier : {nom}"
    if nom in VARIABLES_RESERVEES:
        return f"variable posée par l'Atelier : {nom}"
    return None


class Manifeste(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    version: Literal[1]
    titre: str = Field(default="", max_length=80)
    type: Literal["service", "statique"] = "service"
    commande: Optional[list[str]] = None
    # Relatif au dossier de l'artefact ; peut remonter dans le projet.
    repertoire: str = "."
    # Artefact autonome : ses pages peuvent-elles écrire chez elles ?
    edition: bool = False
    ecoute: Literal["port", "unix"] = "port"
    # `retire` : l'application voit `/` ; `garde` : elle voit `/<slug>/<nom>/`.
    chemin: Literal["retire", "garde"] = "retire"
    # Chemin sondé pour savoir l'application prête. Absent : on se contente
    # d'une connexion qui aboutit.
    sante: Optional[str] = None
    demarrage_s: int = Field(default=60, ge=1, le=600)
    # Absent : le réglage de l'Atelier (`ATELIER_APPS_IDLE_MINUTES`).
    inactivite_min: Optional[int] = Field(default=None, ge=1, le=1440)
    protocoles: list[Literal["http", "ws", "sse"]] = Field(default_factory=lambda: ["http"])
    corps_max_mo: int = Field(default=100, ge=1, le=4096)
    env: dict[str, str] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)
    acces: Literal["proprietaire"] = "proprietaire"

    @model_validator(mode="before")
    @classmethod
    def _pas_de_port(cls, donnees: object) -> object:
        if isinstance(donnees, dict) and "port" in donnees:
            raise ValueError(
                "le champ `port` n'existe pas : l'Atelier attribue le port ; "
                "utilisez `{port}` dans `commande` ou la variable PORT"
            )
        return donnees

    @field_validator("commande")
    @classmethod
    def _commande(cls, valeur: Optional[list[str]]) -> Optional[list[str]]:
        if valeur is None:
            return None
        if not valeur or not valeur[0].strip():
            raise ValueError("`commande` doit nommer un programme")
        for argument in valeur:
            if "\x00" in argument:
                raise ValueError("`commande` contient un octet nul")
            for nom in _SUBSTITUTION.findall(argument):
                if nom not in SUBSTITUTIONS:
                    raise ValueError(
                        f"substitution inconnue {{{nom}}} ; seules existent "
                        + ", ".join("{" + s + "}" for s in SUBSTITUTIONS)
                    )
        return valeur

    @field_validator("repertoire")
    @classmethod
    def _relatif(cls, valeur: str) -> str:
        if not valeur.strip() or "\x00" in valeur:
            raise ValueError("chemin vide")
        chemin = Path(valeur)
        if chemin.is_absolute() or valeur.startswith(("/", "\\")) or chemin.drive:
            raise ValueError(f"chemin absolu refusé : {valeur!r} (relatif au dossier de l'artefact)")
        return valeur

    @field_validator("sante")
    @classmethod
    def _sante(cls, valeur: Optional[str]) -> Optional[str]:
        if valeur is None:
            return None
        if not valeur.startswith("/") or valeur.startswith("//") or any(c.isspace() for c in valeur):
            raise ValueError("`sante` est un chemin qui commence par un seul /")
        return valeur

    @field_validator("protocoles")
    @classmethod
    def _protocoles(cls, valeur: list[str]) -> list[str]:
        if not valeur:
            raise ValueError("`protocoles` ne peut pas être vide")
        if len(set(valeur)) != len(valeur):
            raise ValueError("`protocoles` contient un doublon")
        if "http" not in valeur:
            raise ValueError("`protocoles` doit contenir http")
        return valeur

    @field_validator("env")
    @classmethod
    def _env(cls, valeur: dict[str, str]) -> dict[str, str]:
        for nom, contenu in valeur.items():
            raison = _variable_autorisee(nom)
            if raison:
                raise ValueError(raison)
            if "\x00" in contenu:
                raise ValueError(f"valeur de {nom} : octet nul")
        return valeur

    @field_validator("secrets")
    @classmethod
    def _secrets(cls, valeur: dict[str, str]) -> dict[str, str]:
        for nom, reference in valeur.items():
            raison = _variable_autorisee(nom)
            if raison:
                raise ValueError(raison)
            if not _REF_SECRET.match(reference) or ".." in reference:
                raise ValueError(
                    f"référence de secret invalide pour {nom} : {reference!r} "
                    "(un nom de fichier de ~/work/.secrets/apps)"
                )
        return valeur

    @model_validator(mode="after")
    def _coherence(self) -> "Manifeste":
        if self.type == "service":
            if not self.commande:
                raise ValueError("un artefact `service` exige `commande`")
            if self.edition:
                raise ValueError("`edition` est réservée aux artefacts `statique`")
            utilisees = {n for a in self.commande for n in _SUBSTITUTION.findall(a)}
            if self.ecoute == "unix":
                if "socket" not in utilisees:
                    raise ValueError("`ecoute: unix` exige {socket} dans `commande`")
                if "port" in utilisees:
                    raise ValueError("`ecoute: unix` n'a pas de port : retirez {port}")
            elif "socket" in utilisees:
                raise ValueError("{socket} n'existe qu'avec `ecoute: unix`")
        else:
            if self.commande is not None:
                raise ValueError("un artefact `statique` n'a pas de `commande`")
            if self.secrets or self.env:
                raise ValueError("un artefact `statique` n'a ni `env` ni `secrets`")
        doubles = set(self.env) & set(self.secrets)
        if doubles:
            raise ValueError("variables à la fois dans env et secrets : " + ", ".join(sorted(doubles)))
        return self

    # --- Usage -----------------------------------------------------------

    @property
    def service(self) -> bool:
        return self.type == "service"

    def arguments(
        self,
        *,
        port: int | None,
        prefixe: str,
        projet: Path,
        socket: Path | None = None,
    ) -> list[str]:
        """La commande prête pour `exec`, substitutions faites.

        Remplacement littéral, pas `str.format` : un argument qui contient
        d'autres accolades (du JSON, un gabarit) reste intact.
        """
        valeurs = {
            "port": "" if port is None else str(port),
            "prefixe": prefixe,
            "projet": str(projet),
            "socket": "" if socket is None else str(socket),
        }

        def remplacer(m: re.Match[str]) -> str:
            return valeurs[m.group(1)]

        return [_SUBSTITUTION.sub(remplacer, a) for a in (self.commande or [])]

    def dossier_de_travail(self, racine_projet: Path, nom: str) -> Path:
        """Le dossier où la commande s'exécute : sous le projet, jamais ailleurs."""
        return dossier_dans_le_projet(racine_projet, dossier_artefact(racine_projet, nom), self.repertoire)


def dossier_artefact(racine_projet: Path, nom: str) -> Path:
    if not nom_valide(nom):
        raise ArtefactInconnu(f"nom d'artefact invalide : {nom!r} (minuscules, chiffres, tirets ; 40 au plus)")
    return racine_projet / DOSSIER_ARTEFACTS / nom


def dossier_dans_le_projet(racine_projet: Path, depart: Path, relatif: str) -> Path:
    """Le dossier résolu, liens suivis, s'il reste dans le projet et existe."""
    base = racine_projet.resolve()
    cible = (depart / relatif).resolve()
    if cible != base and base not in cible.parents:
        raise ManifesteInvalide(f"le dossier {relatif!r} sort du projet")
    if not cible.is_dir():
        raise ManifesteInvalide(f"le dossier {relatif!r} n'existe pas dans le projet")
    return cible


def _message(exc: ValidationError) -> str:
    morceaux = []
    for erreur in exc.errors():
        lieu = ".".join(str(p) for p in erreur.get("loc", ()) if p != "__root__")
        texte = str(erreur.get("msg", "")).removeprefix("Value error, ")
        morceaux.append(f"{lieu} : {texte}" if lieu else texte)
    return " ; ".join(morceaux)


def lire_manifeste(donnees: object) -> Manifeste:
    """Valide un manifeste déjà décodé ; `ManifesteInvalide` sinon."""
    try:
        return Manifeste.model_validate(donnees)
    except ValidationError as exc:
        raise ManifesteInvalide(_message(exc)) from None


def charger_manifeste(racine_projet: Path, nom: str) -> Manifeste | None:
    """Le manifeste de l'artefact, ou None s'il est autonome (pas de manifeste).

    Lève `ArtefactInconnu` si le dossier n'existe pas, `ManifesteInvalide`
    si le manifeste ne se lit pas ou sort du projet. Le dossier et le
    manifeste doivent rester dans le projet : un `artifacts` qui serait un
    lien vers ailleurs ferait lancer ce qu'aucun commit du projet ne dit.
    """
    dossier = dossier_artefact(racine_projet, nom)
    base = racine_projet.resolve()
    if dossier.is_symlink() or not dossier.is_dir():
        raise ArtefactInconnu(f"aucun artefact {DOSSIER_ARTEFACTS}/{nom}/")
    if base not in dossier.resolve().parents:
        raise ManifesteInvalide(f"l'artefact {nom} sort du projet")
    chemin = dossier / FICHIER_MANIFESTE
    if chemin.is_symlink():
        raise ManifesteInvalide(f"{FICHIER_MANIFESTE} de {nom} est un lien")
    if not chemin.is_file():
        return None
    try:
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifesteInvalide(f"manifeste de {nom} illisible : {exc}") from None
    manifeste = lire_manifeste(donnees)
    if manifeste.service:
        manifeste.dossier_de_travail(racine_projet, nom)
    return manifeste


def lister_artefacts(racine_projet: Path) -> tuple[dict[str, Manifeste | None], dict[str, str]]:
    """Les artefacts d'un projet (None = autonome sans manifeste), et à part ceux en erreur.

    Un manifeste faux n'empêche pas les autres de s'afficher : le panneau
    montre l'erreur à côté de l'artefact, pour qu'on la corrige. Les dossiers
    dont le nom n'est pas une adresse possible sont ignorés.
    """
    valides: dict[str, Manifeste | None] = {}
    erreurs: dict[str, str] = {}
    dossier = racine_projet / DOSSIER_ARTEFACTS
    if not dossier.is_dir() or dossier.is_symlink():
        return valides, erreurs
    for enfant in sorted(dossier.iterdir()):
        if not enfant.is_dir() or not nom_valide(enfant.name):
            continue
        try:
            valides[enfant.name] = charger_manifeste(racine_projet, enfant.name)
        except (ManifesteInvalide, ArtefactInconnu) as exc:
            erreurs[enfant.name] = str(exc)
    return valides, erreurs


def lire_auteur(racine_projet: Path, nom: str) -> str:
    try:
        chemin = dossier_artefact(racine_projet, nom) / FICHIER_AUTEUR
        return chemin.read_text(encoding="utf-8").strip()[:200] if chemin.is_file() else ""
    except (OSError, ArtefactInconnu):
        return ""
