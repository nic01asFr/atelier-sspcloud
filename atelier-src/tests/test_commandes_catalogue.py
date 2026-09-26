"""Le catalogue de commandes : la classe vérifiée par le serveur, chaque appel journalisé.

Ce qui est éprouvé ici est le comportement, pas la déclaration : une commande
réservée appelée par un modèle ne fait rien, y compris par `gateway_call_tool` ;
une engageante rend un aperçu et n'agit qu'avec un jeton valable pour elle ;
le journal porte l'acteur et aucune valeur secrète.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from mcp_gateway.atelier.commandes.catalogue import APERCU, FAIT, REFUSE, Catalogue, contexte_interface
from mcp_gateway.atelier.commandes.journal import Evenement, Journal, REMPLACEMENT
from mcp_gateway.atelier.commandes.modele import (
    ENGAGEANTE,
    ORIGINE_MCP,
    RESERVEE,
    REVERSIBLE,
    Commande,
    Contexte,
    Effet,
)
from mcp_gateway.atelier.outils_conversation import CONVERSATION_APPELANTE
from mcp_gateway.mcp.gateway import McpGateway


def _executer(coroutine: Any) -> Any:
    return asyncio.run(coroutine)


def _charge(reponse_mcp: dict[str, Any]) -> Any:
    return json.loads(reponse_mcp["content"][0]["text"])


class _Compteur:
    def __init__(self) -> None:
        self.appels: list[dict[str, Any]] = []

    def __call__(self, ctx: Contexte, args: dict[str, Any]) -> Effet:
        self.appels.append(dict(args))
        return Effet(
            charge={"fait": True, "valeur": args.get("valeur")},
            objet_id="essai",
            titre="Essai fait",
            inverse_arguments={"valeur": args.get("valeur")},
        )


def _catalogue(tmp_path: Path) -> tuple[Catalogue, _Compteur, _Compteur]:
    catalogue = Catalogue(journal=Journal(tmp_path / "journal"))
    engageant, reserve = _Compteur(), _Compteur()
    catalogue.ajouter(
        Commande(
            nom="atelier_essai_engageant",
            description="essai",
            objet="essai",
            classe=ENGAGEANTE,
            executer=engageant,
            inverse="atelier_essai_engageant",
        )
    )
    catalogue.ajouter(
        Commande(
            nom="atelier_essai_reserve",
            description="essai",
            objet="essai",
            classe=RESERVEE,
            executer=reserve,
            exposee_mcp=False,
        )
    )
    return catalogue, engageant, reserve


def _modele(acteur: str = "conversation:c1") -> Contexte:
    return Contexte(acteur=acteur, origine=ORIGINE_MCP)


# ── Réservée ───────────────────────────────────────────────────────────


def test_une_commande_reservee_ne_fait_rien_pour_un_modele(tmp_path: Path) -> None:
    catalogue, _, reserve = _catalogue(tmp_path)
    reponse = _executer(catalogue.appeler("atelier_essai_reserve", {"valeur": 1}))
    assert reponse["isError"] is True
    assert "réservée" in _charge(reponse)["erreur"]
    assert reserve.appels == []
    refus = catalogue.journal.lire(commande="atelier_essai_reserve")
    assert refus and refus[0]["resultat"] == REFUSE


def test_une_commande_reservee_passe_pour_la_personne(tmp_path: Path) -> None:
    catalogue, _, reserve = _catalogue(tmp_path)
    reponse = _executer(catalogue.executer("atelier_essai_reserve", {"valeur": 2}, contexte_interface()))
    assert reponse.statut == FAIT
    assert reserve.appels == [{"valeur": 2}]


class _Rien:
    """Ce que la passerelle attend d'un catalogue, d'un pool et de sessions : rien ici."""

    db = None
    bundles: dict[str, Any] = {}

    def get(self, *_: Any) -> None:
        return None


def test_gateway_call_tool_ne_contourne_pas_la_classe(tmp_path: Path) -> None:
    """Le méta-outil repasse par `tools_call` : la même porte, la même vérification."""
    catalogue, _, reserve = _catalogue(tmp_path)
    passerelle = McpGateway(_Rien(), _Rien(), _Rien(), None, outils_locaux=catalogue)  # type: ignore[arg-type]
    reponse = _executer(
        passerelle.tools_call(
            "gateway_call_tool",
            {"name": "atelier_essai_reserve", "arguments": {"valeur": 3}},
            "session-essai",
        )
    )
    assert reponse["isError"] is True
    assert reserve.appels == []
    ligne = catalogue.journal.lire(commande="atelier_essai_reserve")[0]
    assert ligne["action"]["via"] == "gateway_call_tool"
    assert ligne["resultat"] == REFUSE


def test_une_commande_non_exposee_reste_appelable_par_son_nom_et_refusee(tmp_path: Path) -> None:
    catalogue, _, _ = _catalogue(tmp_path)
    noms = {d["name"] for d in catalogue.definitions()}
    assert "atelier_essai_reserve" not in noms
    assert _executer(catalogue.appeler("atelier_essai_reserve", {}))["isError"] is True


# ── Engageante ─────────────────────────────────────────────────────────


def test_une_commande_engageante_rend_un_apercu_sans_agir(tmp_path: Path) -> None:
    catalogue, engageant, _ = _catalogue(tmp_path)
    reponse = _executer(catalogue.executer("atelier_essai_engageant", {"valeur": 5}, _modele()))
    assert reponse.statut == APERCU
    assert reponse.charge["confirmation_requise"] is True
    assert reponse.charge["confirmation"]
    assert engageant.appels == []


def test_un_apercu_qui_refuse_rend_un_refus_sans_jeton(tmp_path: Path) -> None:
    from mcp_gateway.atelier.commandes.modele import Refus

    catalogue = Catalogue(journal=Journal(tmp_path / "journal"))
    fait = _Compteur()

    def apercu(ctx: Contexte, args: dict[str, Any]) -> dict[str, Any]:
        raise Refus("valeur interdite")

    catalogue.ajouter(
        Commande(nom="atelier_essai_apercu", description="essai", objet="essai", classe=ENGAGEANTE,
                 executer=fait, apercu=apercu)
    )
    modele = Contexte(acteur="conversation:c1", origine=ORIGINE_MCP)
    reponse = _executer(catalogue.executer("atelier_essai_apercu", {"valeur": 1}, modele))
    assert reponse.statut == REFUSE and reponse.charge["erreur"] == "valeur interdite"
    assert "confirmation" not in reponse.charge and not catalogue._jetons  # noqa: SLF001
    assert not fait.appels
    assert catalogue.journal.lire(commande="atelier_essai_apercu")[0]["resultat"] == "refus"


def test_le_jeton_ne_vaut_qu_une_fois_et_pour_les_memes_arguments(tmp_path: Path) -> None:
    catalogue, engageant, _ = _catalogue(tmp_path)
    jeton = _executer(catalogue.executer("atelier_essai_engageant", {"valeur": 5}, _modele())).charge[
        "confirmation"
    ]
    autre = _executer(
        catalogue.executer("atelier_essai_engageant", {"valeur": 6, "confirmation": jeton}, _modele())
    )
    assert autre.statut == REFUSE and engageant.appels == []

    jeton = _executer(catalogue.executer("atelier_essai_engageant", {"valeur": 5}, _modele())).charge[
        "confirmation"
    ]
    fait = _executer(
        catalogue.executer("atelier_essai_engageant", {"valeur": 5, "confirmation": jeton}, _modele())
    )
    assert fait.statut == FAIT and engageant.appels == [{"valeur": 5}]
    rejoue = _executer(
        catalogue.executer("atelier_essai_engageant", {"valeur": 5, "confirmation": jeton}, _modele())
    )
    assert rejoue.statut == REFUSE and len(engageant.appels) == 1


def test_un_autre_modele_ne_confirme_pas_l_apercu_d_un_autre(tmp_path: Path) -> None:
    catalogue, engageant, _ = _catalogue(tmp_path)
    jeton = _executer(catalogue.executer("atelier_essai_engageant", {"valeur": 1}, _modele("conversation:a"))).charge[
        "confirmation"
    ]
    reponse = _executer(
        catalogue.executer("atelier_essai_engageant", {"valeur": 1, "confirmation": jeton}, _modele("conversation:b"))
    )
    assert reponse.statut == REFUSE and engageant.appels == []


def test_la_personne_confirme_l_apercu_montre_a_un_agent(tmp_path: Path) -> None:
    catalogue, engageant, _ = _catalogue(tmp_path)
    jeton = _executer(catalogue.executer("atelier_essai_engageant", {"valeur": 9}, _modele())).charge[
        "confirmation"
    ]
    reponse = _executer(catalogue.confirmer(jeton, contexte_interface()))
    assert reponse.statut == FAIT and engageant.appels == [{"valeur": 9}]
    assert catalogue.journal.lire(commande="atelier_essai_engageant")[0]["acteur"] == "personne"


def test_l_engageante_annonce_sa_confirmation_dans_son_schema(tmp_path: Path) -> None:
    catalogue, _, _ = _catalogue(tmp_path)
    definition = next(d for d in catalogue.definitions() if d["name"] == "atelier_essai_engageant")
    assert "confirmation" in definition["inputSchema"]["properties"]
    assert definition["_meta"]["atelier/commande"]["classe"] == ENGAGEANTE


# ── Carte, journal, acteur ─────────────────────────────────────────────


def test_une_commande_reversible_rend_sa_carte_et_journalise_son_acteur(tmp_path: Path) -> None:
    catalogue = Catalogue(journal=Journal(tmp_path / "journal"))
    catalogue.ajouter(
        Commande(
            nom="atelier_essai",
            description="essai",
            objet="essai",
            classe=REVERSIBLE,
            inverse="atelier_essai",
            executer=_Compteur(),
        )
    )
    jeton = CONVERSATION_APPELANTE.set("c-42")
    try:
        reponse = _executer(catalogue.appeler("atelier_essai", {"valeur": 1}))
    finally:
        CONVERSATION_APPELANTE.reset(jeton)
    carte = _charge(reponse)["carte"]
    assert carte["titre"] == "Essai fait"
    assert carte["annuler"]["commande"] == "atelier_annuler"
    ligne = catalogue.journal.lire()[0]
    assert ligne["acteur"] == "conversation:c-42"
    assert ligne["id"] == carte["action"]
    assert ligne["action"]["inverse"] == {"commande": "atelier_essai", "arguments": {"valeur": 1}}
    assert set(ligne) >= {"quand", "source", "acteur", "objet", "action", "resultat", "cout", "empreinte"}


def test_le_journal_n_ecrit_aucun_secret(tmp_path: Path) -> None:
    secret = "sk-valeur-secrete-0123456789"
    journal = Journal(tmp_path / "journal", secrets=lambda: [secret])
    journal.ecrire(
        Evenement(
            source="commande",
            acteur="personne",
            objet={"type": "essai", "id": "x"},
            action={
                "arguments": {"authorization": "Bearer abc", "api_key": "k", "message": f"voici {secret} ici"},
                "avant": None,
                "apres": {"article": "garde"},
            },
            resultat="fait",
        )
    )
    brut = next((tmp_path / "journal").glob("*.jsonl")).read_text(encoding="utf-8")
    assert secret not in brut and "Bearer abc" not in brut
    ligne = json.loads(brut)
    assert ligne["action"]["arguments"]["authorization"] == REMPLACEMENT
    assert ligne["action"]["arguments"]["api_key"] == REMPLACEMENT
    assert ligne["action"]["apres"]["article"] == "garde"


def test_une_source_inconnue_est_refusee(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        Journal(tmp_path).ecrire(Evenement(source="n-importe", acteur="x", objet={}, action={}, resultat="fait"))


# ── Les outils atelier_* d'avant ───────────────────────────────────────


class _OutilsFactices:
    def __init__(self) -> None:
        self.appels: list[str] = []

    def definitions(self) -> list[dict[str, Any]]:
        return [
            {"name": "atelier_projets", "description": "d", "inputSchema": {"type": "object"}},
            {"name": "atelier_nouveau_venu", "description": "d", "inputSchema": {"type": "object"}},
        ]

    async def appeler(self, nom: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.appels.append(nom)
        return {"content": [{"type": "text", "text": json.dumps({"ok": nom})}], "isError": False}


def test_les_outils_existants_gardent_leur_nom_et_prennent_une_classe(tmp_path: Path) -> None:
    from mcp_gateway.atelier.commandes.existants import declarer_les_existants

    outils = _OutilsFactices()
    catalogue = Catalogue(journal=Journal(tmp_path / "journal"), outils=outils)
    declarer_les_existants(catalogue)
    noms = {d["name"] for d in catalogue.definitions()}
    assert {"atelier_projets", "atelier_nouveau_venu"} <= noms
    # Une lecture : pas de carte, pas de ligne au journal, charge inchangée.
    assert _charge(_executer(catalogue.appeler("atelier_projets", {}))) == {"ok": "atelier_projets"}
    assert catalogue.journal.lire() == []
    # Un outil que personne n'a déclaré passe, et le journal le dit.
    _executer(catalogue.appeler("atelier_nouveau_venu", {}))
    assert catalogue.journal.lire()[0]["objet"]["type"] == "non_declare"


def test_decider_refuse_sans_confirmation_mais_n_accorde_pas_seul() -> None:
    from mcp_gateway.atelier.commandes.existants import _decider_allegement

    assert _decider_allegement({"decision": "deny"}) == REVERSIBLE
    assert _decider_allegement({"decision": "allow"}) == ENGAGEANTE


def test_les_creations_se_decrivent_dans_les_mots_de_l_interface(tmp_path: Path) -> None:
    """« Créations » envoyait le modèle vers les compositions (0 sur 6, mesuré)."""
    from mcp_gateway.atelier.commandes.existants import declarer_les_existants

    class _Artefacts(_OutilsFactices):
        def definitions(self) -> list[dict[str, Any]]:
            return [{"name": "atelier_artefacts", "description": "Les artefacts", "inputSchema": {}}]

    catalogue = Catalogue(journal=Journal(tmp_path / "journal"), outils=_Artefacts())
    declarer_les_existants(catalogue)
    description = catalogue.definitions()[0]["description"].lower()
    for mot in ("création", "page", "application", "ce que j'ai fabriqué", "pas une composition"):
        assert mot in description


def test_le_service_monte_le_catalogue_et_l_expose(atelier) -> None:  # noqa: ANN001
    catalogue = atelier.app.state.commandes
    noms = {d["name"] for d in catalogue.definitions()}
    for nom in ("atelier_projets", "atelier_ouvrir", "atelier_envoyer", "atelier_decider",
                "atelier_projet_creer", "atelier_projet_modifier", "atelier_a_valider", "atelier_annuler"):
        assert nom in noms
    assert "atelier_a_valider_accepter" not in noms
    declarations = {c["nom"]: c for c in catalogue.declarations()}
    assert declarations["atelier_a_valider_accepter"]["classe"] == RESERVEE
    for c in declarations.values():
        assert c["classe"] in ("lecture", "reversible", "engageante", "reservee")
        if c["inverse"]:
            assert c["inverse"] in declarations, f"{c['nom']} : inverse inconnue {c['inverse']}"
