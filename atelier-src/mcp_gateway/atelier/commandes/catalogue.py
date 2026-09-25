"""Le catalogue des commandes : une porte, la classe vérifiée, chaque appel journalisé.

L'interface, l'Assistant et les agents agissent sur les objets de l'Atelier par
les mêmes commandes (transverse §1.8). Ce module est cette porte unique :

- **pour les modèles**, il est la famille d'outils locaux de la passerelle
  (`McpGateway.outils_locaux`) : `definitions()` et `appeler()`. Un appel
  direct à `atelier_x` comme un appel par `gateway_call_tool` y aboutissent,
  car le méta-outil repasse par `tools_call` (`mcp/gateway.py`) ;
- **pour l'interface**, il est servi par `/v1/commandes` (`routes.py`).

La classe est vérifiée ici, à l'exécution, quel que soit le chemin :

- `reservee` : refusée à tout appel qui n'est pas la personne dans
  l'interface. La clé du propriétaire ne suffit pas : les agents du pod la
  lisent aussi ;
- `engageante` : sans jeton de confirmation, rend un aperçu et un jeton, et
  n'agit pas. Le jeton ne vaut que pour la même commande, les mêmes arguments
  et le même acteur, une fois, dix minutes ;
- `reversible` : agit, rend une carte avec « Annuler » ;
- `lecture` : agit, sans carte.

Les outils `atelier_*` écrits avant le catalogue (`outils_conversation.py`)
gardent leur nom et leur code : le catalogue les enrobe d'une déclaration
(`existants.py`). Un outil de cette famille que personne n'a déclaré passe
quand même, en classe `reversible`, et le journal le dit (`objet: "non_declare"`).
"""

from __future__ import annotations

import copy
import inspect
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from mcp_gateway.atelier.commandes.journal import Evenement, Journal, empreinte, maintenant, nouvel_identifiant
from mcp_gateway.atelier.commandes.modele import (
    ENGAGEANTE,
    LECTURE,
    ORIGINE_INTERFACE,
    ORIGINE_MCP,
    RESERVEE,
    REVERSIBLE,
    Commande,
    Contexte,
    Effet,
    Refus,
)

log = logging.getLogger("atelier.commandes")

JETON_DUREE_S = 600
ARGUMENT_CONFIRMATION = "confirmation"

FAIT = "fait"
APERCU = "apercu"
REFUSE = "refus"
ERREUR = "erreur"


class ErreurDeCommande(Exception):
    """La commande a été tentée et a échoué ; `charge` est ce qu'elle rend."""

    def __init__(self, charge: Any) -> None:
        super().__init__(str(charge))
        self.charge = charge


@dataclass
class Reponse:
    statut: str
    charge: Any
    action: str = ""

    @property
    def en_erreur(self) -> bool:
        return self.statut in (REFUSE, ERREUR)


@dataclass
class _Jeton:
    nom: str
    arguments: dict[str, Any]
    empreinte: str
    acteur: str
    expire: float


@dataclass
class DeclarationOutil:
    """Ce que le catalogue sait d'un outil `atelier_*` écrit avant lui."""

    objet: str
    classe: str
    inverse: str | None = None
    regles: list[str] = field(default_factory=list)
    # (arguments, charge rendue) -> Effet : la carte, l'objet, l'inverse.
    carte: Callable[[dict[str, Any], Any], Effet] | None = None
    allegement: Callable[[dict[str, Any]], str] | None = None
    # Remplace la description de l'outil : les mots de l'interface, que la
    # personne emploie, et que le modèle doit retrouver dans l'outil.
    description: str | None = None


def _texte_mcp(charge: Any, *, erreur: bool) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(charge, ensure_ascii=False, default=str)}],
        "isError": erreur,
    }


def _charge_de(reponse: dict[str, Any]) -> Any:
    """La charge JSON d'une réponse MCP d'outil (un bloc texte)."""
    for bloc in reponse.get("content") or []:
        if isinstance(bloc, dict) and bloc.get("type") == "text":
            try:
                return json.loads(bloc.get("text") or "null")
            except ValueError:
                return {"texte": bloc.get("text")}
    return {}


