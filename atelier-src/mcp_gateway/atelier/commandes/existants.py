"""Les outils `atelier_*` d'avant le catalogue, déclarés comme commandes.

Leur code reste dans `outils_conversation.py` ; leur nom ne change pas. Ce
module ne dit que ce que le catalogue exige : l'objet, la classe, l'inverse,
les règles et la carte rendue.
"""

from __future__ import annotations

from typing import Any

from mcp_gateway.atelier.commandes.catalogue import Catalogue, DeclarationOutil
from mcp_gateway.atelier.commandes.modele import ENGAGEANTE, LECTURE, REVERSIBLE, Effet


def _lien_conversation(projet: str, conversation: str) -> str:
    return f"/?slug={projet}&session={conversation}" if projet else f"/?session={conversation}"


def _carte_ouvrir(args: dict[str, Any], charge: Any) -> Effet:
    c = charge if isinstance(charge, dict) else {}
    ident, projet = str(c.get("id") or ""), str(c.get("projet") or args.get("projet") or "")
    return Effet(
        charge=charge,
        objet_id=ident,
        titre="Conversation ouverte",
        resume=f"« {c.get('titre') or ident} » dans {projet}",
        voir=_lien_conversation(projet, ident),
        preuve={"conversation": ident, "etat": c.get("etat")},
        apres={"conversation": ident, "projet": projet},
        inverse_arguments={"conversation": ident} if ident else None,
    )


def _carte_envoyer(args: dict[str, Any], charge: Any) -> Effet:
    c = charge if isinstance(charge, dict) else {}
    ident = str(c.get("conversation") or args.get("conversation") or "")
    return Effet(
        charge=charge,
        objet_id=ident,
        titre="Tour lancé",
        resume=f"mode {c.get('mode')}, en cours",
        voir=_lien_conversation("", ident),
        preuve={"etat": c.get("etat"), "curseur": c.get("curseur")},
        inverse_arguments={"conversation": ident} if ident else None,
    )


def _carte_interrompre(args: dict[str, Any], charge: Any) -> Effet:
    c = charge if isinstance(charge, dict) else {}
    ident = str(c.get("conversation") or args.get("conversation") or "")
    return Effet(
        charge=charge,
        objet_id=ident,
        titre="Tour arrêté",
        resume="Ce qui est écrit reste écrit.",
        voir=_lien_conversation("", ident),
        preuve={"etat": c.get("etat")},
    )


def _carte_decider(args: dict[str, Any], charge: Any) -> Effet:
    c = charge if isinstance(charge, dict) else {}
    return Effet(
        charge=charge,
        objet_id=str(c.get("demande") or args.get("demande") or ""),
        titre="Autorisation accordée" if c.get("decision") == "allow" else "Autorisation refusée",
        resume="tour repris" if c.get("tour_repris") else "plus aucun tour n'attendait",
        preuve={"tour_repris": c.get("tour_repris"), "regles_retenues": len(c.get("regles_retenues") or [])},
        apres={"decision": c.get("decision")},
    )


def _artefact(args: dict[str, Any], charge: Any) -> tuple[str, str, dict[str, Any]]:
    c = charge if isinstance(charge, dict) else {}
    projet = str(c.get("slug") or args.get("projet") or "")
    nom = str(c.get("nom") or args.get("nom") or "")
    return projet, nom, c


def _carte_artefact_creer(args: dict[str, Any], charge: Any) -> Effet:
    projet, nom, c = _artefact(args, charge)
    return Effet(
        charge=charge,
        objet_id=f"{projet}/{nom}",
        titre="Création posée",
        resume=f"artifacts/{nom}/ dans {projet} ({c.get('mode')})",
        voir=str(c.get("url") or ""),
        preuve={"mode": c.get("mode"), "etat": c.get("etat")},
        apres={"mode": c.get("mode")},
    )


