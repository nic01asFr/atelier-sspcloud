"""Les agents planifiés ou à la demande, créés par commande dans le Pilote de wikichat.

Le Pilote est remplacé par un faux qui suit son API (`POST /pilote/api/agent`
qui remplace à identifiant égal, `toggle` qui bascule, `DELETE`) et rend ses
agents sous la forme de `triggerToAgent`. On éprouve ce que les règles
garantissent : naissance désactivée, budget obligatoire, activation réservée
à la personne, modification par un modèle qui désactive, et chaque inverse.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mcp_gateway.atelier.commandes import profils
from mcp_gateway.atelier.commandes.agents import A_LA_DEMANDE
from mcp_gateway.atelier.commandes.catalogue import FAIT, REFUSE, contexte_interface
from mcp_gateway.atelier.commandes.creations import AccesPilote, ServicesCreations
from mcp_gateway.atelier.commandes.modele import ORIGINE_MCP, Contexte

NOUVELLES = {
    "atelier_agent_creer": ("reversible", "atelier_agent_supprimer", True),
    "atelier_agent_modifier": ("reversible", "atelier_agent_modifier", True),
    "atelier_agent_supprimer": ("reversible", "atelier_agent_creer", True),
    "atelier_agent_activer": ("reservee", "atelier_agent_desactiver", False),
    "atelier_agent_desactiver": ("reversible", "atelier_agent_activer", True),
}

BUDGET = {"tours": 12, "par_jour": 4}


class FauxPilote:
    """Le Pilote de wikichat, en mémoire, avec la forme de ses réponses."""

    def __init__(self, *, ignore_enabled: bool = False) -> None:
        self.triggers: dict[str, dict[str, Any]] = {}
        self.appels: list[tuple[str, Any]] = []
        self.ignore_enabled = ignore_enabled

    def _agent(self, t: dict[str, Any]) -> dict[str, Any]:
        p = t["params"]
        return {
            "id": t["id"],
            "name": p["name"],
            "desc": t["description"],
            "cron": t["schedule"],
            "enabled": t["enabled"],
            "next": "demain 8:00" if t["enabled"] else "—",
            "trigger": {
                "freq": t["schedule"],
                "cap": str(t["max_per_day"]),
                "cooldown": f"{t['cooldown_s']} s",
                "tz": "Europe/Paris",
            },
            "scope": {"dir": p["repo_path"] or "—", "servers": p["servers"]},
            "memory": {"turns": f"--max-turns {p['max_turns']}", "budget": p["model"]},
            "mission": p["initial_task"].split("\n"),
        }

    async def lire(self) -> dict[str, Any]:
        return {
            "agents": [self._agent(t) for t in self.triggers.values()],
            "system_agents": [{"id": "cron-cartographie", "name": "cartographie", "enabled": True}],
        }

    async def ecrire(self, chemin: str, corps: dict[str, Any] | None) -> dict[str, Any]:
        self.appels.append((chemin, corps))
        if chemin == "/pilote/api/agent":
            b = corps or {}
            ident = b.get("id") or f"x{len(self.triggers)}"
            self.triggers[ident] = {
                "id": ident,
                "schedule": b.get("freq") or "0 8 * * *",
                "enabled": True if self.ignore_enabled else b.get("enabled") is not False,
                "cooldown_s": b.get("cooldown_s", 3600),
                "max_per_day": b.get("max_per_day", 24),
                "description": b.get("desc") or b["name"],
                "params": {
                    "repo_path": b.get("dir", ""),
                    "name": b["name"],
                    "model": b.get("model") or "sonnet",
                    "servers": b.get("tools") or ["Bash"],
                    "max_turns": b.get("max_turns", 15),
                    "initial_task": b.get("mission", ""),
                },
            }
            return {"ok": True, "id": ident}
        if chemin.endswith("/toggle"):
            ident = chemin.split("/")[-2]
            t = self.triggers[ident]
            t["enabled"] = not t["enabled"]
            return {"ok": True, "enabled": t["enabled"]}
        raise AssertionError(chemin)

    async def supprimer(self, chemin: str) -> dict[str, Any]:
        self.appels.append(("DELETE " + chemin, None))
        return {"ok": self.triggers.pop(chemin.rsplit("/", 1)[-1], None) is not None}


def _brancher(atelier: Any, faux: FauxPilote) -> None:
    atelier.app.state.creations = ServicesCreations(
        pilote=AccesPilote(lire=faux.lire, ecrire=faux.ecrire, supprimer=faux.supprimer)
    )


def _modele() -> Contexte:
    return Contexte(acteur="conversation:assistant-1", origine=ORIGINE_MCP)


def _executer(atelier: Any, nom: str, arguments: dict[str, Any], ctx: Contexte | None = None) -> Any:
    return asyncio.run(atelier.app.state.commandes.executer(nom, arguments, ctx or _modele()))


def _journal(atelier: Any, commande: str) -> list[dict[str, Any]]:
    return atelier.app.state.commandes.journal.lire(commande=commande, limite=50)


@pytest.fixture()
def pilote(atelier: Any) -> FauxPilote:
    faux = FauxPilote()
    _brancher(atelier, faux)
    return faux


def _creer(atelier: Any, **plus: Any) -> Any:
    arguments = {"nom": "Veille des factures", "consigne": "Lire les factures du jour.", "budget": BUDGET, **plus}
    return _executer(atelier, "atelier_agent_creer", arguments)


# ── Déclaration ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("nom", sorted(NOUVELLES))
def test_classe_inverse_et_exposition(atelier: Any, nom: str) -> None:
    commande = atelier.app.state.commandes.commande(nom)
    classe, inverse, exposee = NOUVELLES[nom]
    assert commande is not None
    assert (commande.classe, commande.inverse, commande.exposee_mcp) == (classe, inverse, exposee)
    assert commande.regles, "une commande dit ce qu'elle garantit"


def test_seul_le_profil_assistant_voit_les_commandes_d_agents(atelier: Any) -> None:
    definitions = atelier.app.state.commandes._definitions_completes()  # noqa: SLF001
    code = {d["name"] for d in profils.definitions_du_profil(definitions, profils.PROFIL_CODE)}
    assistant = {d["name"] for d in profils.definitions_du_profil(definitions, profils.PROFIL_ASSISTANT)}
    for nom, (_, _, exposee) in NOUVELLES.items():
        assert nom not in code
        assert (nom in assistant) == exposee
    assert "atelier_agent_activer" not in assistant


def test_un_agent_code_est_refuse_a_l_appel(atelier: Any, pilote: FauxPilote) -> None:
    jeton = profils.PROFIL_APPELANT.set(profils.PROFIL_CODE)
    try:
        reponse = _creer(atelier)
    finally:
        profils.PROFIL_APPELANT.reset(jeton)
    assert reponse.statut == REFUSE
    assert "profil code" in reponse.charge["erreur"]
    assert not pilote.triggers


# ── Créer ───────────────────────────────────────────────────────────────


def test_creer_nait_desactive_avec_son_budget(atelier: Any, pilote: FauxPilote) -> None:
    reponse = _creer(atelier, horaire="0 7 * * 1-5", outils=["Read", "Grep"])
    assert reponse.statut == FAIT, reponse.charge
    ident = reponse.charge["agent"]
    assert ident == "agent-veille-des-factures"
    t = pilote.triggers[ident]
    assert t["enabled"] is False
    assert (t["max_per_day"], t["params"]["max_turns"], t["cooldown_s"]) == (4, 12, 3600)
    assert t["schedule"] == "0 7 * * 1-5"
    assert t["params"]["servers"] == ["Read", "Grep"]
    corps = pilote.appels[0][1]
    assert corps["enabled"] is False
    carte = reponse.charge["carte"]
    assert carte["annuler"]["inverse"] == "atelier_agent_supprimer"
    assert carte["preuve"]["actif"] is False
    # Un agent qui n'est dédié à aucun projet a son dossier, hors des projets.
    settings = atelier.app.state.settings
    assert t["params"]["repo_path"] == str(settings.work_dir / "agents" / ident)
    ligne = _journal(atelier, "atelier_agent_creer")[0]
    assert ligne["resultat"] == "fait" and ligne["acteur"] == "conversation:assistant-1"
    assert ligne["action"]["classe"] == "reversible"
    assert ligne["action"]["inverse"] == {"commande": "atelier_agent_supprimer", "arguments": {"agent": ident}}


def test_a_la_demande_et_dedie_a_un_projet(atelier: Any, pilote: FauxPilote) -> None:
    settings = atelier.app.state.settings
    (settings.projects_dir / "carte").mkdir(parents=True)
    reponse = _creer(atelier, projet="carte")
    assert reponse.statut == FAIT, reponse.charge
    t = pilote.triggers[reponse.charge["agent"]]
    assert t["schedule"] == A_LA_DEMANDE
    assert t["params"]["repo_path"] == str(settings.projects_dir / "carte")
    assert reponse.charge["carte"]["preuve"]["horaire"] == "à la demande"


@pytest.mark.parametrize(
    "plus, motif",
    [
        ({"budget": None}, "budget obligatoire"),
        ({"budget": {"tours": 5}}, "par_jour"),
        ({"budget": {"tours": 5, "par_jour": 25}}, "entre 1 et 24"),
        ({"budget": {"tours": 500, "par_jour": 2}}, "entre 1 et 100"),
        ({"outils": ["WebSearch"]}, "WebSearch"),
        ({"outils": ["inexistant"]}, "outil inconnu"),
        ({"horaire": "tous les jours"}, "horaire invalide"),
        ({"projet": "absent"}, "projet inconnu"),
    ],
)
def test_creer_refuse_ce_qui_sort_du_cadre(atelier: Any, pilote: FauxPilote, plus: dict[str, Any], motif: str) -> None:
    arguments = {"nom": "A", "consigne": "B", "budget": BUDGET, **plus}
    if arguments["budget"] is None:
        del arguments["budget"]
    reponse = _executer(atelier, "atelier_agent_creer", arguments)
    assert reponse.statut == REFUSE
    assert motif in reponse.charge["erreur"]
    assert not pilote.triggers
    assert _journal(atelier, "atelier_agent_creer")[0]["resultat"] == "refus"


def test_un_connecteur_du_pool_devient_son_jeton(atelier: Any, pilote: FauxPilote) -> None:
    from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
    from mcp_gateway.db import connect

    conn = connect(atelier.app.state.settings.gateway_db_path)
    try:
        IntegratedMcpStore(conn).upsert("grist", {"type": "http", "url": "http://grist.invalid/mcp"})
    finally:
        conn.close()
    reponse = _creer(atelier, outils=["Read", "grist"])
    assert reponse.statut == FAIT, reponse.charge
    assert pilote.triggers[reponse.charge["agent"]]["params"]["servers"] == ["Read", "mcp__grist"]


def test_un_pilote_qui_active_d_office_est_corrige(atelier: Any) -> None:
    faux = FauxPilote(ignore_enabled=True)
    _brancher(atelier, faux)
    reponse = _creer(atelier)
    assert reponse.statut == FAIT, reponse.charge
    assert faux.triggers[reponse.charge["agent"]]["enabled"] is False


def test_sans_pilote_la_commande_le_dit(atelier: Any) -> None:
    atelier.app.state.creations = ServicesCreations()
    reponse = _creer(atelier)
    assert reponse.statut == REFUSE
    assert "Pilote" in reponse.charge["erreur"]


def test_annuler_la_creation_supprime_l_agent(atelier: Any, pilote: FauxPilote) -> None:
    reponse = _creer(atelier)
    annule = _executer(atelier, "atelier_annuler", {"action": reponse.action})
    assert annule.statut == FAIT, annule.charge
    assert not pilote.triggers


# ── Activer, désactiver ─────────────────────────────────────────────────


def test_activer_est_reserve_a_la_personne(atelier: Any, pilote: FauxPilote) -> None:
    ident = _creer(atelier).charge["agent"]
    refus = _executer(atelier, "atelier_agent_activer", {"agent": ident})
    assert refus.statut == REFUSE and "réservée" in refus.charge["erreur"]
    assert pilote.triggers[ident]["enabled"] is False
    assert _journal(atelier, "atelier_agent_activer")[0]["resultat"] == "refus"

    fait = _executer(atelier, "atelier_agent_activer", {"agent": ident}, contexte_interface())
    assert fait.statut == FAIT, fait.charge
    assert pilote.triggers[ident]["enabled"] is True
    assert fait.charge["carte"]["preuve"]["actif"] is True
    ligne = _journal(atelier, "atelier_agent_activer")[0]
    assert ligne["acteur"] == "personne" and ligne["action"]["classe"] == "reservee"


def test_un_modele_desactive_mais_ne_reactive_pas(atelier: Any, pilote: FauxPilote) -> None:
    ident = _creer(atelier).charge["agent"]
    _executer(atelier, "atelier_agent_activer", {"agent": ident}, contexte_interface())
    coupe = _executer(atelier, "atelier_agent_desactiver", {"agent": ident})
    assert coupe.statut == FAIT, coupe.charge
    assert pilote.triggers[ident]["enabled"] is False
    # Annuler la désactivation, c'est activer : réservé à la personne.
    refus = _executer(atelier, "atelier_annuler", {"action": coupe.action})
    assert refus.statut == REFUSE
    assert pilote.triggers[ident]["enabled"] is False
    remis = _executer(atelier, "atelier_annuler", {"action": coupe.action}, contexte_interface())
    assert remis.statut == FAIT, remis.charge
    assert pilote.triggers[ident]["enabled"] is True


def test_les_taches_de_la_plateforme_ne_se_touchent_pas(atelier: Any, pilote: FauxPilote) -> None:
    reponse = _executer(atelier, "atelier_agent_desactiver", {"agent": "cron-cartographie"})
    assert reponse.statut == REFUSE and "plateforme" in reponse.charge["erreur"]


# ── Modifier ────────────────────────────────────────────────────────────


def test_modifier_par_un_modele_desactive_et_s_annule(atelier: Any, pilote: FauxPilote) -> None:
    ident = _creer(atelier).charge["agent"]
    _executer(atelier, "atelier_agent_activer", {"agent": ident}, contexte_interface())
    reponse = _executer(atelier, "atelier_agent_modifier", {"agent": ident, "consigne": "Lire aussi les avoirs."})
    assert reponse.statut == FAIT, reponse.charge
    t = pilote.triggers[ident]
    assert t["params"]["initial_task"] == "Lire aussi les avoirs."
    assert t["enabled"] is False and reponse.charge["desactive"] is True
    assert t["max_per_day"] == 4  # le reste de la définition est gardé
    ligne = _journal(atelier, "atelier_agent_modifier")[0]
    assert ligne["action"]["inverse"]["arguments"] == {"agent": ident, "consigne": "Lire les factures du jour."}
    annule = _executer(atelier, "atelier_annuler", {"action": reponse.action})
    assert annule.statut == FAIT, annule.charge
    assert pilote.triggers[ident]["params"]["initial_task"] == "Lire les factures du jour."


def test_la_personne_modifie_sans_desactiver(atelier: Any, pilote: FauxPilote) -> None:
    ident = _creer(atelier).charge["agent"]
    _executer(atelier, "atelier_agent_activer", {"agent": ident}, contexte_interface())
    reponse = _executer(
        atelier, "atelier_agent_modifier", {"agent": ident, "budget": {"tours": 20, "par_jour": 2}}, contexte_interface()
    )
    assert reponse.statut == FAIT, reponse.charge
    t = pilote.triggers[ident]
    assert t["enabled"] is True and t["max_per_day"] == 2 and t["params"]["max_turns"] == 20


def test_modifier_sans_rien_est_refuse(atelier: Any, pilote: FauxPilote) -> None:
    ident = _creer(atelier).charge["agent"]
    assert _executer(atelier, "atelier_agent_modifier", {"agent": ident}).statut == REFUSE


# ── Supprimer ───────────────────────────────────────────────────────────


def test_un_modele_ne_supprime_pas_un_agent_actif(atelier: Any, pilote: FauxPilote) -> None:
    ident = _creer(atelier).charge["agent"]
    _executer(atelier, "atelier_agent_activer", {"agent": ident}, contexte_interface())
    refus = _executer(atelier, "atelier_agent_supprimer", {"agent": ident})
    assert refus.statut == REFUSE and "actif" in refus.charge["erreur"]
    assert ident in pilote.triggers


def test_supprimer_puis_annuler_recree_l_agent_desactive(atelier: Any, pilote: FauxPilote) -> None:
    ident = _creer(atelier, horaire="30 6 * * *", outils=["Read"]).charge["agent"]
    reponse = _executer(atelier, "atelier_agent_supprimer", {"agent": ident})
    assert reponse.statut == FAIT, reponse.charge
    assert ident not in pilote.triggers
    assert reponse.charge["carte"]["annuler"]["inverse"] == "atelier_agent_creer"
    annule = _executer(atelier, "atelier_annuler", {"action": reponse.action})
    assert annule.statut == FAIT, annule.charge
    t = pilote.triggers[ident]
    assert t["enabled"] is False
    assert t["schedule"] == "30 6 * * *"
    assert t["params"]["initial_task"] == "Lire les factures du jour."
    assert t["params"]["servers"] == ["Read"]
    assert (t["max_per_day"], t["params"]["max_turns"]) == (4, 12)