_CLES_D_OBJET = ("projet", "slug", "conversation", "nom", "id", "demande", "action")


def _objet_devine(arguments: dict[str, Any]) -> str:
    for cle in _CLES_D_OBJET:
        valeur = arguments.get(cle)
        if isinstance(valeur, str) and valeur.strip():
            if cle == "nom" and isinstance(arguments.get("projet"), str):
                return f"{arguments['projet']}/{valeur}"
            return valeur.strip()
    return ""


def acteur_de_l_appel_mcp() -> str:
    """Qui appelle par la porte `/mcp` : la conversation, sinon un client."""
    from mcp_gateway.atelier.outils_conversation import APPEL_INTERACTIF, CONVERSATION_APPELANTE

    conversation = CONVERSATION_APPELANTE.get()
    if conversation:
        return f"conversation:{conversation}"
    return "client-distant" if APPEL_INTERACTIF.get() else "modele"


def via_de_l_appel() -> str:
    try:
        from mcp_gateway.mcp.gateway import VIA_META_OUTIL
    except ImportError:  # pragma: no cover
        return ""
    return VIA_META_OUTIL.get()


class Catalogue:
    def __init__(self, *, journal: Journal, outils: Any | None = None) -> None:
        self.journal = journal
        self.outils = outils
        self._natives: dict[str, Commande] = {}
        self._declarations: dict[str, DeclarationOutil] = {}
        self._jetons: dict[str, _Jeton] = {}
        self._verrou = threading.Lock()
        # Rappelés après chaque commande réussie qui change quelque chose :
        # la carte de l'Atelier (§1.3) s'y branchera.
        self.apres_commande: list[Callable[[str, dict[str, Any]], None]] = []

    # ── Inscription ─────────────────────────────────────────────────────

    def ajouter(self, commande: Commande) -> Commande:
        if commande.nom in self._natives:
            raise ValueError(f"commande déjà inscrite : {commande.nom}")
        self._natives[commande.nom] = commande
        return commande

    def declarer_outil(self, nom: str, declaration: DeclarationOutil) -> None:
        """Déclare un outil `atelier_*` servi par `outils_conversation`.

        C'est l'unique ligne à ajouter pour qu'un nouvel outil de cette
        famille ait sa classe, son inverse et sa carte.
        """
        self._declarations[nom] = declaration

    def brancher(self, outils: Any) -> None:
        self.outils = outils

    def _definitions_outils(self) -> dict[str, dict[str, Any]]:
        if self.outils is None:
            return {}
        try:
            return {d["name"]: d for d in self.outils.definitions() if isinstance(d, dict) and d.get("name")}
        except Exception:  # noqa: BLE001
            log.exception("définitions des outils atelier")
            return {}

    def _enrober(self, nom: str, definition: dict[str, Any]) -> Commande:
        decl = self._declarations.get(nom) or DeclarationOutil(objet="non_declare", classe=REVERSIBLE)

        async def executer(ctx: Contexte, arguments: dict[str, Any]) -> Effet:
            reponse = await self.outils.appeler(nom, arguments)
            if reponse is None:
                raise Refus(f"outil indisponible : {nom}")
            charge = _charge_de(reponse)
            if reponse.get("isError"):
                raise ErreurDeCommande(charge)
            if decl.carte is not None:
                effet = decl.carte(arguments, charge)
                effet.charge = charge
                return effet
            return Effet(charge=charge, titre=nom, objet_id=_objet_devine(arguments))

        return Commande(
            nom=nom,
            description=decl.description or str(definition.get("description") or ""),
            objet=decl.objet,
            classe=decl.classe,
            executer=executer,
            schema=definition.get("inputSchema") or {"type": "object", "properties": {}},
            inverse=decl.inverse,
            regles=list(decl.regles),
            allegement=decl.allegement,
        )

    def commandes(self) -> dict[str, Commande]:
        """Toutes les commandes : les natives, et les outils atelier présents."""
        toutes: dict[str, Commande] = {}
        for nom, definition in self._definitions_outils().items():
            if nom not in self._natives:
                toutes[nom] = self._enrober(nom, definition)
        toutes.update(self._natives)
        return toutes

    def commande(self, nom: str) -> Commande | None:
        if nom in self._natives:
            return self._natives[nom]
        definition = self._definitions_outils().get(nom)
        return self._enrober(nom, definition) if definition is not None else None

    def declarations(self) -> list[dict[str, Any]]:
        return [c.declaration() for c in sorted(self.commandes().values(), key=lambda c: c.nom)]

    # ── La face MCP (outils locaux de la passerelle) ────────────────────

    def definitions(self) -> list[dict[str, Any]]:
        sortie: list[dict[str, Any]] = []
        for commande in sorted(self.commandes().values(), key=lambda c: c.nom):
            if not commande.exposee_mcp:
                continue
            schema = copy.deepcopy(commande.schema) or {"type": "object", "properties": {}}
            description = commande.description
            if commande.classe == ENGAGEANTE:
                schema.setdefault("properties", {})[ARGUMENT_CONFIRMATION] = {
                    "type": "string",
                    "description": (
                        "Jeton rendu par l'aperçu. À ne passer qu'après le « Oui » de la "
                        "personne, avec les mêmes arguments."
                    ),
                }
                description += (
                    " Commande engageante : un premier appel rend un aperçu et un jeton, "
                    "sans rien faire ; montrez l'aperçu et rappelez avec `confirmation` "
                    "seulement après accord."
                )
            sortie.append(
                {
                    "name": commande.nom,
                    "description": description,
                    "inputSchema": schema,
                    "annotations": {
                        "readOnlyHint": commande.classe == LECTURE,
                        "destructiveHint": False,
                    },
                    "_meta": {
                        "atelier/commande": {
                            "objet": commande.objet,
                            "classe": commande.classe,
                            "inverse": commande.inverse,
                            "regles": list(commande.regles),
                        }
                    },
                }
            )
        return sortie

    @property
    def noms(self) -> set[str]:
        return set(self.commandes())

    async def appeler(self, nom: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        """Un appel venu d'un client MCP. None : ce nom n'est pas à nous."""
        if not nom.startswith("atelier_") or self.commande(nom) is None:
            return None
        ctx = Contexte(acteur=acteur_de_l_appel_mcp(), origine=ORIGINE_MCP, via=via_de_l_appel())
        reponse = await self.executer(nom, arguments or {}, ctx)
        return _texte_mcp(reponse.charge, erreur=reponse.en_erreur)

    # ── Exécution ───────────────────────────────────────────────────────

    def _emettre_jeton(self, nom: str, arguments: dict[str, Any], acteur: str) -> str:
        jeton = secrets.token_urlsafe(18)
        with self._verrou:
            maintenant_s = time.time()
            for cle in [k for k, v in self._jetons.items() if v.expire < maintenant_s]:
                self._jetons.pop(cle, None)
            self._jetons[jeton] = _Jeton(
                nom=nom,
                arguments=copy.deepcopy(arguments),
                empreinte=empreinte(nom, arguments),
                acteur=acteur,
                expire=maintenant_s + JETON_DUREE_S,
            )
        return jeton

    def _consommer_jeton(
        self, jeton: str, nom: str, arguments: dict[str, Any] | None, ctx: Contexte
    ) -> _Jeton | None:
        """Le jeton, s'il vaut pour cet appel ; il est alors détruit.

        Un modèle ne confirme que ce que lui-même a demandé. La personne, dans
        l'interface, peut confirmer l'aperçu montré à un agent : c'est le
        « Oui » qu'il attendait.
        """
        with self._verrou:
            trouve = self._jetons.get(jeton)
            if trouve is None or trouve.expire < time.time() or trouve.nom != nom:
                return None
            if arguments is not None and trouve.empreinte != empreinte(nom, arguments):
                return None
            if trouve.acteur != ctx.acteur and not ctx.est_la_personne:
                return None
            return self._jetons.pop(jeton)

    def _journaliser(
        self,
        *,
        identifiant: str,
        commande: Commande,
        classe: str,
        ctx: Contexte,
        arguments: dict[str, Any],
        resultat: str,
        effet: Effet | None,
        debut: float,
        motif: str = "",
    ) -> None:
        inverse = None
        if effet is not None and commande.inverse and effet.inverse_arguments is not None:
            inverse = {"commande": commande.inverse, "arguments": effet.inverse_arguments}
        action: dict[str, Any] = {
            "commande": commande.nom,
            "classe": classe,
            "origine": ctx.origine,
            "arguments": arguments,
            "avant": effet.avant if effet else None,
            "apres": effet.apres if effet else None,
            "inverse": inverse,
        }
        if ctx.via:
            action["via"] = ctx.via
        if motif:
            action["motif"] = motif
        try:
            self.journal.ecrire(
                Evenement(
                    id=identifiant,
                    source="commande",
                    acteur=ctx.acteur,
                    objet={
                        "type": commande.objet,
                        "id": (effet.objet_id if effet and effet.objet_id else _objet_devine(arguments)),
                    },
                    action=action,
                    resultat=resultat,
                    cout={"jetons": 0, "secondes": round(time.monotonic() - debut, 3)},
                    empreinte=empreinte(commande.nom, arguments),
                )
            )
        except OSError as exc:
            # Un journal qu'on n'arrive pas à écrire se signale ; il ne défait
            # pas ce qui vient d'être fait.
            log.error("journal non écrit pour %s : %s", commande.nom, exc)

    @staticmethod
    def _carte(
        identifiant: str, commande: Commande, ctx: Contexte, effet: Effet
    ) -> dict[str, Any]:
        annuler = None
        if commande.inverse and effet.inverse_arguments is not None:
            annuler = {
                "libelle": "Annuler",
                "commande": "atelier_annuler",
                "arguments": {"action": identifiant},
                "inverse": commande.inverse,
            }
        return {
            "titre": effet.titre or commande.nom,
            "resume": effet.resume,
            "voir": {"libelle": "Voir", "lien": effet.voir} if effet.voir else None,
            "annuler": annuler,
            "preuve": effet.preuve,
            "action": identifiant,
            "par": ctx.acteur,
            "quand": maintenant(),
        }

    async def _apercu(self, commande: Commande, ctx: Contexte, arguments: dict[str, Any]) -> dict[str, Any]:
        if commande.apercu is None:
            return {"commande": commande.nom, "arguments": arguments}
        resultat = commande.apercu(ctx, arguments)
        if inspect.isawaitable(resultat):
            resultat = await resultat
        return resultat

    async def executer(self, nom: str, arguments: dict[str, Any], ctx: Contexte) -> Reponse:
        commande = self.commande(nom)
        if commande is None:
            return Reponse(REFUSE, {"erreur": f"commande inconnue : {nom}"})
        arguments = dict(arguments or {})
        confirmation = arguments.pop(ARGUMENT_CONFIRMATION, None)
        classe = commande.classe_pour(arguments)
        debut = time.monotonic()
        identifiant = nouvel_identifiant()

        def refuser(motif: str) -> Reponse:
            self._journaliser(
                identifiant=identifiant, commande=commande, classe=classe, ctx=ctx,
                arguments=arguments, resultat=REFUSE, effet=None, debut=debut, motif=motif,
            )
            return Reponse(REFUSE, {"erreur": motif, "classe": classe}, identifiant)

        if classe == RESERVEE and not ctx.est_la_personne:
            return refuser(
                f"{nom} est une commande réservée : seule la personne la fait, dans "
                "l'Atelier. Proposez-la dans « À valider » ou ouvrez l'écran d'accord."
            )
        if classe == ENGAGEANTE and not ctx.confirme:
            if confirmation:
                if self._consommer_jeton(str(confirmation), nom, arguments, ctx) is None:
                    return refuser(
                        "jeton de confirmation invalide, expiré, déjà servi, ou donné pour "
                        "d'autres arguments : redemandez un aperçu"
                    )
            else:
                apercu = await self._apercu(commande, ctx, arguments)
                jeton = self._emettre_jeton(nom, arguments, ctx.acteur)
                self._journaliser(
                    identifiant=identifiant, commande=commande, classe=classe, ctx=ctx,
                    arguments=arguments, resultat=APERCU, effet=None, debut=debut,
                )
                return Reponse(
                    APERCU,
                    {
                        "confirmation_requise": True,
                        "commande": nom,
                        "classe": classe,
                        "apercu": apercu,
                        ARGUMENT_CONFIRMATION: jeton,
                        "expire_dans_s": JETON_DUREE_S,
                        "note": (
                            "Rien n'est fait. Montrez l'aperçu ; après le « Oui » de la "
                            "personne, rappelez la même commande avec les mêmes arguments "
                            "et `confirmation`."
                        ),
                    },
                    identifiant,
                )

        try:
            resultat = commande.executer(ctx, arguments)
            if inspect.isawaitable(resultat):
                resultat = await resultat
            effet: Effet = resultat
        except Refus as exc:
            return refuser(str(exc))
        except ErreurDeCommande as exc:
            self._journaliser(
                identifiant=identifiant, commande=commande, classe=classe, ctx=ctx,
                arguments=arguments, resultat=ERREUR, effet=None, debut=debut,
                motif=str(exc.charge)[:300],
            )
            charge = exc.charge if isinstance(exc.charge, dict) else {"erreur": exc.charge}
            return Reponse(ERREUR, charge, identifiant)
        except Exception as exc:  # noqa: BLE001
            log.exception("commande %s", nom)
            motif = f"{type(exc).__name__}: {exc}"
            self._journaliser(
                identifiant=identifiant, commande=commande, classe=classe, ctx=ctx,
                arguments=arguments, resultat=ERREUR, effet=None, debut=debut, motif=motif,
            )
            return Reponse(ERREUR, {"erreur": motif}, identifiant)

        if classe == LECTURE:
            # Une lecture ne change rien : elle n'a ni carte ni ligne au journal
            # (un `atelier_suivre` toutes les trente secondes le noierait).
            return Reponse(FAIT, effet.charge)

        self._journaliser(
            identifiant=identifiant, commande=commande, classe=classe, ctx=ctx,
            arguments=arguments, resultat=FAIT, effet=effet, debut=debut,
        )
        carte = self._carte(identifiant, commande, ctx, effet)
        charge = dict(effet.charge) if isinstance(effet.charge, dict) else {"resultat": effet.charge}
        charge["carte"] = carte
        for rappel in list(self.apres_commande):
            try:
                rappel(nom, charge)
            except Exception:  # noqa: BLE001
                log.exception("rappel après %s", nom)
        return Reponse(FAIT, charge, identifiant)

    async def confirmer(self, jeton: str, ctx: Contexte) -> Reponse:
        """Exécute l'aperçu qu'un jeton désigne (le « Oui » de l'interface)."""
        with self._verrou:
            trouve = self._jetons.get(jeton)
        if trouve is None:
            return Reponse(REFUSE, {"erreur": "jeton inconnu ou expiré"})
        arguments = dict(trouve.arguments)
        arguments[ARGUMENT_CONFIRMATION] = jeton
        return await self.executer(trouve.nom, arguments, ctx)


def contexte_interface(acteur: str = "personne") -> Contexte:
    return Contexte(acteur=acteur, origine=ORIGINE_INTERFACE)


__all__ = [
    "APERCU",
    "ARGUMENT_CONFIRMATION",
    "Catalogue",
    "DeclarationOutil",
    "ERREUR",
    "ErreurDeCommande",
    "FAIT",
    "REFUSE",
    "Reponse",
    "contexte_interface",
]