def _carte_artefact_bascule(titre: str):
    def carte(args: dict[str, Any], charge: Any) -> Effet:
        projet, nom, c = _artefact(args, charge)
        return Effet(
            charge=charge,
            objet_id=f"{projet}/{nom}",
            titre=titre,
            resume=f"{nom} ({projet}) : {c.get('etat')}",
            voir=str(c.get("url") or ""),
            preuve={"etat": c.get("etat"), "port": c.get("port")},
            apres={"etat": c.get("etat")},
            inverse_arguments={"projet": projet, "nom": nom},
        )

    return carte


def _decider_allegement(args: dict[str, Any]) -> str:
    """Un refus n'engage rien (A-5 : l'Assistant refuse seul, n'accepte jamais seul)."""
    return REVERSIBLE if str(args.get("decision") or "").strip().lower() == "deny" else ENGAGEANTE


def _decider_allegement_du_lanceur(catalogue: Any):
    """Comme `_decider_allegement`, et une autorisation de lanceur supervisé dans son périmètre passe seule.

    Seule exception à A-5 : la personne a dit « Oui » à un lancement supervisé,
    et l'Atelier tient le périmètre (`perimetre_du_lanceur.py`). Hors périmètre,
    ou pour une règle « toujours », l'autorisation reste engageante.
    """

    def allegement(args: dict[str, Any]) -> str:
        base = _decider_allegement(args)
        if base != ENGAGEANTE:
            return base
        outils = getattr(catalogue, "outils", None)
        if outils is None:
            return ENGAGEANTE
        try:
            return REVERSIBLE if outils.decision_du_lanceur_sans_confirmation(args) else ENGAGEANTE
        except Exception:  # noqa: BLE001 — dans le doute, la classe déclarée
            return ENGAGEANTE

    return allegement


# Le mot « création » de l'interface envoyait le modèle vers les compositions
# (mesuré : 0 sur 6, `docs/archives/vision/mesures-vague1.md`). Les descriptions de la
# famille des artefacts portent donc les mots que la personne emploie, et
# disent ce qu'une composition n'est pas.
_PAS_UNE_COMPOSITION = (
    " Ce n'est pas une composition : une composition est un enchaînement d'outils de la "
    "passerelle (gateway_*_composition), sans page ni adresse."
)
DESCRIPTIONS = {
    "atelier_artefacts": (
        "Les créations d'un projet : ce que la personne a fabriqué, ses pages et ses "
        "applications (« mes créations », « ce que j'ai fabriqué », « ma page », « mon "
        "application »). Chaque création est un dossier artifacts/<nom>/ servi à une adresse "
        "sur l'hôte des applications. Rend nom, mode (autonome : page en fichiers ; serveur : "
        "application avec un processus), état, adresse, auteur." + _PAS_UNE_COMPOSITION
    ),
    "atelier_artefact_creer": (
        "Crée une nouvelle création (page ou application) : le dossier artifacts/<nom>/, d'un "
        "seul geste, en refusant un nom déjà pris. `mode` : autonome (une page en fichiers, "
        "défaut) ou serveur (une application : un artefact.json à compléter, commande avec "
        "{port}, sante, protocoles)." + _PAS_UNE_COMPOSITION
    ),
    "atelier_artefact_demarrer": (
        "Démarre une création en mode serveur (une application) et attend qu'elle réponde "
        "(`attendre`, défaut vrai). L'Atelier choisit le port. Refusé sur la création d'une "
        "autre conversation sans `forcer`." + _PAS_UNE_COMPOSITION
    ),
    "atelier_artefact_arreter": (
        "Arrête une création en mode serveur (une application) : son groupe de processus "
        "entier." + _PAS_UNE_COMPOSITION
    ),
    "atelier_artefact_journal": (
        "Les dernières lignes du journal d'une création en mode serveur (une application), "
        "200 par défaut."
    ),
    "atelier_artefact_verifier": (
        "Vérifie les créations d'un projet (pages et applications, artefact.json) sans rien "
        "lancer : ce qui est valide, ce qui ne l'est pas et pourquoi. Avec `nom`, dit aussi si "
        "la création tourne et répond." + _PAS_UNE_COMPOSITION
    ),
}


