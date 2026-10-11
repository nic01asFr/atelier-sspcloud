"""Les notifications de l'Atelier : être prévenu, et répondre depuis la notification.

Quand un agent attend la personne (une autorisation, une question), ou qu'un
agent lancé a fini ou s'est bloqué, l'Atelier le dit sur les appareils où la
personne l'a demandé — application fermée, écran verrouillé. L'Atelier est une
PWA : c'est ce qui rend cela possible, y compris sur téléphone.

Trois choses seulement sont décidées ici :

- **Quoi prévenir.** Cinq catégories, réglables en une case chacune, plus des
  heures calmes (on ne sonne pas, la notification reste lisible).
- **À qui, et comment.** Les abonnements des appareils vivent dans la base de la
  passerelle (`notifications.py` : clés VAPID, envoi chiffré par `pywebpush`).
  Ce module n'écrit aucune cryptographie.
- **Répondre depuis la notification.** La charge d'une demande d'accord porte un
  *jeton de décision* : la question, une échéance, une signature. Il ne donne
  qu'un seul pouvoir — répondre **à cette question** — et ne voyage que dans une
  charge chiffrée de bout en bout vers l'appareil de la personne. Le service
  worker n'a donc ni cookie à lire ni clé à garder.

Prévenir ne doit jamais faire échouer ce qu'on annonce : tout ici est
silencieux en cas d'échec, et l'envoi part dans un fil à part (un service de
poussée lent ne bloque pas un tour d'agent).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.decisions import Demande, resume_de_l_action

log = logging.getLogger("atelier.push")

# Ce qu'on peut choisir de recevoir : (libellé en langage courant, par défaut).
CATEGORIES: dict[str, tuple[str, bool]] = {
    "decision": ("Une action attend mon accord", True),
    "question": ("Un agent me pose une question", True),
    "fini": ("Un agent a terminé son travail", False),
    "bloque": ("Un agent est bloqué ou a échoué", True),
    "alerte": ("Une alerte grave de surveillance", True),
}

DUREE_DU_JETON_S = 7 * 24 * 3600  # comme l'âge au-delà duquel une trace n'est plus réveillée
LONGUEUR_DU_DETAIL = 140
_HEURE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
FUSEAU_PAR_DEFAUT = "Europe/Paris"


# -- les préférences ------------------------------------------------------


def chemin_des_preferences(settings: AtelierSettings) -> Path:
    return settings.work_dir / ".atelier" / "notifications.json"


def preferences_par_defaut() -> dict[str, Any]:
    return {
        "categories": {nom: defaut for nom, (_, defaut) in CATEGORIES.items()},
        "calme": {"actif": False, "de": "22:00", "a": "07:00"},
        "fuseau": FUSEAU_PAR_DEFAUT,
        # Montrer ce que l'agent demande sur l'écran verrouillé, ou seulement
        # « ouvrez l'Atelier » : question de discrétion, pas de confort.
        "detail": True,
    }


def _fuseau_valide(nom: str) -> bool:
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(nom)
    except Exception:  # noqa: BLE001 — inconnu, ou base de fuseaux absente
        return False
    return True


def assainir(brut: Any) -> dict[str, Any]:
    """Des préférences complètes et valides, quoi qu'on ait lu ou reçu.

    Ce qui est inconnu ou mal formé est ignoré, pas refusé : un fichier abîmé
    ne doit pas priver la personne de ses notifications.
    """
    prefs = preferences_par_defaut()
    if not isinstance(brut, dict):
        return prefs
    cases = brut.get("categories")
    if isinstance(cases, dict):
        for nom in CATEGORIES:
            if isinstance(cases.get(nom), bool):
                prefs["categories"][nom] = cases[nom]
    calme = brut.get("calme")
    if isinstance(calme, dict):
        if isinstance(calme.get("actif"), bool):
            prefs["calme"]["actif"] = calme["actif"]
        for borne in ("de", "a"):
            valeur = calme.get(borne)
            if isinstance(valeur, str) and _HEURE.match(valeur):
                prefs["calme"][borne] = valeur
    fuseau = brut.get("fuseau")
    if isinstance(fuseau, str) and fuseau and _fuseau_valide(fuseau):
        prefs["fuseau"] = fuseau
    if isinstance(brut.get("detail"), bool):
        prefs["detail"] = brut["detail"]
    return prefs


def lire_les_preferences(settings: AtelierSettings) -> dict[str, Any]:
    try:
        brut = json.loads(chemin_des_preferences(settings).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        brut = None
    return assainir(brut)


def ecrire_les_preferences(settings: AtelierSettings, patch: dict[str, Any]) -> dict[str, Any]:
    """Applique un changement partiel et rend les préférences résultantes."""
    actuelles = lire_les_preferences(settings)
    if isinstance(patch.get("categories"), dict):
        actuelles["categories"].update(
            {k: v for k, v in patch["categories"].items() if k in CATEGORIES}
        )
    if isinstance(patch.get("calme"), dict):
        actuelles["calme"].update(patch["calme"])
    for cle in ("fuseau", "detail"):
        if cle in patch:
            actuelles[cle] = patch[cle]
    prefs = assainir(actuelles)
    chemin = chemin_des_preferences(settings)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(".tmp")
    tmp.write_text(json.dumps(prefs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(chemin)
    return prefs


def en_heures_calmes(prefs: dict[str, Any], maintenant: datetime | None = None) -> bool:
    """Vrai quand on ne doit pas sonner. La fenêtre peut passer minuit (22:00 → 07:00)."""
    calme = prefs.get("calme") or {}
    if not calme.get("actif"):
        return False
    try:
        from zoneinfo import ZoneInfo

        instant = maintenant or datetime.now(ZoneInfo(prefs.get("fuseau") or FUSEAU_PAR_DEFAUT))
    except Exception:  # noqa: BLE001
        instant = maintenant or datetime.now()
    courant = instant.strftime("%H:%M")
    de, a = str(calme.get("de") or "22:00"), str(calme.get("a") or "07:00")
    if de == a:
        return False
    if de < a:
        return de <= courant < a
    return courant >= de or courant < a


# -- le jeton de décision -------------------------------------------------


def _cle_de_signature(cle_proprietaire: str) -> bytes:
    # Dérivée de la clé du propriétaire : renouveler celle-ci invalide les
    # jetons en circulation, comme elle ferme les sessions.
    return hmac.new(cle_proprietaire.encode("utf-8"), b"atelier-push-decision-v1", hashlib.sha256).digest()


def jeton_de_decision(cle_proprietaire: str, request_id: str, expire: int | None = None) -> str:
    """Le droit de répondre à CETTE question, jusqu'à une échéance."""
    echeance = int(expire if expire is not None else time.time() + DUREE_DU_JETON_S)
    corps = f"{request_id}.{echeance}"
    signature = hmac.new(
        _cle_de_signature(cle_proprietaire), corps.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:40]
    return f"{corps}.{signature}"


