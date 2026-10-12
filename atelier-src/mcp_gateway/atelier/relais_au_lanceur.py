"""Un agent qui en lance un autre reçoit ses demandes, sans aller les chercher.

Avant ce module, l'agent lancé « supervisé » posait sa demande d'autorisation
et s'endormait ; son lanceur ne l'apprenait que s'il avait l'idée d'aller voir
(`atelier_suivre`, `atelier_lancements`). Si le lanceur avait fini son tour,
personne ne répondait : l'agent lancé attendait la personne pour une décision
qui revenait à son lanceur.

Ici, la demande devient un message adressé au lanceur, par la même porte que
n'importe quel message à une conversation :

- le lanceur est **inactif** : le message le **relance** (nouveau tour sur la
  même conversation) ; il répond par `atelier_decider` ;
- le lanceur **travaille** : s'il suit l'agent lancé, il voit la demande par
  `atelier_suivre` et y répond de lui-même. Sinon, après un court délai, le
  message est mis en file et il le lira à la fin de son tour ;
- l'agent lancé ne bloque personne dans l'intervalle : il dort et reprend
  (voir `attendre-sans-refuser.md`).

Ce qui reste à la personne ne passe pas par ici : une demande hors du
périmètre du lanceur (`perimetre_du_lanceur`), et toute question posée à la
personne (`AskUserQuestion`), attendent la personne, comme avant.

L'agent lancé peut aussi **interroger son lanceur** sans bloquer
(`demander`, commande `atelier_demander_au_lanceur`) : la question part comme
message, le lanceur répond par `atelier_envoyer`, ce qui relance l'agent lancé.

Garde-fous : seulement les lancements supervisés dont le lanceur est une
conversation ; une demande n'est relayée qu'une fois (la liste est écrite sur
la fiche du lancement, elle survit à un redémarrage) ; au plus
`RELAIS_MAX` messages par lancement.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("atelier.relais_au_lanceur")

PREFIXE_CONVERSATION = "conversation:"
RELAIS_MAX = 30
# Un lanceur qui travaille et suit l'agent lancé répond de lui-même : on lui
# laisse ce temps avant de mettre un message en file.
DELAI_LANCEUR_OCCUPE_S = 20.0


def lanceur_de(lancement: Any) -> str:
    """La conversation qui a lancé : celle que la fiche retient, sinon celle de l'origine."""
    return (getattr(lancement, "lanceur", "") or "").strip() or conversation_du_lanceur(lancement.origine)


def conversation_du_lanceur(origine: str) -> str:
    """L'identifiant de la conversation qui a lancé, ou « » (automate, gardien, personne)."""
    origine = (origine or "").strip()
    if origine.startswith(PREFIXE_CONVERSATION):
        return origine[len(PREFIXE_CONVERSATION):].strip()
    return ""