def declarer_les_existants(catalogue: Catalogue) -> None:
    def d(nom: str, declaration: DeclarationOutil) -> None:
        if nom in DESCRIPTIONS and declaration.description is None:
            declaration.description = DESCRIPTIONS[nom]
        catalogue.declarer_outil(nom, declaration)

    d("atelier_projets", DeclarationOutil(objet="projet", classe=LECTURE))
    d("atelier_conversations", DeclarationOutil(objet="conversation", classe=LECTURE))
    d("atelier_suivre", DeclarationOutil(objet="conversation", classe=LECTURE))
    d("atelier_transcript", DeclarationOutil(objet="conversation", classe=LECTURE))
    d("atelier_artefacts", DeclarationOutil(objet="artefact", classe=LECTURE))
    d("atelier_artefact_journal", DeclarationOutil(objet="artefact", classe=LECTURE))
    d("atelier_artefact_verifier", DeclarationOutil(objet="artefact", classe=LECTURE))
    d(
        "atelier_ouvrir",
        DeclarationOutil(
            objet="conversation",
            classe=REVERSIBLE,
            inverse="atelier_conversation_ranger",
            regles=["refuse un projet inconnu ou rangé", "la conversation s'affiche dans l'interface"],
            carte=_carte_ouvrir,
        ),
    )
    d(
        "atelier_envoyer",
        DeclarationOutil(
            objet="conversation",
            classe=REVERSIBLE,
            inverse="atelier_interrompre",
            regles=["rend la main aussitôt", "bypassPermissions seulement s'il est déjà accordé"],
            carte=_carte_envoyer,
        ),
    )
    d(
        "atelier_interrompre",
        DeclarationOutil(
            objet="conversation",
            classe=REVERSIBLE,
            regles=["sans inverse : arrêter ne défait rien de ce qui a été écrit"],
            carte=_carte_interrompre,
        ),
    )
    d(
        "atelier_decider",
        DeclarationOutil(
            objet="autorisation",
            classe=ENGAGEANTE,
            regles=["un refus passe sans confirmation ; une autorisation demande le « Oui »"],
            carte=_carte_decider,
            allegement=_decider_allegement_du_lanceur(catalogue),
        ),
    )
    d(
        "atelier_artefact_creer",
        DeclarationOutil(
            objet="artefact",
            classe=REVERSIBLE,
            regles=["un nom déjà pris rend l'artefact existant (existe_deja), sans écrire"],
            carte=_carte_artefact_creer,
        ),
    )
    d(
        "atelier_artefact_demarrer",
        DeclarationOutil(
            objet="artefact",
            classe=REVERSIBLE,
            inverse="atelier_artefact_arreter",
            regles=["refusé sur l'artefact d'une autre conversation sans forcer"],
            carte=_carte_artefact_bascule("Création démarrée"),
        ),
    )
    d(
        "atelier_artefact_arreter",
        DeclarationOutil(
            objet="artefact",
            classe=REVERSIBLE,
            inverse="atelier_artefact_demarrer",
            regles=["arrête le groupe de processus entier"],
            carte=_carte_artefact_bascule("Création arrêtée"),
        ),
    )
    # Outils attendus de l'équipe P (panneau) : déclarés d'avance pour qu'ils
    # naissent avec leur classe. Absents, ils ne sont pas annoncés.
    d("atelier_montrer", DeclarationOutil(objet="vue", classe=LECTURE))
    d(
        "atelier_navigateur_ouvrir",
        DeclarationOutil(
            objet="acces",
            classe=REVERSIBLE,
            regles=["code de passage d'agent borné au projet, jamais le cookie de l'Atelier"],
        ),
    )


__all__ = ["declarer_les_existants"]
