"""Les décisions qu'un tour attend, et la trace qui leur survit.

Quand une conversation tourne en `manual`, le CLI ne refuse plus : il demande.
Il envoie une `control_request` sur sa sortie, puis **attend** — éprouvé sur ce
pod, trente-deux minutes sans que rien ne le presse, mémoire plate. C'est donc
à nous de tenir la question, de la montrer, et de rendre la réponse.

Deux couches, parce qu'elles ne font pas le même travail.

L'**attente vive** est le processus garé, l'entrée ouverte : répondre reprend
le tour exactement là où il s'est arrêté, sans rien rejouer. C'est le cas
courant et le meilleur. Elle vit dans `_vives`, en mémoire, et meurt avec le
service.

La **trace** est le fichier écrit à l'instant où la question est posée. Elle ne
sert à rien tant que tout va bien — et à tout le jour où le service redémarre :
la question reste affichable, donc répondable. C'est elle qui rend tenable la
promesse qu'une décision en attente peut le rester.

Ce que ce module ne fait pas encore : rejouer un tour dont le processus a
disparu. La trace le permettra ; le rejeu est un autre palier, avec sa propre
prudence — un tour rejoué refait ce que l'agent avait déjà fait avant la
question.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Demande:
    """Ce que le CLI demande, tel qu'il le demande.

    Tous ces champs viennent de la `control_request` ; aucun n'est déduit. Le
    CLI fournit déjà la raison du blocage et des suggestions toutes faites —
    « passer la conversation en acceptEdits », « ajouter ce répertoire » — qui
    sont exactement les boutons dont l'écran a besoin.
    """

    request_id: str
    session_id: str
    outil: str
    arguments: dict[str, Any] = field(default_factory=dict)
    affichage: str = ""
    description: str = ""
    raison: str = ""
    raison_type: str = ""
    suggestions: list[dict[str, Any]] = field(default_factory=list)
    tool_use_id: str = ""
    posee_le: str = field(default_factory=_maintenant)
    vive: bool = True

    @classmethod
    def depuis_control_request(
        cls, request_id: str, session_id: str, requete: dict[str, Any]
    ) -> Demande:
        return cls(
            request_id=request_id,
            session_id=session_id,
            outil=str(requete.get("tool_name") or "?"),
            arguments=requete.get("input") if isinstance(requete.get("input"), dict) else {},
            affichage=str(requete.get("display_name") or requete.get("tool_name") or ""),
            description=str(requete.get("description") or ""),
            raison=str(requete.get("decision_reason") or ""),
            raison_type=str(requete.get("decision_reason_type") or ""),
            suggestions=[s for s in (requete.get("permission_suggestions") or []) if isinstance(s, dict)],
            tool_use_id=str(requete.get("tool_use_id") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def reponse_autorisee(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Laisser passer, éventuellement avec des arguments corrigés."""
    return {"behavior": "allow", "updatedInput": arguments or {}}


def reponse_refusee(motif: str = "") -> dict[str, Any]:
    """Refuser, et dire pourquoi.

    Le motif n'est pas décoratif : il revient au modèle. Éprouvé — l'agent le
    lit, en tire une théorie et essaie une autre route. Un refus est donc un
    aller-retour, pas un frein ; c'est `interrupt` qui arrête un tour.
    """
    return {"behavior": "deny", "message": motif or "Refusé par l'utilisateur."}


class RegistreDesDecisions:
    """Tient les questions posées, et rend les réponses à qui les attend.

    Deux fils s'y croisent : celui du tour, qui pose puis se bloque, et celui
    de la requête HTTP, qui répond. Le rendez-vous se fait sur un `Event` par
    demande — pas de sondage, pas de délai arbitraire.
    """

    def __init__(self, dossier: Path) -> None:
        self._dossier = dossier
        self._verrou = threading.Lock()
        self._vives: dict[str, Demande] = {}
        self._reponses: dict[str, dict[str, Any]] = {}
        self._signaux: dict[str, threading.Event] = {}

    # -- la trace ---------------------------------------------------------

    def _chemin(self, request_id: str) -> Path:
        return self._dossier / f"{request_id}.json"

    def _ecrire(self, demande: Demande) -> None:
        try:
            self._dossier.mkdir(parents=True, exist_ok=True)
            self._chemin(demande.request_id).write_text(
                json.dumps(demande.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            # Une trace qu'on n'arrive pas à écrire ne doit pas faire tomber
            # le tour : l'attente vive, elle, fonctionne toujours.
            pass

    def _effacer(self, request_id: str) -> None:
        try:
            self._chemin(request_id).unlink(missing_ok=True)
        except OSError:
            pass

    def orphelines(self) -> list[Demande]:
        """Les questions écrites par un service qui n'est plus là.

        Au redémarrage, leur processus a disparu : plus personne n'attend la
        réponse. Elles restent pourtant affichables — c'est tout l'intérêt de
        la trace — et se distinguent des vives par `vive: false`.
        """
        restes: list[Demande] = []
        if not self._dossier.exists():
            return restes
        for fichier in sorted(self._dossier.glob("*.json")):
            try:
                brut = json.loads(fichier.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(brut, dict):
                continue
            connus = {c for c in Demande.__dataclass_fields__}
            demande = Demande(**{k: v for k, v in brut.items() if k in connus})
            with self._verrou:
                demande.vive = demande.request_id in self._vives
            restes.append(demande)
        return restes

    # -- le rendez-vous ---------------------------------------------------

    def poser(self, demande: Demande) -> threading.Event:
        """Enregistre la question et rend le signal qui dira qu'on a répondu."""
        signal = threading.Event()
        with self._verrou:
            self._vives[demande.request_id] = demande
            self._signaux[demande.request_id] = signal
        self._ecrire(demande)
        return signal

    def repondre(self, request_id: str, reponse: dict[str, Any]) -> bool:
        """Dépose la réponse et réveille le tour. Faux si personne n'attendait."""
        with self._verrou:
            signal = self._signaux.get(request_id)
            if signal is None:
                return False
            self._reponses[request_id] = reponse
        signal.set()
        return True

    def reponse(self, request_id: str) -> dict[str, Any] | None:
        with self._verrou:
            return self._reponses.get(request_id)

    def clore(self, request_id: str) -> None:
        """La question est réglée : plus d'attente vive, plus de trace."""
        with self._verrou:
            self._vives.pop(request_id, None)
            self._reponses.pop(request_id, None)
            self._signaux.pop(request_id, None)
        self._effacer(request_id)

    def en_attente(self, session_id: str = "") -> list[Demande]:
        """Les questions vives, filtrées par conversation si on le demande."""
        with self._verrou:
            demandes = list(self._vives.values())
        if session_id:
            demandes = [d for d in demandes if d.session_id == session_id]
        return sorted(demandes, key=lambda d: d.posee_le)

    def abandonner(self, session_id: str) -> int:
        """Le tour s'arrête sans réponse : on ne laisse pas la question traîner.

        Sert quand l'utilisateur interrompt, ou quand le processus meurt : sans
        cela, une question resterait affichée alors que plus rien ne l'attend.
        """
        with self._verrou:
            perdues = [rid for rid, d in self._vives.items() if d.session_id == session_id]
        for rid in perdues:
            self.clore(rid)
        return len(perdues)