class RelaisAuLanceur:
    def __init__(
        self,
        *,
        store: Any,
        lanceur: Any,
        projets: Path,
        attendre: Callable[[float], None] = time.sleep,
        en_fil: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self.store = store
        self.lanceur = lanceur
        self.projets = Path(projets)
        self._attendre = attendre
        self._en_fil = en_fil or self._fil
        self._verrou = threading.Lock()

    @staticmethod
    def _fil(travail: Callable[[], None]) -> None:
        threading.Thread(target=travail, name="relais-au-lanceur", daemon=True).start()

    # ── une demande se pose ou s'endort ─────────────────────────────────

    def demande(self, quoi: str, demande: Any) -> None:
        """Crochet du harnais (`avis`). Ne lève jamais."""
        try:
            self._demande(quoi, demande)
        except Exception:  # noqa: BLE001 — relayer ne doit jamais faire échouer le tour
            log.exception("relais de la demande au lanceur")

    def _demande(self, quoi: str, demande: Any) -> None:
        if quoi not in ("attendue", "veille"):
            return
        lancement = self._lancement_de(demande.session_id)
        if lancement is None or not lancement.supervise:
            return
        lanceur_id = lanceur_de(lancement)
        if not lanceur_id or lanceur_id == lancement.conversation or self.store.get(lanceur_id) is None:
            return
        from mcp_gateway.atelier.perimetre_du_lanceur import hors_perimetre, resume_de_la_demande

        if hors_perimetre(demande, self.projets / lancement.projet) is not None:
            return  # la personne décide
        with self._verrou:
            if not self._reserver(lancement, f"demande:{demande.request_id}"):
                return
        resume = resume_de_la_demande(demande)
        nom = lancement.nom or lancement.id
        texte = (
            f"[Atelier] L'agent « {nom} » (lancement {lancement.id}) attend ton accord pour {resume}\n"
            "C'est dans ton périmètre de lanceur : réponds avec "
            f'atelier_decider(demande="{demande.request_id}", decision="allow") pour autoriser, '
            'ou decision="deny" et motif="…" pour refuser. Il reprend dès ta réponse. '
            "Si c'est déjà réglé (tu l'as vu par atelier_suivre), ignore ce message."
        )
        occupe = self._occupe(lanceur_id)
        self._en_fil(lambda: self._livrer(lanceur_id, texte, demande.request_id, attendre_d_abord=occupe))

    def _livrer(self, lanceur_id: str, texte: str, request_id: str, *, attendre_d_abord: bool) -> None:
        if attendre_d_abord:
            self._attendre(DELAI_LANCEUR_OCCUPE_S)
            if not self._toujours_en_attente(request_id):
                return  # le lanceur a répondu de lui-même
        self._envoyer(lanceur_id, texte)

    # ── l'agent lancé interroge son lanceur ─────────────────────────────

    def demander(self, conversation: str, question: str) -> dict[str, Any]:
        """Envoie la question de l'agent lancé à son lanceur ; ne bloque pas.

        Rend ce qu'il faut dire à l'agent lancé. Lève `Refus` si cette
        conversation n'est pas un lancement supervisé par un agent.
        """
        from mcp_gateway.atelier.commandes.modele import Refus

        question = (question or "").strip()
        if not question:
            raise Refus("question vide")
        lancement = self._lancement_de(conversation)
        if lancement is None or not lancement.supervise:
            raise Refus(
                "cette conversation n'a pas été lancée en supervision par un agent : "
                "pose ta question à la personne."
            )
        lanceur_id = lanceur_de(lancement)
        if not lanceur_id or self.store.get(lanceur_id) is None:
            raise Refus(
                "ton lanceur n'est pas un agent que l'Atelier peut joindre (automate, gardien, personne) : "
                "pose ta question à la personne."
            )
        with self._verrou:
            if not self._reserver(lancement, f"question:{hashlib.sha1(question.encode('utf-8')).hexdigest()[:12]}"):
                raise Refus("cette question a déjà été posée à ton lanceur, ou la limite de messages est atteinte")
        nom = lancement.nom or lancement.id
        texte = (
            f"[Atelier] L'agent « {nom} » (lancement {lancement.id}) te demande :\n{question[:4000]}\n"
            f'Réponds-lui avec atelier_envoyer(conversation="{lancement.conversation}", message="…") : '
            "ton message le relance, il n'attend pas à plein temps."
        )
        self._en_fil(lambda: self._envoyer(lanceur_id, texte))
        return {
            "envoyee": True,
            "a": lanceur_id,
            "suite": (
                "Ta question est partie. Ne bloque pas dessus : fais ce qui ne dépend pas de la réponse, "
                "ou termine ton tour en disant ce que tu attends. La réponse de ton lanceur te relancera."
            ),
        }

    # ── un lancement finit ──────────────────────────────────────────────

    def fin(self, lancement: Any) -> None:
        """Crochet des lancements (`avis`). Ne lève jamais."""
        try:
            self._fin(lancement)
        except Exception:  # noqa: BLE001
            log.exception("relais de la fin au lanceur")

    def _fin(self, lancement: Any) -> None:
        if not lancement.supervise:
            return
        lanceur_id = lanceur_de(lancement)
        if not lanceur_id or self.store.get(lanceur_id) is None:
            return
        # Un lanceur qui travaille voit la fin par atelier_suivre / atelier_lancements :
        # on ne le réveille que s'il est inactif, pour ne pas doubler.
        if self._occupe(lanceur_id):
            return
        with self._verrou:
            if not self._reserver(lancement, f"fin:{lancement.etat}"):
                return
        nom = lancement.nom or lancement.id
        dernier = (lancement.texte or lancement.erreur or "").strip()
        if len(dernier) > 700:
            dernier = dernier[:700] + " …"
        suite = ""
        if lancement.proposition:
            suite = f"\nIl a déposé une proposition dans « À valider » ({lancement.proposition}) : c'est à la personne de la fusionner."
        elif lancement.etat == "en_attente":
            suite = "\nIl attend la personne (hors de ton périmètre)."
        texte = (
            f"[Atelier] L'agent « {nom} » (lancement {lancement.id}) est {lancement.etat.replace('_', ' ')}."
            + (f"\nSon dernier message :\n{dernier}" if dernier else "")
            + suite
            + f'\nLe détail : atelier_transcript(conversation="{lancement.conversation}").'
        )
        self._en_fil(lambda: self._envoyer(lanceur_id, texte))

    # ── outils communs ──────────────────────────────────────────────────

    def _lancement_de(self, session_id: str) -> Any | None:
        for lancement in self.lanceur.tous():
            if lancement.conversation == session_id:
                return lancement
        return None

    def _reserver(self, lancement: Any, marque: str) -> bool:
        """Note qu'on a relayé `marque` ; faux s'il l'était déjà ou si le plafond est atteint."""
        courant = self.lanceur.lire(lancement.id) or lancement
        if marque in courant.relayees or len(courant.relayees) >= RELAIS_MAX:
            return False
        courant.relayees = [*courant.relayees, marque]
        self.lanceur._ecrire(courant)  # noqa: SLF001
        lancement.relayees = courant.relayees
        return True

    def _occupe(self, session_id: str) -> bool:
        try:
            return bool(self.store.harness.tour_en_cours(session_id))
        except Exception:  # noqa: BLE001
            return False

    def _toujours_en_attente(self, request_id: str) -> bool:
        try:
            return self.store.harness.decisions.demande(request_id) is not None
        except Exception:  # noqa: BLE001
            return True

    def _envoyer(self, lanceur_id: str, texte: str) -> None:
        """Livre le message : relance le lanceur s'il est inactif, sinon le met en file."""
        try:
            # peut_attendre : si le lanceur doit lui-même demander à la personne,
            # il dort et reprend, il n'est pas refusé d'office.
            self.store.send(lanceur_id, texte, peut_attendre=True)
        except Exception:  # noqa: BLE001
            log.exception("message au lanceur %s non livré", lanceur_id)
