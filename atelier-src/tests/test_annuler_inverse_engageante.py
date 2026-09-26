"""`atelier_annuler` applique une inverse engageante quand l'auteur défait son propre geste.

Le « Oui » donné à l'action vaut pour son inverse : l'inverse s'exécute sans
nouvel aperçu, avec le même acteur, et son journal dit par où elle est passée
(`via: atelier_annuler:<action>`). Un autre modèle, lui, retombe sur l'aperçu ;
une inverse réservée reste refusée à tout modèle.
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp_gateway.atelier.commandes.catalogue import FAIT, REFUSE, contexte_interface
from mcp_gateway.atelier.commandes.modele import (
    ENGAGEANTE,
    ORIGINE_MCP,
    RESERVEE,
    REVERSIBLE,
    Commande,
    Contexte,
    Effet,
)


class _Etat:
    def __init__(self) -> None:
        self.valeur = "avant"
        self.appels: list[tuple[str, str]] = []


def _inscrire(atelier: Any, classe_inverse: str) -> _Etat:
    etat = _Etat()
    catalogue = atelier.app.state.commandes

    def poser(ctx: Contexte, args: dict[str, Any]) -> Effet:
        avant, etat.valeur = etat.valeur, str(args["valeur"])
        etat.appels.append(("poser", ctx.acteur))
        return Effet(charge={"valeur": etat.valeur}, objet_id="essai", inverse_arguments={"valeur": avant})

    def remettre(ctx: Contexte, args: dict[str, Any]) -> Effet:
        avant, etat.valeur = etat.valeur, str(args["valeur"])
        etat.appels.append(("remettre", ctx.acteur))
        return Effet(charge={"valeur": etat.valeur}, objet_id="essai", inverse_arguments={"valeur": avant})

    catalogue.ajouter(
        Commande(nom="atelier_essai_poser", description="essai", objet="essai", classe=REVERSIBLE,
                 executer=poser, inverse="atelier_essai_remettre")
    )
    catalogue.ajouter(
        Commande(nom="atelier_essai_remettre", description="essai", objet="essai", classe=classe_inverse,
                 executer=remettre, inverse="atelier_essai_poser")
    )
    return etat


def _modele(nom: str = "c1") -> Contexte:
    return Contexte(acteur=f"conversation:{nom}", origine=ORIGINE_MCP)


def _executer(atelier: Any, nom: str, arguments: dict[str, Any], ctx: Contexte) -> Any:
    return asyncio.run(atelier.app.state.commandes.executer(nom, arguments, ctx))


def test_l_auteur_annule_sans_nouvel_accord_et_le_journal_le_dit(atelier: Any) -> None:
    etat = _inscrire(atelier, ENGAGEANTE)
    pose = _executer(atelier, "atelier_essai_poser", {"valeur": "apres"}, _modele())
    annule = _executer(atelier, "atelier_annuler", {"action": pose.action}, _modele())
    assert annule.statut == FAIT, annule.charge
    assert etat.valeur == "avant"
    assert etat.appels[-1] == ("remettre", "conversation:c1")
    assert annule.charge["carte"]["preuve"]["consentement_de_l_action"] is True
    ligne = atelier.app.state.commandes.journal.lire(commande="atelier_essai_remettre", limite=5)
    assert [l["resultat"] for l in ligne] == ["fait"], "pas d'aperçu intermédiaire"
    assert ligne[0]["acteur"] == "conversation:c1"
    assert ligne[0]["action"]["classe"] == "engageante"
    assert ligne[0]["action"]["via"] == f"atelier_annuler:{pose.action}"


def test_un_autre_modele_n_annule_pas_sans_accord(atelier: Any) -> None:
    etat = _inscrire(atelier, ENGAGEANTE)
    pose = _executer(atelier, "atelier_essai_poser", {"valeur": "apres"}, _modele("c1"))
    refus = _executer(atelier, "atelier_annuler", {"action": pose.action}, _modele("c2"))
    assert refus.statut == REFUSE
    assert etat.valeur == "apres"
    assert atelier.app.state.commandes.journal.lire(commande="atelier_essai_remettre", limite=1)[0]["resultat"] == "apercu"


def test_la_personne_annule_le_geste_d_un_modele(atelier: Any) -> None:
    etat = _inscrire(atelier, ENGAGEANTE)
    pose = _executer(atelier, "atelier_essai_poser", {"valeur": "apres"}, _modele("c1"))
    annule = _executer(atelier, "atelier_annuler", {"action": pose.action}, contexte_interface())
    assert annule.statut == FAIT, annule.charge
    assert etat.valeur == "avant" and etat.appels[-1] == ("remettre", "personne")


def test_une_inverse_reservee_reste_refusee_a_un_modele(atelier: Any) -> None:
    etat = _inscrire(atelier, RESERVEE)
    pose = _executer(atelier, "atelier_essai_poser", {"valeur": "apres"}, _modele())
    refus = _executer(atelier, "atelier_annuler", {"action": pose.action}, _modele())
    assert refus.statut == REFUSE and "réservée" in refus.charge["erreur"]
    assert etat.valeur == "apres"
    fait = _executer(atelier, "atelier_annuler", {"action": pose.action}, contexte_interface())
    assert fait.statut == FAIT and etat.valeur == "avant"