def lire_le_jeton(cle_proprietaire: str, jeton: str, maintenant: float | None = None) -> str | None:
    """La question que ce jeton permet de trancher, ou `None` (faux, périmé, trafiqué)."""
    if not isinstance(jeton, str) or jeton.count(".") < 2:
        return None
    corps, _, signature = jeton.rpartition(".")
    request_id, _, echeance = corps.rpartition(".")
    if not request_id or not echeance.isdigit():
        return None
    attendue = hmac.new(
        _cle_de_signature(cle_proprietaire), corps.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:40]
    if not hmac.compare_digest(signature, attendue):
        return None
    if int(echeance) < (maintenant if maintenant is not None else time.time()):
        return None
    return request_id


# -- le notifieur ---------------------------------------------------------


def _court(texte: str, limite: int = LONGUEUR_DU_DETAIL) -> str:
    propre = " ".join(str(texte or "").split())
    return propre if len(propre) <= limite else propre[: limite - 1] + "…"


class Notifieur:
    """Décide s'il faut prévenir, compose la notification, la pousse.

    `envoyer(titre, corps, **charge)` est injectable : les tests n'envoient rien,
    et rendent le nombre d'appareils atteints comme le fait l'envoi réel.
    """

    def __init__(
        self,
        db: Any,
        settings: AtelierSettings,
        cle_proprietaire: str,
        store: Any = None,
        envoyer: Callable[..., int] | None = None,
        asynchrone: bool = True,
    ) -> None:
        self.db = db
        self.settings = settings
        self._cle = cle_proprietaire
        self.store = store
        self._envoyer = envoyer or self._envoi_reel
        self._asynchrone = asynchrone and envoyer is None
        self._deja: dict[str, float] = {}
        self._verrou = threading.Lock()
        # La table des abonnements : la passerelle la crée à son démarrage,
        # mais l'Atelier n'a pas à en dépendre (ni les tests, sans passerelle).
        try:
            from mcp_gateway.notifications import migrer_schema

            migrer_schema(db)
        except Exception:  # noqa: BLE001 — sans table, il n'y a simplement aucun appareil
            log.exception("table des abonnements non préparée")

    # -- l'état -----------------------------------------------------------

    @staticmethod
    def disponible() -> bool:
        """Faux quand `pywebpush` n'est pas installé : on le dit, on n'échoue pas en silence."""
        try:
            import pywebpush  # noqa: F401
        except ImportError:
            return False
        return True

    def appareils(self) -> list[dict[str, Any]]:
        from mcp_gateway.notifications import abonnements

        try:
            return abonnements(self.db)
        except Exception:  # noqa: BLE001
            return []

    # -- l'envoi ----------------------------------------------------------

    def _envoi_reel(self, titre: str, corps: str, **charge: Any) -> int:
        from mcp_gateway.notifications import prevenir

        return prevenir(
            self.db,
            titre,
            corps,
            url=str(charge.pop("url", "/")),
            tag=str(charge.pop("tag", "atelier")),
            extra=charge or None,
        )

    def _pousser(self, titre: str, corps: str, **charge: Any) -> int:
        """Pousse vers tous les appareils. Rend le nombre atteint (0 en différé)."""
        if self._asynchrone:
            threading.Thread(
                target=self._pousser_sans_bruit,
                args=(titre, corps, charge),
                daemon=True,
                name="push",
            ).start()
            return 0
        return self._pousser_sans_bruit(titre, corps, charge)

    def _pousser_sans_bruit(self, titre: str, corps: str, charge: dict[str, Any]) -> int:
        try:
            return int(self._envoyer(titre, corps, **charge) or 0)
        except Exception:  # noqa: BLE001 — prévenir ne doit jamais faire échouer ce qu'on annonce
            log.exception("notification non envoyée")
            return 0

    # -- composer ---------------------------------------------------------

    def _agent(self, session_id: str) -> tuple[str, str]:
        """Le nom sous lequel la personne reconnaît cette conversation, et où l'ouvrir."""
        fiche = None
        try:
            fiche = self.store.get(session_id) if self.store is not None else None
        except Exception:  # noqa: BLE001
            fiche = None
        if fiche is None:
            return "Un agent", f"/?session={session_id}"
        nom = (getattr(fiche, "title", "") or getattr(fiche, "slug", "") or "Un agent").strip()
        if getattr(fiche, "kind", "") == "assistant":
            return nom, f"/?view=assistant&session={session_id}"
        slug = getattr(fiche, "slug", "")
        return nom, f"/?slug={slug}&session={session_id}" if slug else f"/?session={session_id}"

    def _deja_dit(self, cle: str, ttl_s: float | None = None) -> bool:
        """Vrai si on a déjà prévenu pour cela (et, avec `ttl_s`, depuis moins longtemps que ça)."""
        with self._verrou:
            vu = self._deja.get(cle)
            if vu is not None and (ttl_s is None or time.time() - vu < ttl_s):
                return True
            if len(self._deja) > 500:
                for ancienne in sorted(self._deja, key=self._deja.get)[:250]:
                    self._deja.pop(ancienne, None)
            self._deja[cle] = time.time()
            return False

    def _contexte(self, categorie: str) -> tuple[dict[str, Any], bool] | None:
        """Les préférences, et s'il faut rester silencieux ; `None` si la catégorie est coupée."""
        prefs = lire_les_preferences(self.settings)
        if not prefs["categories"].get(categorie):
            return None
        return prefs, en_heures_calmes(prefs)

    # -- les avis ---------------------------------------------------------

    def avis(self, quoi: str, demande: Demande) -> None:
        """Une question se pose (`attendue`) ou s'endort (`veille`). Ne lève jamais."""
        try:
            self._avis(quoi, demande)
        except Exception:  # noqa: BLE001
            log.exception("avis « %s » non rendu", quoi)

    def _avis(self, quoi: str, demande: Demande) -> None:
        if not self.appareils():
            return
        categorie = "question" if demande.genre == "question" else "decision"
        contexte = self._contexte(categorie)
        if contexte is None:
            return
        # `attendue` puis `veille` portent la même question : une seule
        # notification, la première.
        if self._deja_dit(f"decision:{demande.request_id}"):
            return
        prefs, silencieux = contexte
        nom, url = self._agent(demande.session_id)
        if demande.genre == "question":
            questions = demande.questions
            texte = (questions[0].get("question") or questions[0].get("header") or "") if questions else ""
            titre, detail = f"{nom} vous pose une question", _court(texte)
            actions: list[str] = []
        else:
            titre, detail = f"{nom} a besoin de votre accord", _court(resume_de_l_action(demande))
            actions = ["allow", "deny"]
        if not prefs["detail"]:
            detail = "Ouvrez l’Atelier pour voir la demande."
        self._pousser(
            titre,
            detail,
            url=url,
            tag=f"decision-{demande.request_id}",
            categorie=categorie,
            silencieux=silencieux,
            decision={
                "id": demande.request_id,
                "genre": demande.genre,
                "jeton": jeton_de_decision(self._cle, demande.request_id),
            },
            actions=actions,
        )

    def decision_prise(self, request_id: str, accordee: bool) -> None:
        """La question a trouvé sa réponse (ici ou ailleurs) : la notification se referme."""
        try:
            if not self.appareils():
                return
            self._pousser(
                "Réponse enregistrée",
                "Autorisé." if accordee else "Refusé.",
                url="/",
                tag=f"decision-{request_id}",
                categorie="decision",
                silencieux=True,
                resolue=True,
            )
        except Exception:  # noqa: BLE001
            log.exception("clôture de la notification non envoyée")

    def lancement(self, lancement: Any) -> None:
        """Un agent lancé a fini, ou s'est arrêté sans y arriver. Ne lève jamais."""
        try:
            if not self.appareils():
                return
            etat = getattr(lancement, "etat", "")
            if etat == "fini":
                categorie, ton = "fini", "a terminé son travail"
            elif etat in ("echec", "delai", "interrompu"):
                categorie, ton = "bloque", "s’est arrêté sans finir"
            else:
                return
            contexte = self._contexte(categorie)
            if contexte is None:
                return
            if self._deja_dit(f"lancement:{lancement.id}:{etat}"):
                return
            prefs, silencieux = contexte
            nom = (getattr(lancement, "nom", "") or getattr(lancement, "projet", "") or "Un agent").strip()
            detail = _court(getattr(lancement, "erreur", "") or getattr(lancement, "texte", "") or "")
            if not prefs["detail"]:
                detail = ""
            _, url = self._agent(getattr(lancement, "conversation", "") or "")
            self._pousser(
                f"{nom} {ton}",
                detail,
                url=url,
                tag=f"lancement-{lancement.id}",
                categorie=categorie,
                silencieux=silencieux,
            )
        except Exception:  # noqa: BLE001
            log.exception("avis de lancement non rendu")

    # Une alerte qui s'ouvre, se résout et se rouvre ne doit pas faire sonner dix
    # fois : on ne la redit qu'après ce délai (registre des défauts D-24).
    DELAI_ENTRE_DEUX_ALERTES_S = 6 * 3600

    def alerte(self, alerte: dict[str, Any]) -> None:
        """Une alerte grave des gardiens vient de s'ouvrir. Ne lève jamais."""
        try:
            if not self.appareils():
                return
            contexte = self._contexte("alerte")
            if contexte is None:
                return
            if self._deja_dit(f"alerte:{alerte.get('empreinte')}", self.DELAI_ENTRE_DEUX_ALERTES_S):
                return
            prefs, silencieux = contexte
            self._pousser(
                "Alerte de surveillance",
                _court(alerte.get("resume") or "") if prefs["detail"] else "Ouvrez l’Atelier pour la voir.",
                url="/?view=agent",
                tag=f"alerte-{alerte.get('empreinte')}",
                categorie="alerte",
                silencieux=silencieux,
            )
        except Exception:  # noqa: BLE001
            log.exception("avis d'alerte non rendu")

    async def surveiller_les_alertes(
        self, lire: Callable[[], Any], intervalle_s: float = 60.0
    ) -> None:
        """Prévient des alertes graves **nouvelles** des gardiens.

        Les gardiens tournent dans un autre processus : l'Atelier ne voit pas
        leurs écritures, il lit leurs alertes ouvertes. La première lecture
        fixe la base — on ne fait pas sonner pour ce qui était déjà ouvert
        avant qu'on ne regarde.
        """
        import asyncio

        connues: set[str] | None = None
        while True:
            try:
                brut = await lire()
                liste = brut.get("alertes", []) if isinstance(brut, dict) else brut
                ouvertes = {
                    str(a.get("empreinte")): a
                    for a in (liste or [])
                    if isinstance(a, dict) and a.get("niveau") == "alerte" and a.get("empreinte")
                }
                if connues is None:
                    connues = set(ouvertes)
                else:
                    for empreinte, a in ouvertes.items():
                        if empreinte not in connues:
                            connues.add(empreinte)
                            self.alerte(a)
                    # Résolue puis rouverte : la nouvelle ouverture est vue, mais
                    # `alerte` ne la redit qu'après son délai.
                    connues = set(ouvertes)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — gardiens injoignables : on réessaiera
                pass
            await asyncio.sleep(intervalle_s)

    def essai(self) -> dict[str, Any]:
        """Envoie une notification d'essai et dit honnêtement ce qui s'est passé.

        Le seul moyen de savoir que la chaîne entière tient — le pod joint le
        service de poussée, le navigateur l'a reçue — avant qu'un agent n'ait
        vraiment besoin de la personne.
        """
        appareils = self.appareils()
        if not self.disponible():
            return {
                "ok": False,
                "disponible": False,
                "appareils": len(appareils),
                "atteints": 0,
                "message": "Les notifications ne sont pas installées sur ce service.",
            }
        if not appareils:
            return {
                "ok": False,
                "disponible": True,
                "appareils": 0,
                "atteints": 0,
                "message": "Aucun appareil n’est inscrit : activez les notifications sur celui-ci d’abord.",
            }
        atteints = self._pousser_sans_bruit(
            "L’Atelier vous prévient",
            "Les notifications fonctionnent. Vous serez prévenu quand un agent aura besoin de vous.",
            {"url": "/", "tag": "essai", "categorie": "essai", "silencieux": False},
        )
        if atteints:
            msg = f"Reçu sur {atteints} appareil" + ("s" if atteints > 1 else "") + "."
        else:
            msg = (
                "Rien n’a pu être envoyé. Le service de notifications de votre navigateur est peut-être "
                "injoignable depuis ce pod, ou l’autorisation a été retirée sur l’appareil."
            )
        return {"ok": atteints > 0, "disponible": True, "appareils": len(appareils), "atteints": atteints, "message": msg}
