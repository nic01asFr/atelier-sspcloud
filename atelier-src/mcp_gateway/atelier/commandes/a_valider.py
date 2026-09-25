"""La file « À valider » (décision S3) : une seule file pour tout ce qui attend la personne.

Les propositions des gardiens, des agents et des créations, la mémoire
proposée, les décisions en attente de l'Assistant arrivent ici par **une seule
fonction**, `FileAValider.deposer`. La personne les accepte ou les refuse ;
l'Assistant peut refuser seul, jamais accepter (A-5) : c'est le catalogue qui
l'impose, `atelier_a_valider_accepter` étant une commande réservée.

**Stockage.** Un fichier par proposition, `~/work/.atelier-etat/a-valider/<id>.json`,
écrit de façon atomique. L'exécuteur des gardiens, un autre processus, dépose
sans passer par le service : il importe ce module et écrit dans le dossier.

**Les deux files qui existaient déjà.**

- `decisions.py` tient les autorisations et questions d'un tour vivant du CLI
  (`control_request`) : elles attendent une réponse dans la seconde, pendant
  que le processus est garé. Ce n'est pas une proposition, et les faire
  transiter ici casserait la reprise du tour. Elles restent où elles sont.
- Le pilote de wikichat tient `.wikichat/proposed-actions.json` dans le dossier
  de chaque agent, avec son applicateur. **On s'y branche, on ne migre pas** :
  wikichat reste la maison de la coordination (S5), et ses agents écrivent ce
  fichier selon un contrat que le pilote leur injecte. La file les lit par
  l'API du pilote (`/pilote/api/data`, `queue` de chaque agent) et transmet
  la décision à `/pilote/api/agent/<id>/decide`. Rien n'est recopié : leurs
  identifiants sont `pilote:<agent>:<action>`.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from mcp_gateway.atelier.commandes.journal import Evenement, Journal, empreinte as calculer_empreinte, maintenant

SOURCES = ("gardien", "agent", "creation", "memoire", "assistant", "pilote")
EN_ATTENTE = "en_attente"
ACCEPTEE = "acceptee"
REFUSEE = "refusee"
STATUTS = (EN_ATTENTE, ACCEPTEE, REFUSEE)
PREFIXE_PILOTE = "pilote:"


class ErreurAValider(ValueError):
    """Une proposition mal formée, inconnue, ou déjà tranchée."""


@dataclass
class Proposition:
    id: str
    source: str
    titre: str
    resume: str = ""
    acteur: str = ""
    projet: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    # Ce qu'accepter exécute : une commande du catalogue et ses arguments.
    # Sans action, accepter ne fait que trancher.
    action: dict[str, Any] | None = None
    empreinte: str = ""
    creee_le: str = ""
    modifiee_le: str = ""
    occurrences: int = 1
    statut: str = EN_ATTENTE
    decision: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _proposition(brut: dict[str, Any]) -> Proposition:
    champs = set(Proposition.__dataclass_fields__)
    return Proposition(**{k: v for k, v in brut.items() if k in champs})


class FileAValider:
    def __init__(self, dossier: Path, *, journal: Journal | None = None) -> None:
        self.dossier = Path(dossier)
        self.journal = journal
        self._verrou = threading.Lock()

    # ── Stockage ────────────────────────────────────────────────────────

    def _chemin(self, identifiant: str) -> Path:
        if not identifiant or "/" in identifiant or "\\" in identifiant or identifiant.startswith("."):
            raise ErreurAValider(f"identifiant invalide : {identifiant!r}")
        return self.dossier / f"{identifiant}.json"

    def _ecrire(self, p: Proposition) -> None:
        self.dossier.mkdir(parents=True, exist_ok=True)
        chemin = self._chemin(p.id)
        temporaire = chemin.with_name(chemin.name + f".{secrets.token_hex(4)}.tmp")
        temporaire.write_text(json.dumps(p.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporaire, chemin)

    def lire(self, identifiant: str) -> Proposition | None:
        try:
            brut = json.loads(self._chemin(identifiant).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return _proposition(brut) if isinstance(brut, dict) else None

    def toutes(self) -> list[Proposition]:
        if not self.dossier.is_dir():
            return []
        sortie: list[Proposition] = []
        for fichier in self.dossier.glob("*.json"):
            try:
                brut = json.loads(fichier.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(brut, dict):
                sortie.append(_proposition(brut))
        return sortie

    def _journaliser(self, p: Proposition, acteur: str, action: str, resultat: str, avant: Any = None) -> None:
        if self.journal is None:
            return
        try:
            self.journal.ecrire(
                Evenement(
                    source="validation",
                    acteur=acteur or p.acteur or p.source,
                    objet={"type": "validation", "id": p.id},
                    action={"geste": action, "avant": avant, "apres": {"statut": p.statut}, "source": p.source},
                    resultat=resultat,
                    empreinte=p.empreinte,
                )
            )
        except OSError:
            pass

    # ── La seule porte d'entrée ─────────────────────────────────────────

    def deposer(
        self,
        source: str,
        titre: str,
        resume: str = "",
        *,
        acteur: str = "",
        projet: str = "",
        detail: dict[str, Any] | None = None,
        action: dict[str, Any] | None = None,
        empreinte: str = "",
    ) -> Proposition:
        """Dépose une proposition. La même empreinte, encore en attente, n'est pas dupliquée.

        Un gardien revoit le même constat toutes les cinq minutes : la file ne
        doit en garder qu'une entrée, qui compte ses occurrences.
        """
        if source not in SOURCES or source == "pilote":
            raise ErreurAValider(f"source inconnue : {source} ({', '.join(s for s in SOURCES if s != 'pilote')})")
        if not str(titre or "").strip():
            raise ErreurAValider("titre requis")
        if action is not None:
            if not isinstance(action, dict) or not str(action.get("commande") or "").startswith("atelier_"):
                raise ErreurAValider("action : {commande: atelier_…, arguments: {…}}")
            if not isinstance(action.get("arguments", {}), dict):
                raise ErreurAValider("action.arguments doit être un objet")
        cle = empreinte or calculer_empreinte(source, projet, titre, action)
        with self._verrou:
            for p in self.toutes():
                if p.statut == EN_ATTENTE and p.source == source and p.empreinte == cle:
                    p.occurrences += 1
                    p.modifiee_le = maintenant()
                    self._ecrire(p)
                    return p
            quand = maintenant()
            p = Proposition(
                id=f"av-{quand[:10].replace('-', '')}-{secrets.token_hex(4)}",
                source=source,
                titre=str(titre).strip()[:200],
                resume=str(resume or "").strip()[:2000],
                acteur=acteur,
                projet=projet,
                detail=dict(detail or {}),
                action=dict(action) if action else None,
                empreinte=cle,
                creee_le=quand,
                modifiee_le=quand,
            )
            self._ecrire(p)
        self._journaliser(p, acteur, "deposer", "fait")
        return p

    # ── Lecture et décision ─────────────────────────────────────────────

    def lister(self, *, statut: str = EN_ATTENTE, projet: str = "", source: str = "") -> list[Proposition]:
        sortie = [
            p
            for p in self.toutes()
            if (not statut or p.statut == statut)
            and (not projet or p.projet == projet)
            and (not source or p.source == source)
        ]
        return sorted(sortie, key=lambda p: p.creee_le, reverse=True)

    def trancher(
        self, identifiant: str, statut: str, *, par: str, motif: str = "", resultat: Any = None
    ) -> Proposition:
        if statut not in (ACCEPTEE, REFUSEE):
            raise ErreurAValider("décision : acceptee ou refusee")
        with self._verrou:
            p = self.lire(identifiant)
            if p is None:
                raise ErreurAValider(f"proposition inconnue : {identifiant}")
            if p.statut != EN_ATTENTE:
                raise ErreurAValider(f"déjà tranchée : {p.statut}")
            p.statut = statut
            p.modifiee_le = maintenant()
            p.decision = {"par": par, "quand": p.modifiee_le, "motif": motif, "resultat": resultat}
            self._ecrire(p)
        self._journaliser(p, par, "accepter" if statut == ACCEPTEE else "refuser", "fait", {"statut": EN_ATTENTE})
        return p

    def rouvrir(self, identifiant: str, *, par: str) -> Proposition:
        """L'inverse d'un refus : la proposition attend de nouveau."""
        with self._verrou:
            p = self.lire(identifiant)
            if p is None:
                raise ErreurAValider(f"proposition inconnue : {identifiant}")
            if p.statut != REFUSEE:
                raise ErreurAValider("seule une proposition refusée se rouvre")
            avant = {"statut": p.statut}
            p.statut = EN_ATTENTE
            p.decision = None
            p.modifiee_le = maintenant()
            self._ecrire(p)
        self._journaliser(p, par, "rouvrir", "fait", avant)
        return p


# ── Le pilote de wikichat, lu sans être recopié ────────────────────────


def propositions_du_pilote(donnees: Any) -> list[dict[str, Any]]:
    """Les actions en attente du pilote, au format de la file.

    `donnees` est la réponse de `/pilote/api/data` : `agents[].queue`, déjà
    filtrée par le pilote sur `status == "pending"`.
    """
    agents = donnees.get("agents") if isinstance(donnees, dict) else None
    sortie: list[dict[str, Any]] = []
    for agent in agents if isinstance(agents, list) else []:
        if not isinstance(agent, dict):
            continue
        ident = str(agent.get("id") or "")
        for action in agent.get("queue") or []:
            if not isinstance(action, dict) or not ident:
                continue
            sortie.append(
                Proposition(
                    id=f"{PREFIXE_PILOTE}{ident}:{action.get('id')}",
                    source="pilote",
                    titre=str(action.get("title") or "Action proposée"),
                    resume=str(action.get("sub") or ""),
                    acteur=f"agent:{agent.get('name') or ident}",
                    detail={
                        "agent": ident,
                        "genre": action.get("kind"),
                        "montant": action.get("amount"),
                        "a_completer": action.get("needs") or [],
                    },
                ).to_dict()
            )
    return sortie


def decomposer_id_pilote(identifiant: str) -> tuple[str, str]:
    """`pilote:<agent>:<action>` -> (agent, action)."""
    reste = identifiant[len(PREFIXE_PILOTE):]
    agent, sep, action = reste.partition(":")
    if not identifiant.startswith(PREFIXE_PILOTE) or not sep or not agent or not action:
        raise ErreurAValider(f"identifiant du pilote invalide : {identifiant}")
    return agent, action


def dossier_a_valider(work_dir: Path) -> Path:
    return Path(work_dir) / ".atelier-etat" / "a-valider"


__all__ = [
    "ACCEPTEE",
    "EN_ATTENTE",
    "ErreurAValider",
    "FileAValider",
    "PREFIXE_PILOTE",
    "Proposition",
    "REFUSEE",
    "SOURCES",
    "decomposer_id_pilote",
    "dossier_a_valider",
    "propositions_du_pilote",
]
