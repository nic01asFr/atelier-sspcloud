"""Les agents lancés par l'Atelier (lot D) et les réparations des gardiens (G5).

Avant ce module, wikichat lançait `claude -p` lui-même : un réveil sur
mention, une routine, un trigger tournaient hors de l'Atelier, sans fiche,
sans le profil du projet, avec un mode à part, et personne ne les voyait.
Désormais ils **demandent** le lancement ici. L'Atelier :

- crée une conversation (une fiche, donc une identité) dans le projet visé,
  ou reprend celle que l'agent avait déjà ;
- lui applique le profil `code` du projet (le serveur `atelier` et wikichat le
  déduisent de la fiche), le mode du projet, et les plafonds : durée, nombre
  simultané, nombre par jour et par origine (décision J-b) ;
- la montre dans l'interface comme toute conversation (`lance_par` sur la
  fiche) ;
- journalise le lancement et sa fin au journal unique.

**Deux portes, une règle.**

- La commande `atelier_lancer_agent`, classe `engageante` : un modèle
  (l'Assistant) reçoit un aperçu et un jeton, et rien ne part avant le « Oui »
  de la personne.
- La route interne `POST /v1/lancements`, pour wikichat et l'exécuteur des
  gardiens. Elle n'accepte que la clé du lanceur (`~/work/.secrets/
  atelier_lanceur_key`, en-tête `X-Atelier-Lanceur`), ni la clé du
  propriétaire ni la session de l'interface. Elle passe par la même commande,
  en contexte `automate` : l'accord a été donné par la personne quand elle a
  activé le trigger ou la routine (J-b2), et les plafonds tiennent quand même.

**Sur une branche.** Un lancement qui porte `branche` travaille dans une
copie du projet (`git worktree`, sous `<projet>/.atelier/reparations/<id>`),
jamais dans le dossier du projet. L'agent ne peut ni pousser ni déplacer une
autre branche que la sienne : règles de permission refusées au CLI, crochets
git (`reference-transaction`, `pre-push`) et réécriture des adresses d'envoi,
posés par l'environnement du tour. À la fin du tour, l'Atelier (le code, pas
le modèle) vérifie que la branche de base n'a pas bougé et dépose la
proposition dans « À valider » : l'avant (constat, base), l'après (commits,
écart, extrait), et l'action de fusion, `atelier_reparation_fusionner`,
réservée à la personne. Rien n'est jamais poussé.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Annotated

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from mcp_gateway.atelier.commandes.modele import (
    ENGAGEANTE,
    LECTURE,
    RESERVEE,
    Commande,
    Contexte,
    Effet,
    Refus,
)

log = logging.getLogger("atelier.lancements")

ENTETE_CLE = "X-Atelier-Lanceur"
NOM_DU_FICHIER_DE_CLE = "atelier_lanceur_key"
ORIGINE_AUTOMATE = "automate"

EN_COURS = "en_cours"
FINI = "fini"
ECHEC = "echec"
DELAI = "delai"
ARRETE = "arrete"
INTERROMPU = "interrompu"
ETATS_FINAUX = (FINI, ECHEC, DELAI, ARRETE, INTERROMPU)

PREFIXE_GARDIEN = "gardien:"
BRANCHES_PERMISES = ("gardien/", "agent/")
_NOM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,79}$")
_NOMS_GENERIQUES = {"atelier", "poste"}
_ID = re.compile(r"^lc-[0-9]{8}-[0-9a-f]{8}$")
DOSSIER_DES_COPIES = Path(".atelier") / "reparations"

# Les fichiers que l'Atelier dépose dans un projet sans les versionner : une
# copie de travail doit les avoir aussi, sinon l'agent y recevrait d'autres
# connecteurs, un autre mode par défaut.
FICHIERS_DE_LIAISON = (
    Path(".mcp.json"),
    Path(".atelier") / "connecteurs-choisis.json",
    Path(".atelier") / "connecteurs-herites",
    Path(".claude") / "settings.local.json",
)


# ── Plafonds ─────────────────────────────────────────────────────────────────


def _entier(nom: str, defaut: int) -> int:
    try:
        return int(os.environ.get(nom) or defaut)
    except ValueError:
        return defaut


@dataclass
class Plafonds:
    """Les bornes des agents lancés. Tenues ici, quel que soit l'appelant.

    `par_origine_jour` reprend le `max_per_day` des triggers de wikichat (J-b,
    24) ; `reparations_par_jour` et la durée des réparations, les plafonds des
    gardiens (`gardiens.md` §3.2 : 3 par jour, une à la fois par projet).
    """

    simultanes: int = 3
    par_jour: int = 100
    par_origine_jour: int = 24
    duree_defaut_s: int = 900
    duree_max_s: int = 1800
    reparations_par_jour: int = 3

    @classmethod
    def depuis_l_environnement(cls) -> "Plafonds":
        return cls(
            simultanes=_entier("ATELIER_LANCEMENTS_SIMULTANES", 3),
            par_jour=_entier("ATELIER_LANCEMENTS_PAR_JOUR", 100),
            par_origine_jour=_entier("ATELIER_LANCEMENTS_PAR_ORIGINE", 24),
            duree_defaut_s=_entier("ATELIER_LANCEMENTS_DUREE_S", 900),
            duree_max_s=_entier("ATELIER_LANCEMENTS_DUREE_MAX_S", 1800),
            reparations_par_jour=_entier("ATELIER_REPARATIONS_PAR_JOUR", 3),
        )


# ── La clé du lanceur ────────────────────────────────────────────────────────


def chemin_de_la_cle(settings: Any) -> Path:
    return Path(settings.secrets_dir) / NOM_DU_FICHIER_DE_CLE


def assurer_la_cle(settings: Any) -> str:
    """La clé de la route interne, créée à la première demande (0600).

    Distincte de la clé du propriétaire : qui la porte peut demander un
    lancement, dans les plafonds, et rien d'autre. Lue par wikichat et par
    l'exécuteur des gardiens ; jamais journalisée.
    """
    chemin = chemin_de_la_cle(settings)
    try:
        existante = chemin.read_text(encoding="utf-8").strip()
    except OSError:
        existante = ""
    if existante:
        return existante
    chemin.parent.mkdir(parents=True, exist_ok=True)
    cle = secrets.token_urlsafe(32)
    provisoire = chemin.with_name(chemin.name + ".tmp")
    provisoire.write_text(cle + "\n", encoding="utf-8")
    try:
        os.chmod(provisoire, 0o600)
    except OSError:
        pass
    os.replace(provisoire, chemin)
    return cle


def lire_la_cle(settings: Any) -> str:
    try:
        return chemin_de_la_cle(settings).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


# ── Le lancement ─────────────────────────────────────────────────────────────


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _jour(quand: str) -> str:
    return (quand or "")[:10]


@dataclass
class Lancement:
    id: str
    origine: str
    acteur: str
    projet: str
    conversation: str = ""
    nom: str = ""
    mode: str = ""
    avertissements: list[str] = field(default_factory=list)
    plafonds: dict[str, Any] = field(default_factory=dict)
    etat: str = EN_COURS
    cree_le: str = ""
    fini_le: str = ""
    texte: str = ""
    erreur: str = ""
    message: str = ""
    outils: list[str] = field(default_factory=list)
    # Sur une branche : la copie de travail, la branche, la base et son commit.
    branche: str = ""
    copie: str = ""
    base: str = ""
    base_commit: str = ""
    # Une réparation d'un gardien : le constat qui l'a fait naître.
    reparation: dict[str, Any] | None = None
    # Ce que l'Atelier a conclu : la proposition déposée, ou pourquoi aucune.
    proposition: str = ""
    conclusion: dict[str, Any] = field(default_factory=dict)

    def en_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def depuis(cls, brut: dict[str, Any]) -> "Lancement":
        champs = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in brut.items() if k in champs})


def _git(dossier: Path, *args: str, env: dict[str, str] | None = None, delai: float = 30.0) -> tuple[int, str]:
    """Une commande git dans `dossier`, sans shell. Rend (code, sortie)."""
    try:
        fini = subprocess.run(  # noqa: S603 — arguments fixés ici
            ["git", *args],
            cwd=str(dossier),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=delai,
            env={**os.environ, **(env or {})},
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    sortie = (fini.stdout or "").strip()
    if fini.returncode:
        sortie = (sortie + "\n" + (fini.stderr or "").strip()).strip()
    return fini.returncode, sortie


# ── Les gardes d'une copie de travail ────────────────────────────────────────

CROCHET_TRANSACTION = """#!/bin/sh
# Pose par l'Atelier pour une copie de travail sur branche (lancements.py).
# Seule la branche de l'agent peut bouger ; main et les autres, jamais.
[ "$1" = "prepared" ] || exit 0
while read ancien nouveau ref; do
  case "$ref" in
    "$ATELIER_BRANCHE_PERMISE") ;;
    refs/heads/*|refs/tags/*)
      echo "Atelier : $ref ne peut pas bouger depuis cette copie (seule $ATELIER_BRANCHE_PERMISE le peut)." >&2
      exit 1 ;;
  esac
done
exit 0
"""

CROCHET_ENVOI = """#!/bin/sh
# Pose par l'Atelier : un agent lance ne pousse jamais. La personne fusionne.
echo "Atelier : envoi refuse depuis une copie de travail d'agent. La proposition attend dans A valider." >&2
exit 1
"""

# Les crochets du dépôt restent joués : `core.hooksPath` les remplacerait tous.
CROCHET_RELAIS = """#!/bin/sh
h="$(git rev-parse --git-common-dir)/hooks/$(basename "$0")"
[ -x "$h" ] && exec "$h" "$@"
exit 0
"""
CROCHETS_RELAYES = ("pre-commit", "prepare-commit-msg", "commit-msg", "post-commit", "pre-rebase", "post-checkout", "post-merge")

PREFIXES_D_ENVOI = ("https://", "http://", "ssh://", "git://", "git@", "file://")


def assurer_les_crochets(settings: Any) -> Path:
    dossier = Path(settings.work_dir) / ".atelier-etat" / "lancements" / "crochets"
    dossier.mkdir(parents=True, exist_ok=True)
    contenus = {"reference-transaction": CROCHET_TRANSACTION, "pre-push": CROCHET_ENVOI}
    contenus.update({nom: CROCHET_RELAIS for nom in CROCHETS_RELAYES})
    for nom, contenu in contenus.items():
        chemin = dossier / nom
        if not chemin.is_file() or chemin.read_text(encoding="utf-8") != contenu:
            chemin.write_text(contenu, encoding="utf-8", newline="\n")
        try:
            os.chmod(chemin, 0o755)
        except OSError:
            pass
    return dossier


def adresse_refusee(settings: Any) -> str:
    """Où partirait un envoi : un chemin qui n'est pas un dépôt."""
    return str(Path(settings.work_dir) / ".atelier-etat" / "lancements" / "envoi-refuse" / "aucun-depot").replace("\\", "/")


def environnement_de_la_copie(settings: Any, projet: Path, branche: str) -> dict[str, str]:
    """L'environnement git d'un agent sur branche : ce que tous ses `git` hériteront.

    - `core.hooksPath` vers les crochets de l'Atelier : `reference-transaction`
      refuse tout déplacement d'une branche qui n'est pas la sienne (main
      compris, et même par `git update-ref`), `pre-push` refuse l'envoi ;
    - `url.<nulle part>.pushInsteadOf` pour les adresses des remotes du projet
      et les schémas courants : un envoi, même `--no-verify`, part vers un
      dossier qui n'est pas un dépôt.

    C'est une garde, pas une prison : un agent décidé à contourner son
    environnement le peut. La vérification de fin de tour (la base n'a pas
    bougé) et les règles refusées au CLI sont les deux autres ceintures.
    """
    crochets = assurer_les_crochets(settings)
    nulle_part = adresse_refusee(settings)
    prefixes = list(PREFIXES_D_ENVOI)
    if os.name != "nt":
        prefixes.append("/")
    code, remotes = _git(projet, "remote")
    if code == 0:
        for remote in remotes.split():
            for option in ("--push", "--all"):
                c, adresse = _git(projet, "remote", "get-url", option, remote)
                if c == 0:
                    prefixes.extend(a.strip() for a in adresse.splitlines() if a.strip())
    paires = [("core.hooksPath", str(crochets).replace("\\", "/"))]
    for prefixe in dict.fromkeys(prefixes):
        paires.append((f"url.{nulle_part}.pushInsteadOf", prefixe))
    env = {"GIT_CONFIG_COUNT": str(len(paires))}
    for i, (cle, valeur) in enumerate(paires):
        env[f"GIT_CONFIG_KEY_{i}"] = cle
        env[f"GIT_CONFIG_VALUE_{i}"] = valeur
    env["ATELIER_BRANCHE_PERMISE"] = f"refs/heads/{branche}"
    env["ATELIER_COPIE_DE_TRAVAIL"] = "1"
    return env


# Refusées au CLI pour un agent sur branche : un refus l'emporte sur tout mode.
REGLES_REFUSEES_SUR_BRANCHE = [
    "Bash(git push:*)",
    "Bash(git push)",
    "Bash(git checkout main:*)",
    "Bash(git switch main:*)",
    "Bash(git merge:*)",
    "Bash(git rebase:*)",
    "Bash(git reset --hard:*)",
    "Bash(git update-ref:*)",
    "Bash(git branch -f:*)",
    "Bash(git branch -D:*)",
    "Bash(git worktree:*)",
    "Bash(gh pr merge:*)",
]


# ── Le lanceur ───────────────────────────────────────────────────────────────


class Lanceur:
    def __init__(
        self,
        settings: Any,
        store: Any,
        *,
        projects: Any = None,
        file: Any = None,
        journal: Any = None,
        plafonds: Plafonds | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.projects = projects
        self.file = file
        self.journal = journal
        self.plafonds = plafonds or Plafonds.depuis_l_environnement()
        self.dossier = Path(settings.work_dir) / ".atelier-etat" / "lancements"
        self._verrou = threading.RLock()
        self._fils: dict[str, threading.Thread] = {}

    # ── stockage ────────────────────────────────────────────────────────

    def _chemin(self, identifiant: str) -> Path:
        if not _ID.match(identifiant or ""):
            raise Refus(f"lancement inconnu : {identifiant}")
        return self.dossier / f"{identifiant}.json"

    def _ecrire(self, lancement: Lancement) -> None:
        self.dossier.mkdir(parents=True, exist_ok=True)
        chemin = self._chemin(lancement.id)
        provisoire = chemin.with_name(chemin.name + f".{secrets.token_hex(3)}.tmp")
        provisoire.write_text(json.dumps(lancement.en_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        for essai in range(10):
            try:
                os.replace(provisoire, chemin)
                return
            except PermissionError:
                if essai == 9:
                    raise
                time.sleep(0.02)

    def lire(self, identifiant: str) -> Lancement | None:
        try:
            brut = json.loads(self._chemin(identifiant).read_text(encoding="utf-8"))
        except (OSError, ValueError, Refus):
            return None
        return Lancement.depuis(brut) if isinstance(brut, dict) else None

    def tous(self) -> list[Lancement]:
        if not self.dossier.is_dir():
            return []
        sortie = []
        for fichier in self.dossier.glob("lc-*.json"):
            try:
                brut = json.loads(fichier.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(brut, dict):
                sortie.append(Lancement.depuis(brut))
        sortie.sort(key=lambda l: l.cree_le, reverse=True)
        return sortie

    def lister(self, *, etat: str = "", origine: str = "", projet: str = "", limite: int = 100) -> list[Lancement]:
        sortie = [
            l
            for l in self.tous()
            if (not etat or l.etat == etat)
            and (not origine or l.origine.startswith(origine))
            and (not projet or l.projet == projet)
        ]
        return sortie[: max(1, min(limite, 500))]

    def reconcilier(self) -> list[str]:
        """Au démarrage : un lancement « en cours » sans fil qui le joue a été interrompu."""
        repris = []
        for l in self.tous():
            if l.etat == EN_COURS and l.id not in self._fils:
                l.etat = INTERROMPU
                l.erreur = l.erreur or "l'Atelier a redémarré pendant le tour"
                l.fini_le = _maintenant()
                self._ecrire(l)
                repris.append(l.id)
        return repris

    # ── validation d'une demande ───────────────────────────────────────

    def _projet(self, demande: dict[str, Any]) -> tuple[str, Path]:
        slug = str(demande.get("projet") or "").strip()
        dossier_demande = str(demande.get("dossier") or "").strip()
        racine = Path(self.settings.projects_dir).resolve()
        if not slug and dossier_demande:
            try:
                relatif = Path(dossier_demande).resolve().relative_to(racine)
                slug = relatif.parts[0] if relatif.parts else ""
            except (ValueError, OSError):
                slug = ""
            if not slug:
                slug = self.settings.default_slug
        if not slug:
            raise Refus("projet requis")
        if slug == getattr(self.settings, "assistant_slug", None):
            raise Refus("un agent lancé travaille dans un projet (profil code), pas dans le dossier de l'Assistant")
        if "/" in slug or "\\" in slug or slug in (".", ".."):
            raise Refus(f"projet invalide : {slug}")
        if self.projects is not None:
            tous = self.projects.list_projects(include_archived=True)
            connus = {p.slug for p in tous} | {self.settings.default_slug}
            if slug not in connus:
                raise Refus(f"projet inconnu : {slug}")
            if any(p.slug == slug and getattr(p, "archived", False) for p in tous):
                raise Refus(f"projet rangé : {slug} ; un agent lancé là ne se verrait pas")
        dossier = racine / slug
        return slug, dossier

    def _mode(
        self, dossier: Path, demande: dict[str, Any], origine: str
    ) -> tuple[str, list[str]]:
        """Le mode du tour : demandé, sinon celui du projet, sinon du service.

        `bypassPermissions` ne s'obtient pas en le demandant : il faut que la
        demande vienne d'une définition persistée (routine ou trigger, activée
        par la personne) **et** que le projet l'accorde lui-même. Un réparateur
        ne l'a jamais (`gardiens.md` §3.3).
        """
        from mcp_gateway.atelier.modes_permission import BYPASS, mode_du_projet, mode_du_service, normaliser

        avertissements: list[str] = []
        du_projet = mode_du_projet(dossier)
        base = du_projet or mode_du_service(self.settings) or "acceptEdits"
        gardien = origine.startswith(PREFIXE_GARDIEN)
        if base == BYPASS and (gardien or du_projet != BYPASS):
            base = "acceptEdits"
        brut = str(demande.get("mode") or "").strip()
        if not brut:
            return base, avertissements
        if brut == "dontAsk":
            # Sans interlocuteur, `default` refuse ce qui n'est pas permis :
            # c'est ce que `dontAsk` demandait.
            brut = "default"
        voulu = normaliser(brut)
        if not voulu:
            avertissements.append(f"mode inconnu « {brut} » : {base} retenu")
            return base, avertissements
        if voulu == BYPASS:
            definition = demande.get("mode_de_la_definition") is True
            if gardien or not definition or du_projet != BYPASS:
                avertissements.append(
                    "bypassPermissions non accordé (il faut une définition de routine ou de "
                    f"trigger et un projet qui l'accorde) : {base} retenu"
                )
                return base, avertissements
        return voulu, avertissements

    def _duree(self, demande: dict[str, Any], exiger: bool, avertissements: list[str]) -> int:
        plafonds = demande.get("plafonds") if isinstance(demande.get("plafonds"), dict) else {}
        brut = plafonds.get("duree_s", demande.get("duree_s"))
        if brut in (None, ""):
            if exiger:
                raise Refus("plafonds.duree_s requis : une tâche automatique déclare sa durée (J-b)")
            return self.plafonds.duree_defaut_s
        try:
            duree = int(brut)
        except (TypeError, ValueError):
            raise Refus("plafonds.duree_s : un nombre de secondes") from None
        if duree <= 0:
            raise Refus("plafonds.duree_s : positif")
        if duree > self.plafonds.duree_max_s:
            avertissements.append(f"durée ramenée de {duree} s à {self.plafonds.duree_max_s} s (plafond)")
            duree = self.plafonds.duree_max_s
        return duree

    def _verifier_les_plafonds(self, origine: str, slug: str, branche: str) -> None:
        aujourd_hui = _jour(_maintenant())
        tous = self.tous()
        en_cours = [l for l in tous if l.etat == EN_COURS]
        if len(en_cours) >= self.plafonds.simultanes:
            raise Refus(
                f"plafond atteint : {len(en_cours)} agents lancés tournent déjà "
                f"(au plus {self.plafonds.simultanes} à la fois)"
            )
        du_jour = [l for l in tous if _jour(l.cree_le) == aujourd_hui]
        if len(du_jour) >= self.plafonds.par_jour:
            raise Refus(f"plafond atteint : {len(du_jour)} lancements aujourd'hui (au plus {self.plafonds.par_jour})")
        meme_origine = [l for l in du_jour if l.origine == origine]
        if len(meme_origine) >= self.plafonds.par_origine_jour:
            raise Refus(
                f"plafond atteint : {len(meme_origine)} lancements aujourd'hui pour {origine} "
                f"(au plus {self.plafonds.par_origine_jour})"
            )
        if origine.startswith(PREFIXE_GARDIEN):
            reparations = [l for l in du_jour if l.origine.startswith(PREFIXE_GARDIEN)]
            if len(reparations) >= self.plafonds.reparations_par_jour:
                raise Refus(
                    f"plafond atteint : {len(reparations)} réparations aujourd'hui "
                    f"(au plus {self.plafonds.reparations_par_jour})"
                )
        if branche and any(l.projet == slug and l.branche for l in en_cours):
            raise Refus(f"une copie de travail tourne déjà pour {slug} : une à la fois par projet")

    def _branche(self, demande: dict[str, Any], origine: str, identifiant: str) -> str:
        branche = str(demande.get("branche") or "").strip()
        if origine.startswith(PREFIXE_GARDIEN) and not branche:
            raise Refus("une réparation d'un gardien travaille sur une branche `gardien/…`")
        if not branche:
            return ""
        if origine.startswith(PREFIXE_GARDIEN) and not branche.startswith("gardien/"):
            raise Refus("la branche d'une réparation commence par gardien/")
        if not branche.startswith(BRANCHES_PERMISES):
            raise Refus(f"branche refusée : {branche} (préfixes permis : {', '.join(BRANCHES_PERMISES)})")
        if not re.fullmatch(r"[A-Za-z0-9._/-]{3,120}", branche) or ".." in branche or branche.endswith((".lock", "/", ".")):
            raise Refus(f"nom de branche invalide : {branche}")
        return branche

    # ── lancer ─────────────────────────────────────────────────────────

    def apercu(self, demande: dict[str, Any], origine: str) -> dict[str, Any]:
        """Ce que ferait le lancement, sans rien faire : l'aperçu d'une commande engageante."""
        slug, dossier = self._projet(demande)
        mode, avertissements = self._mode(dossier, demande, origine)
        duree = self._duree(demande, False, avertissements)
        return {
            "projet": slug,
            "nom": str(demande.get("nom") or "").strip() or None,
            "mode": mode,
            "duree_s": duree,
            "branche": str(demande.get("branche") or "") or None,
            "message": str(demande.get("message") or "")[:500],
            "avertissements": avertissements,
            "plafonds": asdict(self.plafonds),
        }

    def lancer(self, demande: dict[str, Any], *, acteur: str, origine: str, exiger_duree: bool) -> Lancement:
        message = str(demande.get("message") or "")
        if not message.strip():
            raise Refus("message vide")
        if len(message) > 60_000:
            raise Refus("message trop long (60 000 caractères au plus)")
        origine = (origine or "").strip()[:160] or acteur
        slug, dossier = self._projet(demande)
        nom = str(demande.get("nom") or "").strip()
        if nom and (not _NOM.match(nom) or nom.lower() in _NOMS_GENERIQUES or nom.startswith("session-")):
            raise Refus(f"nom d'agent invalide ou générique : {nom!r}")
        mode, avertissements = self._mode(dossier, demande, origine)
        duree = self._duree(demande, exiger_duree, avertissements)
        outils = [str(o) for o in (demande.get("outils") or []) if str(o).strip()][:50]
        identifiant = f"lc-{datetime.now(timezone.utc):%Y%m%d}-{secrets.token_hex(4)}"
        branche = self._branche(demande, origine, identifiant)
        reprise = str(demande.get("conversation") or "").strip()
        jetons = None
        plafonds = demande.get("plafonds") if isinstance(demande.get("plafonds"), dict) else {}
        if plafonds.get("jetons") not in (None, ""):
            try:
                jetons = int(plafonds["jetons"])
            except (TypeError, ValueError):
                raise Refus("plafonds.jetons : un nombre") from None

        with self._verrou:
            self._verifier_les_plafonds(origine, slug, branche)
            rec = None
            if reprise and not branche:
                rec = self.store.get(reprise)
                if rec is None:
                    avertissements.append(f"conversation {reprise} inconnue : une nouvelle est ouverte")
                elif rec.slug != slug:
                    # L'agent a changé de projet : sa conversation d'avant reste
                    # où elle est, une nouvelle s'ouvre dans le projet visé.
                    avertissements.append(f"conversation {reprise} dans {rec.slug}, pas dans {slug} : une nouvelle est ouverte")
                    rec = None
                elif rec.state == "archived":
                    rec = None
                    avertissements.append(f"conversation {reprise} rangée : une nouvelle est ouverte")
                elif rec.state == "running" and self.store.harness.tour_en_cours(rec.session_id):
                    raise Refus(f"déjà en cours : la conversation {reprise} travaille")
            lancement = Lancement(
                id=identifiant,
                origine=origine,
                acteur=acteur,
                projet=slug,
                nom=nom,
                mode=mode,
                avertissements=avertissements,
                plafonds={"duree_s": duree, **({"jetons": jetons} if jetons is not None else {})},
                cree_le=_maintenant(),
                message=message[:2000],
                outils=outils,
                branche=branche,
                reparation=demande.get("reparation") if isinstance(demande.get("reparation"), dict) else None,
            )
            copie: Path | None = None
            if branche:
                copie = self._ouvrir_la_copie(lancement, dossier)
            if rec is None:
                titre = str(demande.get("titre") or "").strip() or nom or f"Agent lancé ({origine})"
                rec = self.store.create(slug=slug, model=(str(demande.get("modele") or "").strip() or None), title=titre[:120])
            rec.lance_par = origine
            if nom:
                rec.nom_wikichat = nom
            if copie is not None:
                rec.cwd = str(copie)
            self.store.save(rec)
            lancement.conversation = rec.session_id
            self._ecrire(lancement)
            fil = threading.Thread(target=self._jouer, args=(lancement.id,), name=f"lancement-{lancement.id}", daemon=True)
            self._fils[lancement.id] = fil
        self._journaliser(lancement, "lance")
        fil.start()
        return lancement

    # ── la copie de travail ─────────────────────────────────────────────

    def _ouvrir_la_copie(self, lancement: Lancement, dossier: Path) -> Path:
        code, racine = _git(dossier, "rev-parse", "--show-toplevel")
        if code != 0 or Path(racine).resolve() != dossier.resolve():
            raise Refus(f"{lancement.projet} n'est pas un dépôt git : une branche est impossible")
        code, base = _git(dossier, "symbolic-ref", "--short", "HEAD")
        if code != 0 or not base:
            raise Refus(f"{lancement.projet} n'est sur aucune branche (HEAD détachée)")
        code, commit = _git(dossier, "rev-parse", "HEAD")
        if code != 0:
            raise Refus(f"{lancement.projet} n'a pas encore de commit")
        branche = lancement.branche
        if branche == base:
            raise Refus(f"la branche de l'agent ne peut pas être la branche de base ({base})")
        if _git(dossier, "rev-parse", "--verify", "--quiet", f"refs/heads/{branche}")[0] == 0:
            branche = f"{branche}-{lancement.id[-4:]}"
            lancement.branche = branche
        copie = dossier / DOSSIER_DES_COPIES / lancement.id
        # Ignorée du projet, même d'un projet d'avant le gabarit.
        if _git(dossier, "check-ignore", "-q", str((DOSSIER_DES_COPIES / "x").as_posix()))[0] != 0:
            code, commun = _git(dossier, "rev-parse", "--git-common-dir")
            if code == 0:
                exclusion = (dossier / commun).resolve() / "info" / "exclude"
                exclusion.parent.mkdir(parents=True, exist_ok=True)
                with exclusion.open("a", encoding="utf-8") as f:
                    f.write("\n# Copies de travail des agents lancés par l'Atelier\n/.atelier/reparations/\n")
        copie.parent.mkdir(parents=True, exist_ok=True)
        code, sortie = _git(dossier, "worktree", "add", "-b", branche, str(copie), commit, delai=120)
        if code != 0:
            raise Refus(f"copie de travail impossible : {sortie[-300:]}")
        for relatif in FICHIERS_DE_LIAISON:
            source = dossier / relatif
            if source.is_file():
                cible = copie / relatif
                cible.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(source, cible)
                except OSError as exc:
                    log.warning("%s non recopié dans la copie : %s", relatif, exc)
        lancement.copie = str(copie)
        lancement.base = base
        lancement.base_commit = commit
        return copie

    # ── jouer le tour ──────────────────────────────────────────────────

    def _jouer(self, identifiant: str) -> None:
        lancement = self.lire(identifiant)
        if lancement is None:
            return
        duree = int(lancement.plafonds.get("duree_s") or self.plafonds.duree_defaut_s)
        regles: dict[str, list[str]] = {}
        if lancement.outils:
            regles["allow"] = list(lancement.outils)
        env: dict[str, str] = {}
        if lancement.branche and lancement.copie:
            regles["deny"] = list(REGLES_REFUSEES_SUR_BRANCHE)
            env = environnement_de_la_copie(
                self.settings, Path(self.settings.projects_dir) / lancement.projet, lancement.branche
            )
        # Filet : le harnais coupe le tour à sa durée ; si rien ne l'a coupé
        # un peu après, on l'interrompt nous-mêmes.
        minuterie = threading.Timer(duree + 30, self._couper, args=(identifiant,))
        minuterie.daemon = True
        minuterie.start()
        etat, texte, erreur = FINI, "", ""
        try:
            resultat = self.store.send(
                lancement.conversation,
                lancement.message,
                peut_attendre=False,
                mode=lancement.mode,
                delai_s=duree,
                regles=regles or None,
                env_tour=env or None,
            )
            texte = resultat.text or ""
            fiche = self.store.get(lancement.conversation)
            cause = getattr(fiche, "cause", "") if fiche else ""
            etat_fiche = getattr(fiche, "state", "") if fiche else ""
            if etat_fiche == "interrupted":
                etat = ARRETE
            elif cause == "timeout_mural" or etat_fiche == "timeout":
                etat, erreur = DELAI, f"durée dépassée ({duree} s)"
            elif etat_fiche == "failed" or resultat.exit_code != 0:
                etat, erreur = ECHEC, cause or f"code {resultat.exit_code}"
        except Exception as exc:  # noqa: BLE001 — le lancement doit finir, quoi qu'il arrive
            log.exception("lancement %s", identifiant)
            etat, erreur = ECHEC, f"{type(exc).__name__}: {exc}"
        finally:
            minuterie.cancel()
        with self._verrou:
            lancement = self.lire(identifiant) or lancement
            if lancement.etat == ARRETE:
                etat = ARRETE
            lancement.etat = etat
            lancement.texte = texte[-4000:]
            lancement.erreur = erreur[:500]
            lancement.fini_le = _maintenant()
            self._ecrire(lancement)
        if lancement.branche and lancement.copie:
            try:
                self._conclure(lancement)
            except Exception as exc:  # noqa: BLE001
                log.exception("conclusion de %s", identifiant)
                lancement.conclusion = {"erreur": f"{type(exc).__name__}: {exc}"}
                self._ecrire(lancement)
        self._journaliser(lancement, lancement.etat)
        with self._verrou:
            self._fils.pop(identifiant, None)

    def _couper(self, identifiant: str) -> None:
        lancement = self.lire(identifiant)
        if lancement is None or lancement.etat != EN_COURS:
            return
        log.warning("lancement %s : durée dépassée, interruption", identifiant)
        try:
            self.store.interrupt(lancement.conversation)
        except (KeyError, OSError):
            pass

    def arreter(self, identifiant: str) -> Lancement:
        with self._verrou:
            lancement = self.lire(identifiant)
            if lancement is None:
                raise Refus(f"lancement inconnu : {identifiant}")
            if lancement.etat != EN_COURS:
                return lancement
            lancement.etat = ARRETE
            self._ecrire(lancement)
        try:
            self.store.interrupt(lancement.conversation)
        except (KeyError, OSError):
            pass
        return lancement

    def attendre(self, identifiant: str, delai_s: float = 10.0) -> Lancement | None:
        """Attend la fin du fil d'un lancement (tests, arrêt propre)."""
        fil = self._fils.get(identifiant)
        if fil is not None:
            fil.join(delai_s)
        return self.lire(identifiant)

    # ── conclure une copie de travail ──────────────────────────────────

    def _conclure(self, lancement: Lancement) -> None:
        """Vérifie que la base n'a pas bougé, et dépose la proposition dans « À valider »."""
        projet = Path(self.settings.projects_dir) / lancement.projet
        copie = Path(lancement.copie)
        code, base_apres = _git(projet, "rev-parse", f"refs/heads/{lancement.base}")
        base_intacte = code == 0 and base_apres == lancement.base_commit
        _, commits_bruts = _git(copie, "log", "--format=%h %s", f"{lancement.base_commit}..HEAD")
        commits = [c for c in commits_bruts.splitlines() if c.strip()][:50]
        _, ecart = _git(copie, "diff", "--stat", lancement.base_commit, "HEAD")
        _, extrait = _git(copie, "diff", lancement.base_commit, "HEAD")
        _, sale = _git(copie, "status", "--porcelain", "--untracked-files=no")
        conclusion: dict[str, Any] = {
            "base_intacte": base_intacte,
            "commits": commits,
            "non_commite": bool(sale.strip()),
        }
        lancement.conclusion = conclusion
        if not base_intacte:
            # Ne peut arriver qu'en contournant les gardes. On ne propose rien
            # à fusionner : la personne doit d'abord voir ce qui s'est passé.
            conclusion["alerte"] = (
                f"la branche {lancement.base} a bougé pendant le tour "
                f"({lancement.base_commit[:10]} → {base_apres[:10] if base_apres else '?'})"
            )
        reparation = lancement.reparation or {}
        titre_constat = str(reparation.get("resume") or reparation.get("titre") or "").strip()
        if not base_intacte:
            titre = f"Alerte : {lancement.base} a bougé pendant une réparation ({lancement.projet})"
        elif commits:
            titre = f"Réparation proposée : {titre_constat or lancement.branche}"
        else:
            titre = f"Diagnostic sans correction : {titre_constat or lancement.branche}"
        detail = {
            "lancement": lancement.id,
            "conversation": lancement.conversation,
            "branche": lancement.branche,
            "copie": lancement.copie,
            "avant": {
                "constat": reparation.get("resume") or "",
                "preuve": reparation.get("preuve") or "",
                "controle": reparation.get("controle") or "",
                "base": lancement.base,
                "commit": lancement.base_commit,
            },
            "apres": {
                "etat_du_tour": lancement.etat,
                "commits": commits,
                "ecart": ecart[-3000:],
                "extrait": extrait[:6000],
                "non_commite": conclusion["non_commite"],
                "conclusion_de_l_agent": lancement.texte[-1500:],
                "base_apres": base_apres,
            },
            "verification": reparation.get("verification") or "",
            "fusion": f"git merge --no-ff {lancement.branche} dans {lancement.base}, sans envoi",
        }
        if self.journal is not None and getattr(self.journal, "filtre", None) is not None:
            try:
                detail = self.journal.filtre.nettoyer(detail)
            except Exception:  # noqa: BLE001 — sans filtre, le détail reste tel quel
                pass
        if self.file is None:
            self._ecrire(lancement)
            return
        action = None
        if base_intacte and commits:
            action = {"commande": NOM_FUSIONNER, "arguments": {"lancement": lancement.id}}
        source = "gardien" if lancement.origine.startswith(PREFIXE_GARDIEN) else "agent"
        p = self.file.deposer(
            source,
            titre,
            lancement.texte[-1500:] or titre_constat,
            acteur=f"conversation:{lancement.conversation}",
            projet=lancement.projet,
            detail=detail,
            action=action,
            empreinte=str(reparation.get("empreinte") or "") + f"|{lancement.id}",
        )
        lancement.proposition = p.id
        self._ecrire(lancement)

    def fusionner(self, identifiant: str) -> dict[str, Any]:
        """Fusionne la branche d'un lancement dans sa base, sans rien pousser.

        Appelée par `atelier_reparation_fusionner`, réservée à la personne :
        c'est son « Oui » dans « À valider ».
        """
        lancement = self.lire(identifiant)
        if lancement is None or not lancement.branche:
            raise Refus(f"aucune branche à fusionner pour {identifiant}")
        if lancement.etat == EN_COURS:
            raise Refus("l'agent travaille encore sur cette branche")
        projet = Path(self.settings.projects_dir) / lancement.projet
        code, courante = _git(projet, "symbolic-ref", "--short", "HEAD")
        if code != 0 or courante != lancement.base:
            raise Refus(f"le projet n'est plus sur {lancement.base} (il est sur {courante or '?'}) : rien n'est fusionné")
        code, sale = _git(projet, "status", "--porcelain", "--untracked-files=no")
        if code != 0 or sale.strip():
            raise Refus("le projet a des modifications non commitées : rangez-les d'abord, rien n'est fusionné")
        _, avant = _git(projet, "rev-parse", "HEAD")
        code, sortie = _git(
            projet,
            "merge",
            "--no-ff",
            "--no-edit",
            "-m",
            f"Fusionner {lancement.branche} (proposition de {lancement.origine})",
            lancement.branche,
            delai=120,
        )
        if code != 0:
            _git(projet, "merge", "--abort")
            raise Refus(f"fusion impossible, rien n'a changé : {sortie[-300:]}")
        _, apres = _git(projet, "rev-parse", "HEAD")
        if lancement.copie:
            _git(projet, "worktree", "remove", "--force", lancement.copie, delai=60)
        lancement.conclusion = {**(lancement.conclusion or {}), "fusionne": apres}
        self._ecrire(lancement)
        return {"lancement": identifiant, "branche": lancement.branche, "base": lancement.base, "avant": avant, "apres": apres}

    # ── journal ────────────────────────────────────────────────────────

    def _journaliser(self, lancement: Lancement, resultat: str) -> None:
        if self.journal is None:
            return
        try:
            from mcp_gateway.atelier.commandes.journal import Evenement

            self.journal.ecrire(
                Evenement(
                    source="automate",
                    acteur=lancement.acteur,
                    objet={"type": "agent", "id": lancement.conversation or lancement.id},
                    action={
                        "commande": "atelier_lancer_agent",
                        "classe": ENGAGEANTE,
                        "origine": lancement.origine,
                        "avant": None,
                        "apres": {
                            "lancement": lancement.id,
                            "etat": lancement.etat,
                            "projet": lancement.projet,
                            "mode": lancement.mode,
                            "duree_s": lancement.plafonds.get("duree_s"),
                            "branche": lancement.branche or None,
                            "proposition": lancement.proposition or None,
                        },
                    },
                    resultat=resultat,
                )
            )
        except (OSError, ValueError) as exc:
            log.warning("journal du lancement %s non écrit : %s", lancement.id, exc)


# ── Les commandes ────────────────────────────────────────────────────────────

NOM_LANCER = "atelier_lancer_agent"
NOM_LISTER = "atelier_lancements"
NOM_FUSIONNER = "atelier_reparation_fusionner"


def _origine_du_contexte(ctx: Contexte, arguments: dict[str, Any]) -> str:
    if ctx.origine == ORIGINE_AUTOMATE:
        return str(arguments.get("origine") or ctx.acteur).strip()[:160]
    return ctx.acteur


def inscrire_les_commandes(catalogue: Any, lanceur: Lanceur) -> None:
    schema_lancer = {
        "type": "object",
        "properties": {
            "projet": {"type": "string", "description": "Le projet où l'agent travaille."},
            "message": {"type": "string", "description": "Sa mission, en entier."},
            "nom": {"type": "string", "description": "Son nom auprès de wikichat (facultatif)."},
            "duree_min": {"type": "integer", "description": "Durée maximale en minutes (15 par défaut, 30 au plus)."},
            "mode": {"type": "string", "enum": ["plan", "default", "acceptEdits"]},
            "modele": {"type": "string"},
            "branche": {"type": "string", "description": "Facultatif : `agent/<sujet>`, pour qu'il travaille dans une copie et propose sa branche."},
        },
        "required": ["projet", "message"],
    }

    def _demande(arguments: dict[str, Any]) -> dict[str, Any]:
        demande = dict(arguments)
        if demande.get("duree_min") not in (None, "") and "plafonds" not in demande:
            try:
                demande["plafonds"] = {"duree_s": int(demande["duree_min"]) * 60}
            except (TypeError, ValueError):
                raise Refus("duree_min : un nombre de minutes") from None
        return demande

    def apercu(ctx: Contexte, arguments: dict[str, Any]) -> dict[str, Any]:
        # Un aperçu ne lève pas : un projet inconnu se lit dans l'aperçu, et
        # le lancement confirmé le refusera de la même façon.
        try:
            return lanceur.apercu(_demande(arguments), _origine_du_contexte(ctx, arguments))
        except Refus as exc:
            return {"refus": str(exc)}

    def lancer(ctx: Contexte, arguments: dict[str, Any]) -> Effet:
        automate = ctx.origine == ORIGINE_AUTOMATE
        demande = _demande(arguments)
        if not automate:
            # Un modèle ou la personne : ni reprise d'une conversation d'autrui,
            # ni règles d'outils, ni réparation — ce sont des champs d'automate.
            for cle in ("conversation", "outils", "reparation", "mode_de_la_definition", "origine"):
                demande.pop(cle, None)
        l = lanceur.lancer(
            demande,
            acteur=ctx.acteur,
            origine=_origine_du_contexte(ctx, arguments),
            exiger_duree=automate,
        )
        return Effet(
            charge={"lancement": l.en_dict()},
            objet_id=l.conversation,
            titre="Agent lancé",
            resume=f"{l.nom or 'un agent'} dans {l.projet}, mode {l.mode}, {l.plafonds.get('duree_s')} s au plus"
            + (f", sur la branche {l.branche}" if l.branche else ""),
            voir=f"/?session={l.conversation}",
            preuve={"lancement": l.id, "conversation": l.conversation},
            apres={"lancement": l.id, "etat": l.etat},
        )

    catalogue.ajouter(
        Commande(
            nom=NOM_LANCER,
            description=(
                "Lance un agent code dans un projet : une conversation visible dans l'Atelier, "
                "avec le profil du projet, son mode et des plafonds (durée, nombre). Pour "
                "déléguer un travail à un agent plutôt que de le faire soi-même."
            ),
            objet="agent",
            classe=ENGAGEANTE,
            executer=lancer,
            apercu=apercu,
            schema=schema_lancer,
            regles=[
                "profil code du projet visé, jamais celui de l'Assistant",
                "mode du projet ; bypassPermissions seulement par une définition de routine ou de trigger et si le projet l'accorde",
                "plafonds tenus par l'Atelier : simultanés, par jour, par origine, durée",
                "sur une branche : copie de travail, jamais main, jamais d'envoi",
            ],
        )
    )

    def lister(ctx: Contexte, arguments: dict[str, Any]) -> Effet:
        del ctx
        liste = lanceur.lister(
            etat=str(arguments.get("etat") or ""),
            origine=str(arguments.get("origine") or ""),
            projet=str(arguments.get("projet") or ""),
            limite=int(arguments.get("limite") or 50),
        )
        return Effet(charge={"lancements": [l.en_dict() for l in liste], "nombre": len(liste)})

    catalogue.ajouter(
        Commande(
            nom=NOM_LISTER,
            description="Les agents lancés (par wikichat, les gardiens, l'Assistant) : état, projet, origine.",
            objet="agent",
            classe=LECTURE,
            executer=lister,
            schema={
                "type": "object",
                "properties": {
                    "etat": {"type": "string"},
                    "origine": {"type": "string"},
                    "projet": {"type": "string"},
                    "limite": {"type": "integer"},
                },
            },
        )
    )

    def fusionner(ctx: Contexte, arguments: dict[str, Any]) -> Effet:
        del ctx
        identifiant = str(arguments.get("lancement") or "").strip()
        resultat = lanceur.fusionner(identifiant)
        return Effet(
            charge=resultat,
            objet_id=identifiant,
            titre="Branche fusionnée",
            resume=f"{resultat['branche']} dans {resultat['base']}, sans envoi",
            preuve={"commit": resultat["apres"]},
            avant={"commit": resultat["avant"]},
            apres={"commit": resultat["apres"]},
        )

    catalogue.ajouter(
        Commande(
            nom=NOM_FUSIONNER,
            description="Fusionne la branche proposée par un agent lancé dans sa base, sans rien pousser.",
            objet="projet",
            classe=RESERVEE,
            executer=fusionner,
            schema={"type": "object", "properties": {"lancement": {"type": "string"}}, "required": ["lancement"]},
            regles=["réservée à la personne (« À valider »)", "jamais d'envoi", "refusée si le projet a changé de branche ou n'est pas propre"],
            exposee_mcp=False,
        )
    )


# ── Les routes ───────────────────────────────────────────────────────────────


def construire_le_routeur(app: Any) -> Any:
    from mcp_gateway.atelier.auth import ENTETE_INTERFACE
    from mcp_gateway.atelier.commandes.catalogue import APERCU, ERREUR, FAIT, REFUSE
    from mcp_gateway.atelier.vscode_bridge import COOKIE_NAME
    from mcp_gateway.auth import bearer_from_header

    router = APIRouter(prefix="/v1/lancements")
    statuts = {FAIT: 202, APERCU: 200, REFUSE: 403, ERREUR: 422}

    def _cle_du_lanceur(presentee: str | None) -> bool:
        attendue = lire_la_cle(app.state.settings)
        return bool(presentee and attendue and secrets.compare_digest(presentee.strip(), attendue))

    def _lecteur(request: Request, cle: str | None, authorization: str | None) -> str:
        """Lire : la clé du lanceur, ou le propriétaire (clé ou session de l'interface)."""
        if _cle_du_lanceur(cle):
            return "lanceur"
        return app.state.auth.check_api(
            bearer_from_header(authorization),
            request.cookies.get(COOKIE_NAME),
            request.headers.get(ENTETE_INTERFACE) == "1",
        )

    @router.post("")
    async def lancer(
        request: Request,
        cle: Annotated[str | None, Header(alias=ENTETE_CLE)] = None,
    ) -> JSONResponse:
        # La route interne : la clé du lanceur, et rien d'autre. La clé du
        # propriétaire ne l'ouvre pas — l'Assistant passe par la commande,
        # donc par l'aperçu.
        if not _cle_du_lanceur(cle):
            raise HTTPException(401, "clé du lanceur requise")
        try:
            corps = await request.json()
        except ValueError:
            raise HTTPException(422, "corps JSON attendu") from None
        if not isinstance(corps, dict):
            raise HTTPException(422, "corps JSON attendu")
        origine = str(corps.get("origine") or "").strip()[:160]
        if not origine:
            raise HTTPException(422, "origine requise (qui demande ce lancement)")
        ctx = Contexte(acteur=f"automate:{origine}", origine=ORIGINE_AUTOMATE, confirme=True)
        reponse = await app.state.commandes.executer(NOM_LANCER, corps, ctx)
        corps_reponse = {"statut": reponse.statut, "action": reponse.action or None}
        if isinstance(reponse.charge, dict):
            corps_reponse.update({k: v for k, v in reponse.charge.items() if k != "carte"})
        return JSONResponse(corps_reponse, status_code=statuts.get(reponse.statut, 200))

    @router.get("")
    def lister(
        request: Request,
        etat: str = "",
        origine: str = "",
        projet: str = "",
        limite: int = 100,
        cle: Annotated[str | None, Header(alias=ENTETE_CLE)] = None,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        _lecteur(request, cle, authorization)
        liste = app.state.lancements.lister(etat=etat, origine=origine, projet=projet, limite=limite)
        return {"lancements": [l.en_dict() for l in liste], "nombre": len(liste)}

    @router.get("/{identifiant}")
    def lire(
        request: Request,
        identifiant: str,
        cle: Annotated[str | None, Header(alias=ENTETE_CLE)] = None,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        _lecteur(request, cle, authorization)
        lancement = app.state.lancements.lire(identifiant)
        if lancement is None:
            raise HTTPException(404, f"lancement inconnu : {identifiant}")
        return {"lancement": lancement.en_dict()}

    @router.post("/{identifiant}/arreter")
    def arreter(
        request: Request,
        identifiant: str,
        cle: Annotated[str | None, Header(alias=ENTETE_CLE)] = None,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        _lecteur(request, cle, authorization)
        try:
            lancement = app.state.lancements.arreter(identifiant)
        except Refus as exc:
            raise HTTPException(404, str(exc)) from None
        return {"lancement": lancement.en_dict()}

    return router


# ── L'enregistrement ─────────────────────────────────────────────────────────


def enregistrer_les_lancements(app: Any) -> Lanceur:
    """La ligne que `api.py` appelle, après le catalogue.

    Monte le lanceur, ses commandes et ses routes ; pose la clé du lanceur ;
    régénère le contexte des projets à la structure type (lot B) : VS Code et
    le terminal le lisent sans attendre un tour de l'Atelier.
    """
    settings = app.state.settings
    lanceur = Lanceur(
        settings,
        app.state.store,
        projects=getattr(app.state, "projects", None),
        file=getattr(app.state, "a_valider", None),
        journal=getattr(app.state, "journal_unique", None),
    )
    app.state.lancements = lanceur
    try:
        assurer_la_cle(settings)
    except OSError as exc:
        log.warning("clé du lanceur non posée : %s", exc)
    try:
        lanceur.reconcilier()
    except OSError as exc:
        log.warning("lancements non réconciliés : %s", exc)
    inscrire_les_commandes(app.state.commandes, lanceur)
    app.include_router(construire_le_routeur(app))
    _brancher_le_contexte(app)
    return lanceur


def _brancher_le_contexte(app: Any) -> None:
    from mcp_gateway.atelier.project_context import ecrire_contexte, ecrire_tous_les_contextes

    settings = app.state.settings

    def apres_commande(nom: str, charge: dict[str, Any]) -> None:
        # Un projet créé importe le contexte dès sa naissance : sans ce rappel,
        # VS Code l'ouvrirait avant qu'un tour de l'Atelier l'ait écrit.
        if nom not in ("atelier_projet_creer", "atelier_projet_modifier", "atelier_projet_deployer_declarer"):
            return
        slug = ""
        for cle in ("slug", "projet"):
            valeur = charge.get(cle) if isinstance(charge, dict) else None
            if isinstance(valeur, str) and valeur:
                slug = valeur
                break
            if isinstance(valeur, dict) and isinstance(valeur.get("slug"), str):
                slug = valeur["slug"]
                break
        if slug:
            ecrire_contexte(Path(settings.projects_dir) / slug, slug, settings)

    app.state.commandes.apres_commande.append(apres_commande)
    if not getattr(app.state, "use_fake", False):
        try:
            ecrire_tous_les_contextes(settings)
        except OSError as exc:
            log.warning("contextes des projets non régénérés : %s", exc)


__all__ = [
    "ENTETE_CLE",
    "Lancement",
    "Lanceur",
    "NOM_FUSIONNER",
    "NOM_LANCER",
    "Plafonds",
    "assurer_la_cle",
    "chemin_de_la_cle",
    "enregistrer_les_lancements",
    "environnement_de_la_copie",
    "lire_la_cle",
]
