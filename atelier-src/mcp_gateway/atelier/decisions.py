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
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# L'outil par lequel l'agent pose une question à l'utilisateur. Il arrive par
# le même canal qu'une demande d'autorisation — mesuré — mais il ne demande pas
# la permission d'agir : il demande une réponse.
#
# L'autoriser ne sert à rien : le CLI, n'ayant pas d'écran pour poser la
# question, conclut aussitôt « The user did not answer the questions ». C'est
# le message d'un refus qui lui revient comme résultat, verbatim — c'est donc
# par là que la réponse passe. Le mot « refus » n'est qu'un véhicule.
OUTIL_QUESTION = "AskUserQuestion"


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
    # « autorisation » : peut-on faire ceci ? « question » : que répondez-vous ?
    # Deux cartes différentes à l'écran, un seul canal en dessous.
    genre: str = "autorisation"

    @property
    def questions(self) -> list[dict[str, Any]]:
        """Les questions posées, telles que le modèle les a formulées."""
        brut = self.arguments.get("questions")
        return [q for q in brut if isinstance(q, dict)] if isinstance(brut, list) else []

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
            genre=(
                "question"
                if requete.get("tool_name") == OUTIL_QUESTION
                else "autorisation"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def chemins_vises(demande: Demande) -> list[str]:
    """Les chemins qu'un outil s'apprête à toucher.

    Sert à savoir si une autorisation déjà donnée sur un répertoire couvre
    cette demande. Les noms viennent des outils du CLI ; on ne devine pas.
    """
    champs = ("file_path", "path", "notebook_path", "directory", "cwd")
    vus: list[str] = []
    for champ in champs:
        valeur = demande.arguments.get(champ)
        if isinstance(valeur, str) and valeur:
            vus.append(valeur)
    return vus


_SEPARATEURS = re.compile(r"\|\||&&|\||;|\n")
_REDIRECTION_SEULE = re.compile(r"^\d*(>>?|<)(&\d+)?$")
_REDIRECTION_COLLEE = re.compile(r"^\d*(>>?|<)\S+$")


def segments_de_la_commande(commande: str) -> list[str]:
    """Les sous-commandes d'une ligne, telles que le CLI les juge une à une.

    Mesuré : pour `./x.sh 2>&1 | tail -5`, le CLI répond
    `decision_reason_type: subcommandResults` et ne suggère de règle que pour
    `./x.sh` — il a découpé sur le tube, jugé `tail -5` inoffensif, et ôté
    la redirection avant de comparer. On découpe comme lui, sans prétendre
    connaître sa liste de commandes sûres.
    """
    return [
        sans_redirections(morceau)
        for morceau in _SEPARATEURS.split(commande)
        if sans_redirections(morceau)
    ]


def sans_redirections(segment: str) -> str:
    """`./x.sh 2>&1` et `./x.sh > out.txt` sont `./x.sh` aux yeux du CLI."""
    gardes: list[str] = []
    sauter = False
    for mot in segment.split():
        if sauter:
            sauter = False
            continue
        if _REDIRECTION_SEULE.match(mot):
            # `> fichier` : la cible suit et part avec ; `2>&1` se suffit.
            sauter = "&" not in mot
            continue
        if _REDIRECTION_COLLEE.match(mot):
            continue
        gardes.append(mot)
    return " ".join(gardes)


def _regle_couvre_le_segment(valeur: str, segment: str) -> bool:
    """La syntaxe du CLI : `x` exact, `x:*` tout ce qui commence par `x`."""
    if valeur.endswith(":*"):
        prefixe = valeur[:-2]
        return segment == prefixe or segment.startswith(prefixe + " ")
    return segment == valeur


@dataclass
class Regle:
    """Une décision qu'on ne veut plus reprendre.

    Trois portées, et aucune n'est inventée : ce sont celles que le CLI
    propose lui-même dans chaque demande. `repertoire` vient de sa suggestion
    `addDirectories`, `commande` de `addRules`, et `outil` est le cas simple —
    « cet outil, dans ce fil, ne me demande plus ».

    Une règle ne vaut que pour une conversation. Rien ne fuit d'un fil à
    l'autre : c'est là qu'on a accordé, c'est là que ça s'applique.

    `outil` nomme l'outil d'une règle `commande` (« Bash », le plus souvent) :
    c'est ce qu'il faut pour la rendre au CLI dans sa propre syntaxe,
    `Bash(./x.sh)`. Vide sur les règles écrites avant ce champ.
    """

    session_id: str
    portee: str
    valeur: str
    posee_le: str = field(default_factory=_maintenant)
    outil: str = ""

    def couvre(self, demande: Demande) -> bool:
        if demande.session_id != self.session_id:
            return False
        # Une question ne s'accorde pas d'avance. L'autoriser sans réponse ne
        # rendrait rien au modèle, et « ne plus me demander » n'a aucun sens
        # quand ce qu'on demande, c'est un avis.
        if demande.genre == "question":
            return False
        if self.portee == "outil":
            return demande.outil == self.valeur
        if self.portee == "commande":
            if self.outil and demande.outil != self.outil:
                return False
            segments = segments_de_la_commande(str(demande.arguments.get("command") or ""))
            return bool(segments) and all(
                _regle_couvre_le_segment(self.valeur, s) for s in segments
            )
        if self.portee == "repertoire":
            racine = self.valeur.rstrip("/") or "/"
            for chemin in chemins_vises(demande):
                if chemin == racine or chemin.startswith(racine + "/"):
                    return True
        return False

    def pour_le_cli(self) -> str:
        """La règle dans la syntaxe des réglages du CLI (`permissions.allow`).

        Vide pour un répertoire : celui-là se passe par
        `permissions.additionalDirectories`, pas par une règle d'outil.
        """
        if self.portee == "outil":
            return self.valeur
        if self.portee == "commande":
            return f"{self.outil or 'Bash'}({self.valeur})"
        return ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def regles_suggerees(demande: Demande) -> list[Regle]:
    """Les règles que le CLI propose lui-même pour cette demande.

    On suit ses suggestions dans l'ordre où elles portent le moins loin :
    les commandes précises avant un répertoire entier, et l'outil seulement
    faute de mieux. Élargir plus que nécessaire serait accorder plus que ce
    qu'on nous demande.

    Toutes les règles de commande sont prises, pas la première : pour une
    ligne `a && b` le CLI en propose une par sous-commande qu'il juge à
    demander, et n'en retenir qu'une le ferait redemander l'autre.

    Une question n'en a jamais : on ne se dispense pas de donner son avis.
    """
    if demande.genre == "question":
        return []
    commandes: list[Regle] = []
    for suggestion in demande.suggestions:
        if suggestion.get("type") != "addRules":
            continue
        for regle in suggestion.get("rules") or []:
            contenu = regle.get("ruleContent")
            outil = regle.get("toolName")
            if isinstance(contenu, str) and contenu:
                commandes.append(
                    Regle(
                        demande.session_id,
                        "commande",
                        contenu,
                        outil=outil if isinstance(outil, str) else "",
                    )
                )
    if commandes:
        return commandes
    for suggestion in demande.suggestions:
        if suggestion.get("type") != "addDirectories":
            continue
        for dossier in suggestion.get("directories") or []:
            if isinstance(dossier, str) and dossier:
                return [Regle(demande.session_id, "repertoire", dossier)]
    if demande.outil:
        return [Regle(demande.session_id, "outil", demande.outil)]
    return []


def regle_suggeree(demande: Demande) -> Regle | None:
    """La première des règles suggérées — celle qu'on nomme à l'écran."""
    regles = regles_suggerees(demande)
    return regles[0] if regles else None


def permissions_a_retenir(demande: Demande) -> list[dict[str, Any]]:
    """Les suggestions du CLI, à lui rendre telles quelles avec l'autorisation.

    Le protocole le prévoit : une réponse `allow` peut porter
    `updatedPermissions`, et le CLI applique ces règles sur-le-champ, avec sa
    propre sémantique — il cesse de demander dans le tour courant. On force
    la destination `session` : le processus meurt avec le tour, et c'est
    notre registre, repassé au tour suivant, qui fait durer la décision.
    Rien n'est écrit dans les réglages du dossier, que d'autres fils
    partagent.
    """
    retenues: list[dict[str, Any]] = []
    for suggestion in demande.suggestions:
        if suggestion.get("type") not in ("addRules", "addDirectories"):
            continue
        copie = dict(suggestion)
        copie["destination"] = "session"
        retenues.append(copie)
    return retenues


def reglages_cli(regles: list[Regle]) -> dict[str, Any]:
    """Ce qu'on passe au CLI par `--settings` pour qu'il applique lui-même
    ce qu'on a accordé dans ce fil.

    C'est lui qui découpe, juge et compare ; nous ne faisons que lui rendre
    ses règles dans sa syntaxe. Vide quand rien n'a été accordé : on n'ajoute
    pas un drapeau pour rien.
    """
    autorisees = [r.pour_le_cli() for r in regles if r.pour_le_cli()]
    dossiers = [r.valeur for r in regles if r.portee == "repertoire" and r.valeur]
    permissions: dict[str, Any] = {}
    if autorisees:
        permissions["allow"] = autorisees
    if dossiers:
        permissions["additionalDirectories"] = dossiers
    return {"permissions": permissions} if permissions else {}


def reponse_aux_questions(demande: Demande, choix: list[list[str]]) -> dict[str, Any]:
    """Rend les réponses de l'utilisateur au modèle.

    Elles voyagent dans le message d'un refus, parce que c'est le seul champ
    du protocole qui revienne au modèle verbatim — vérifié : il l'a reçu tel
    quel et a poursuivi. Autoriser l'outil, au contraire, ne produit qu'un
    « the user did not answer ».

    On nomme chaque réponse par l'intitulé de sa question, faute de quoi un
    modèle qui en a posé trois ne saurait pas laquelle on lui rend.
    """
    lignes: list[str] = []
    for rang, question in enumerate(demande.questions):
        repondu = choix[rang] if rang < len(choix) else []
        if not repondu:
            continue
        intitule = str(question.get("header") or question.get("question") or f"Question {rang + 1}")
        lignes.append(f"- {intitule} : " + ", ".join(str(r) for r in repondu))
    if not lignes:
        return {"behavior": "deny", "message": "L'utilisateur n'a pas répondu."}
    return {
        "behavior": "deny",
        "message": "Réponse de l'utilisateur :" + chr(10) + chr(10).join(lignes),
    }


def reponse_autorisee(
    arguments: dict[str, Any] | None = None,
    permissions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Laisser passer, éventuellement avec des arguments corrigés.

    `permissions` sont les règles à faire appliquer par le CLI dès
    maintenant — celles qu'il a suggérées, rendues avec « toujours ».
    """
    reponse: dict[str, Any] = {"behavior": "allow", "updatedInput": arguments or {}}
    if permissions:
        reponse["updatedPermissions"] = permissions
    return reponse


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
        self._regles: dict[str, list[Regle]] = {}
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

    # -- la mémoire des décisions -----------------------------------------

    def _chemin_regles(self, session_id: str) -> Path:
        return self._dossier / "regles" / f"{session_id}.json"

    def regles(self, session_id: str) -> list[Regle]:
        """Ce qu'on a déjà accordé dans cette conversation.

        Relues du disque à la première demande : une règle posée hier doit
        valoir aujourd'hui, sans quoi on reposerait la question à chaque
        redémarrage — et le mode `manual` redeviendrait invivable.
        """
        with self._verrou:
            connues = self._regles.get(session_id)
        if connues is not None:
            return list(connues)
        lues: list[Regle] = []
        try:
            brut = json.loads(self._chemin_regles(session_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            brut = []
        if isinstance(brut, list):
            champs = set(Regle.__dataclass_fields__)
            for item in brut:
                if isinstance(item, dict):
                    lues.append(Regle(**{k: v for k, v in item.items() if k in champs}))
        with self._verrou:
            self._regles[session_id] = lues
        return list(lues)

    def retenir(self, regle: Regle) -> None:
        """Garde une décision pour ne plus la reposer."""
        deja = self.regles(regle.session_id)
        if any(r.portee == regle.portee and r.valeur == regle.valeur for r in deja):
            return
        deja.append(regle)
        with self._verrou:
            self._regles[regle.session_id] = deja
        try:
            chemin = self._chemin_regles(regle.session_id)
            chemin.parent.mkdir(parents=True, exist_ok=True)
            chemin.write_text(
                json.dumps([r.to_dict() for r in deja], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def regle_qui_couvre(self, demande: Demande) -> Regle | None:
        """La règle déjà posée qui dispense de reposer cette question.

        Pour une ligne de commande, les règles se cumulent comme chez le CLI :
        `a && b` est couverte si `a` l'est par une règle et `b` par une
        autre. On rend la première qui participe, pour nommer la cause.
        """
        regles = self.regles(demande.session_id)
        for regle in regles:
            if regle.couvre(demande):
                return regle
        commande = demande.arguments.get("command")
        if demande.genre == "question" or not isinstance(commande, str):
            return None
        segments = segments_de_la_commande(commande)
        de_commande = [
            r
            for r in regles
            if r.portee == "commande"
            and r.session_id == demande.session_id
            and (not r.outil or r.outil == demande.outil)
        ]
        if not segments or not de_commande:
            return None
        for segment in segments:
            if not any(_regle_couvre_le_segment(r.valeur, segment) for r in de_commande):
                return None
        return de_commande[0]

    def oublier_les_regles(self, session_id: str) -> int:
        """Rend à la conversation son état de départ : tout redevient à décider."""
        nombre = len(self.regles(session_id))
        with self._verrou:
            self._regles[session_id] = []
        try:
            self._chemin_regles(session_id).unlink(missing_ok=True)
        except OSError:
            pass
        return nombre

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

    def demande(self, request_id: str) -> Demande | None:
        """La question elle-même, tant qu'un tour l'attend.

        La route en a besoin pour retenir une règle : c'est la demande qui
        porte les suggestions du CLI, et elle disparaît dès qu'on répond.
        """
        with self._verrou:
            return self._vives.get(request_id)

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

    def relacher(self, request_id: str) -> Demande | None:
        """Cesse d'attendre, mais garde la question.

        L'attente vive coûte un processus garé — environ 130 Mo qu'aucun
        échange ne récupère, ce pod n'ayant pas de zone d'échange. Au bout
        d'un long silence, on rend cette mémoire. La trace, elle, reste : la
        décision n'expire pas, seul le chemin rapide expire.
        """
        with self._verrou:
            demande = self._vives.pop(request_id, None)
            self._reponses.pop(request_id, None)
            self._signaux.pop(request_id, None)
        return demande

    def demande_tracee(self, request_id: str) -> Demande | None:
        """Relit une question sur le disque, même si plus personne ne l'attend.

        C'est ce qui permet de répondre à une question relâchée, ou posée
        avant un redémarrage : on ne reprend pas le tour, mais la décision
        est prise et retenue.
        """
        try:
            brut = json.loads(self._chemin(request_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(brut, dict):
            return None
        champs = set(Demande.__dataclass_fields__)
        demande = Demande(**{k: v for k, v in brut.items() if k in champs})
        demande.vive = False
        return demande

    def en_attente(self, session_id: str = "") -> list[Demande]:
        """Les questions vives, filtrées par conversation si on le demande."""
        with self._verrou:
            demandes = list(self._vives.values())
        if session_id:
            demandes = [d for d in demandes if d.session_id == session_id]
        return sorted(demandes, key=lambda d: d.posee_le)

    def oublier_les_questions(self, session_id: str) -> int:
        """Efface jusqu'aux traces des questions de cette conversation.

        `abandonner` ne referme que les attentes vives. Une question relâchée,
        ou survivante d'un redémarrage, n'a plus personne qui l'attende : rien
        ne la retirait, et elle restait affichable pour une conversation qui
        n'existe plus.
        """
        efface = 0
        for demande in self.orphelines():
            if demande.session_id == session_id:
                self._effacer(demande.request_id)
                efface += 1
        return efface

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
