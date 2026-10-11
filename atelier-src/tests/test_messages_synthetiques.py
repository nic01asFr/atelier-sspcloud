"""Ce qui s'écrit au nom de la personne sans qu'elle l'ait dit ne lui est pas prêté.

Registre D-14 : la fiche d'une conversation comptait « 122 messages de la
personne » dont des résumés de compaction et des notifications ; la mémoire de
nuit en tirait des préférences que la personne n'avait jamais exprimées.
"""

from __future__ import annotations

from typing import Any

from mcp_gateway.atelier.journal import est_synthetique
from mcp_gateway.atelier.memoire import evenements_de
from mcp_gateway.atelier.memoire_modele import faits_connus
from mcp_gateway.atelier.sessions import MESSAGE_DE_REPRISE


def _user(texte: str, quand: str = "t", **drapeaux: Any) -> dict[str, Any]:
    return {"type": "user", "timestamp": quand, "message": {"role": "user", "content": [{"type": "text", "text": texte}]}, **drapeaux}


def test_un_mot_de_la_personne_reste_un_mot_de_la_personne() -> None:
    assert est_synthetique(_user("Fais-moi un plan")) is False
    assert est_synthetique(_user("[Request interrupted by user for tool use]")) is False, "un vrai geste de la personne"


def test_ce_que_le_cli_ou_l_atelier_ecrit_n_est_pas_la_personne() -> None:
    assert est_synthetique(_user("rappel", isSynthetic=True))
    assert est_synthetique(_user("contexte de l'IDE", isMeta=True))
    assert est_synthetique(_user("résumé", isCompactSummary=True))
    assert est_synthetique(_user("This session is being continued from a previous conversation that ran out of context."))
    assert est_synthetique(_user("[Atelier] Tu attendais l'accord de la personne pour : Bash — ls."))
    assert est_synthetique(_user("J'ai pris la main sur ton navigateur pendant 30 s, et je te la rends."))


def test_les_messages_de_l_atelier_portent_sa_marque() -> None:
    assert MESSAGE_DE_REPRISE.startswith("[Atelier]")


def test_la_memoire_ne_lit_que_les_paroles_de_la_personne() -> None:
    entrees = [
        _user("Exige une vérification avant intégration", "t1"),
        _user("This session is being continued from a previous conversation. Il exige OAuth.", "t2", isCompactSummary=True),
        _user("[Atelier] Tu attendais l'accord", "t3"),
    ]
    evenements, _ = evenements_de(entrees)
    assert [e["role"] for e in evenements] == ["personne", "systeme", "systeme"]


def test_la_fiche_ne_compte_que_les_vrais_messages() -> None:
    entrees = [_user("Bonjour", "t1"), _user("[Atelier] reprise", "t2"), _user("Merci", "t3")]
    evenements, _ = evenements_de(entrees)
    ligne = faits_connus({"conversation": {"projet": "p"}, "evenements": evenements})
    assert "2 message(s) de la personne" in ligne
