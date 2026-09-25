"""La file « À valider » : une porte d'entrée, la personne seule accepte.

Couvre le dépôt (et son dédoublonnage), la lecture par l'API, le refus par un
modèle (permis), l'acceptation par un modèle (refusée : A-5) ou par la clé du
propriétaire (refusée aussi : les agents la lisent), l'acceptation par la
personne qui exécute l'action proposée, et le branchement sur le pilote de
wikichat sans recopie.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from mcp_gateway.atelier.commandes.a_valider import (
    ACCEPTEE,
    EN_ATTENTE,
    REFUSEE,
    ErreurAValider,
    FileAValider,
    propositions_du_pilote,
)
from mcp_gateway.atelier.commandes.catalogue import FAIT, REFUSE, Catalogue, contexte_interface
from mcp_gateway.atelier.commandes.journal import Journal
from mcp_gateway.atelier.commandes.modele import ORIGINE_MCP, Contexte
from mcp_gateway.atelier.commandes.natives import Services, inscrire_les_natives


def _modele() -> Contexte:
    return Contexte(acteur="conversation:assistant", origine=ORIGINE_MCP)


def test_deposer_dedoublonne_une_meme_empreinte(tmp_path: Path) -> None:
    file = FileAValider(tmp_path / "av")
    a = file.deposer("gardien", "Port 0.0.0.0 ouvert", "vu sur :9000", empreinte="port-9000")
    b = file.deposer("gardien", "Port 0.0.0.0 ouvert", "revu", empreinte="port-9000")
    assert a.id == b.id and b.occurrences == 2
    c = file.deposer("agent", "Port 0.0.0.0 ouvert", empreinte="port-9000")
    assert c.id != a.id
    # Un autre processus (l'exécuteur des gardiens) lit la même file.
    assert {p.id for p in FileAValider(tmp_path / "av").lister()} == {a.id, c.id}


@pytest.mark.parametrize(
    "source,titre,action",
    [("inconnue", "t", None), ("gardien", " ", None), ("gardien", "t", {"commande": "rm -rf"})],
)
def test_deposer_refuse_ce_qui_est_mal_forme(tmp_path: Path, source: str, titre: str, action: Any) -> None:
    with pytest.raises(ErreurAValider):
        FileAValider(tmp_path).deposer(source, titre, action=action)


class _Projets:
    def __init__(self) -> None:
        self.ranges: list[str] = []

    def patch(self, slug: str, *, archived: bool | None = None, title: str | None = None) -> None:
        self.ranges.append(slug)

    def list_projects(self, include_archived: bool = False) -> list[Any]:
        return []


class _Reglages:
    def __init__(self, racine: Path) -> None:
        self.projects_dir = racine / "projects"
        self.assistant_slug = "wikichat-memory"
        (self.projects_dir / "carte").mkdir(parents=True)


def _catalogue(tmp_path: Path, **pilote: Any) -> tuple[Catalogue, FileAValider, _Projets]:
    journal = Journal(tmp_path / "journal")
    file = FileAValider(tmp_path / "av", journal=journal)
    catalogue = Catalogue(journal=journal)
    projets = _Projets()
    inscrire_les_natives(
        catalogue,
        Services(settings=_Reglages(tmp_path), projects=projets, sessions=None, file=file, **pilote),
    )
    return catalogue, file, projets


def test_un_modele_refuse_seul_mais_n_accepte_jamais(tmp_path: Path) -> None:
    catalogue, file, projets = _catalogue(tmp_path)
    p = file.deposer(
        "gardien", "Ranger la carte", action={"commande": "atelier_projet_ranger", "arguments": {"projet": "carte"}}
    )
    accepte = asyncio.run(catalogue.executer("atelier_a_valider_accepter", {"id": p.id}, _modele()))
    assert accepte.statut == REFUSE and projets.ranges == []
    assert file.lire(p.id).statut == EN_ATTENTE

    refuse = asyncio.run(catalogue.executer("atelier_a_valider_refuser", {"id": p.id, "motif": "pas maintenant"}, _modele()))
    assert refuse.statut == FAIT and file.lire(p.id).statut == REFUSEE
    assert file.lire(p.id).decision["par"] == "conversation:assistant"

    # Le refus s'annule : la proposition attend de nouveau.
    annule = asyncio.run(catalogue.executer("atelier_annuler", {"action": refuse.charge["carte"]["action"]}, _modele()))
    assert annule.statut == FAIT and file.lire(p.id).statut == EN_ATTENTE


def test_la_personne_accepte_et_l_action_proposee_s_execute(tmp_path: Path) -> None:
    catalogue, file, projets = _catalogue(tmp_path)
    p = file.deposer(
        "agent", "Ranger la carte", action={"commande": "atelier_projet_ranger", "arguments": {"projet": "carte"}}
    )
    reponse = asyncio.run(catalogue.executer("atelier_a_valider_accepter", {"id": p.id}, contexte_interface()))
    assert reponse.statut == FAIT, reponse.charge
    assert projets.ranges == ["carte"]
    tranchee = file.lire(p.id)
    assert tranchee.statut == ACCEPTEE and tranchee.decision["resultat"]["carte"]["titre"] == "Projet rangé"
    # L'action exécutée a sa propre ligne au journal, avec la personne pour acteur.
    ligne = catalogue.journal.lire(commande="atelier_projet_ranger")[0]
    assert ligne["acteur"] == "personne" and ligne["resultat"] == FAIT
    # Deux fois, non.
    again = asyncio.run(catalogue.executer("atelier_a_valider_accepter", {"id": p.id}, contexte_interface()))
    assert again.statut == REFUSE


DONNEES_PILOTE = {
    "agents": [
        {
            "id": "trig-1",
            "name": "Veille Grist",
            "queue": [{"id": "p0", "title": "Ajouter une ligne", "sub": "table Contacts", "kind": "action", "needs": []}],
        }
    ]
}


def test_les_propositions_du_pilote_sont_lues_sans_recopie(tmp_path: Path) -> None:
    decisions: list[tuple[str, str, str]] = []

    async def lire() -> Any:
        return DONNEES_PILOTE

    async def decider(agent: str, action: str, decision: str, complete: Any) -> Any:
        decisions.append((agent, action, decision))
        return {"ok": True, "persisted": True}

    catalogue, file, _ = _catalogue(tmp_path, pilote_lire=lire, pilote_decider=decider)
    liste = asyncio.run(catalogue.executer("atelier_a_valider", {}, _modele())).charge["propositions"]
    assert [p["id"] for p in liste] == ["pilote:trig-1:p0"]
    assert list((tmp_path / "av").glob("*.json")) == [], "rien n'est recopié dans la file"

    assert asyncio.run(catalogue.executer("atelier_a_valider_accepter", {"id": "pilote:trig-1:p0"}, _modele())).statut == REFUSE
    assert decisions == []
    fait = asyncio.run(catalogue.executer("atelier_a_valider_accepter", {"id": "pilote:trig-1:p0"}, contexte_interface()))
    assert fait.statut == FAIT and decisions == [("trig-1", "p0", "approve")]


def test_un_pilote_absent_ne_rend_pas_la_file_illisible(tmp_path: Path) -> None:
    async def lire() -> Any:
        raise ConnectionError("wikichat arrêté")

    catalogue, file, _ = _catalogue(tmp_path, pilote_lire=lire)
    file.deposer("memoire", "Retenir : préfère le vouvoiement")
    charge = asyncio.run(catalogue.executer("atelier_a_valider", {}, _modele())).charge
    assert charge["nombre"] == 1 and "indisponibles" in charge["note"]


def test_propositions_du_pilote_tolere_le_desordre() -> None:
    assert propositions_du_pilote(None) == []
    assert propositions_du_pilote({"agents": [{"id": "x", "queue": [None, {"id": "a", "title": "T"}]}]})[0]["titre"] == "T"


# ── Par l'API HTTP ──────────────────────────────────────────────────────


def test_l_api_depose_lit_et_ne_laisse_pas_la_cle_accepter(atelier, cle_du_proprietaire: str) -> None:  # noqa: ANN001
    entetes = {"Authorization": f"Bearer {cle_du_proprietaire}"}
    depot = atelier.post(
        "/v1/a-valider",
        headers=entetes,
        json={"source": "gardien", "titre": "Droits 0644 sur un secret", "empreinte": "droits-x"},
    )
    assert depot.status_code == 200, depot.text
    ident = depot.json()["proposition"]["id"]

    liste = atelier.get("/v1/a-valider", headers=entetes)
    assert liste.status_code == 200
    assert [p["id"] for p in liste.json()["resultat"]["propositions"]] == [ident]

    # La clé du propriétaire est aussi celle des agents : elle n'est pas la personne.
    accepte = atelier.post(f"/v1/a-valider/{ident}/decision", headers=entetes, json={"decision": "accepter"})
    assert accepte.status_code == 403
    refuse = atelier.post(f"/v1/a-valider/{ident}/decision", headers=entetes, json={"decision": "refuser", "motif": "vu"})
    assert refuse.status_code == 200 and refuse.json()["resultat"]["statut"] == REFUSEE

    journal = atelier.get("/v1/journal", headers=entetes, params={"objet": ident}).json()["evenements"]
    assert {e["action"].get("commande") or e["action"].get("geste") for e in journal} >= {
        "atelier_a_valider_accepter",
        "atelier_a_valider_refuser",
    }


def test_l_api_sans_cle_est_fermee(atelier) -> None:  # noqa: ANN001
    assert atelier.get("/v1/a-valider").status_code == 401
    assert atelier.get("/v1/journal").status_code == 401
    assert atelier.get("/v1/commandes").status_code == 401


def test_l_api_liste_le_catalogue_et_rend_l_apercu_d_une_engageante(atelier, cle_du_proprietaire: str) -> None:  # noqa: ANN001
    entetes = {"Authorization": f"Bearer {cle_du_proprietaire}"}
    commandes = {c["nom"]: c for c in atelier.get("/v1/commandes", headers=entetes).json()["commandes"]}
    assert commandes["atelier_projet_creer"]["classe"] == "reversible"
    assert commandes["atelier_projet_creer"]["inverse"] == "atelier_projet_ranger"
    reponse = atelier.post(
        "/v1/commandes/atelier_decider",
        headers=entetes,
        json={"arguments": {"demande": "inconnue", "decision": "allow"}},
    )
    assert reponse.status_code == 200 and reponse.json()["statut"] == "apercu"
    jeton = reponse.json()["resultat"]["confirmation"]
    # Confirmée, elle s'exécute pour de bon : la demande inconnue est alors refusée par l'outil.
    confirme = atelier.post("/v1/commandes/confirmer", headers=entetes, json={"jeton": jeton})
    assert confirme.json()["statut"] == "erreur"
    assert "inconnue" in json.dumps(confirme.json()["resultat"], ensure_ascii=False)
