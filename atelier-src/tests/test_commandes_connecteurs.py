"""Les connecteurs par commande : le pool de la passerelle, le choix d'un projet, les secrets.

Le pool est le vrai (`gateway.db` d'un Atelier jetable) ; seule la sonde est
remplacée. On éprouve : l'ajout engageant (aperçu, puis jeton), le refus de
tout secret en argument, le retrait qui garde la déclaration et son annulation
qui la remet sans ressaisir le secret, le choix d'un projet par la fonction
de profil, et l'accord d'un secret réservé à la personne.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from mcp_gateway.atelier.commandes import profils
from mcp_gateway.atelier.commandes.catalogue import APERCU, FAIT, REFUSE, contexte_interface
from mcp_gateway.atelier.commandes.creations import ServicesCreations
from mcp_gateway.atelier.commandes.modele import ORIGINE_MCP, Contexte
from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
from mcp_gateway.db import connect

NOUVELLES = {
    "atelier_connecteur_ajouter": ("engageante", "atelier_connecteur_retirer", True),
    "atelier_connecteur_retirer": ("reversible", "atelier_connecteur_ajouter", True),
    "atelier_connecteur_choisir": ("reversible", "atelier_connecteur_choisir", True),
    "atelier_connecteur_accorder": ("reservee", None, False),
}
JETON_QGIS = "jeton-qgis-0123456789abcdef"


def _modele() -> Contexte:
    return Contexte(acteur="conversation:assistant-1", origine=ORIGINE_MCP)


def _executer(atelier: Any, nom: str, arguments: dict[str, Any], ctx: Contexte | None = None) -> Any:
    return asyncio.run(atelier.app.state.commandes.executer(nom, arguments, ctx or _modele()))


def _pool(atelier: Any) -> dict[str, dict[str, Any]]:
    conn = connect(atelier.app.state.settings.gateway_db_path)
    try:
        return IntegratedMcpStore(conn).list_servers(mask=False)
    finally:
        conn.close()


def _mettre_au_pool(atelier: Any, **serveurs: dict[str, Any]) -> None:
    conn = connect(atelier.app.state.settings.gateway_db_path)
    try:
        for nom, cfg in serveurs.items():
            IntegratedMcpStore(conn).upsert(nom, cfg)
    finally:
        conn.close()


def _projet(atelier: Any, slug: str) -> Path:
    chemin = atelier.app.state.settings.projects_dir / slug
    chemin.mkdir(parents=True, exist_ok=True)
    return chemin


def _servis(projet: Path) -> set[str]:
    return set(json.loads((projet / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"])


@pytest.fixture()
def sondes(atelier: Any) -> list[str]:
    vues: list[str] = []

    async def sonder(nom: str) -> dict[str, Any]:
        vues.append(nom)
        return {"sonde": "ok", "online": True, "tools": 3}

    atelier.app.state.creations = ServicesCreations(sonder=sonder)
    return vues


def _ajouter(atelier: Any, arguments: dict[str, Any], ctx: Contexte | None = None) -> Any:
    ctx = ctx or _modele()
    apercu = _executer(atelier, "atelier_connecteur_ajouter", arguments, ctx)
    assert apercu.statut == APERCU, apercu.charge
    jeton = apercu.charge["confirmation"]
    return _executer(atelier, "atelier_connecteur_ajouter", {**arguments, "confirmation": jeton}, ctx)


# ── Déclaration ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("nom", sorted(NOUVELLES))
def test_classe_inverse_et_exposition(atelier: Any, nom: str) -> None:
    commande = atelier.app.state.commandes.commande(nom)
    classe, inverse, exposee = NOUVELLES[nom]
    assert commande is not None
    assert (commande.classe, commande.inverse, commande.exposee_mcp) == (classe, inverse, exposee)


def test_seul_le_profil_assistant_voit_les_commandes_de_connecteurs(atelier: Any) -> None:
    definitions = atelier.app.state.commandes._definitions_completes()  # noqa: SLF001
    code = {d["name"] for d in profils.definitions_du_profil(definitions, profils.PROFIL_CODE)}
    assistant = {d["name"] for d in profils.definitions_du_profil(definitions, profils.PROFIL_ASSISTANT)}
    for nom, (_, _, exposee) in NOUVELLES.items():
        assert nom not in code
        assert (nom in assistant) == exposee
    ajouter = next(d for d in definitions if d["name"] == "atelier_connecteur_ajouter")
    assert "confirmation" in ajouter["inputSchema"]["properties"]


def test_un_agent_code_ne_peut_pas_ajouter(atelier: Any, sondes: list[str]) -> None:
    jeton = profils.PROFIL_APPELANT.set(profils.PROFIL_CODE)
    try:
        reponse = _executer(atelier, "atelier_connecteur_ajouter", {"nom": "qgis", "url": "http://qgis.invalid/mcp"})
    finally:
        profils.PROFIL_APPELANT.reset(jeton)
    assert reponse.statut == REFUSE and "profil code" in reponse.charge["erreur"]


# ── Ajouter ─────────────────────────────────────────────────────────────


def test_ajouter_montre_un_apercu_puis_agit_sur_le_oui(atelier: Any, sondes: list[str]) -> None:
    arguments = {"nom": "qgis", "url": "http://qgis.invalid/mcp", "en_tetes": {"X-Projet": "carte"}}
    apercu = _executer(atelier, "atelier_connecteur_ajouter", arguments)
    assert apercu.statut == APERCU
    assert apercu.charge["apercu"]["declaration"] == {
        "type": "http",
        "url": "http://qgis.invalid/mcp",
        "headers": {"X-Projet": "carte"},
    }
    assert "qgis" not in _pool(atelier)
    fait = _executer(atelier, "atelier_connecteur_ajouter", {**arguments, "confirmation": apercu.charge["confirmation"]})
    assert fait.statut == FAIT, fait.charge
    assert _pool(atelier)["qgis"]["enabled"] is True
    assert sondes == ["qgis"]
    carte = fait.charge["carte"]
    assert carte["preuve"]["sonde"]["sonde"] == "ok"
    assert carte["annuler"]["inverse"] == "atelier_connecteur_retirer"
    lignes = atelier.app.state.commandes.journal.lire(commande="atelier_connecteur_ajouter", limite=10)
    assert [l["resultat"] for l in lignes] == ["fait", "apercu"]
    assert lignes[0]["action"]["classe"] == "engageante"
    # Un projet qui hérite du pool le reçoit.
    projet = _projet(atelier, "carte")
    from mcp_gateway.atelier.mcp_sync import lier_le_projet

    lier_le_projet(atelier.app.state.settings, projet)
    assert "qgis" in _servis(projet)


@pytest.mark.parametrize(
    "arguments, motif",
    [
        ({"url": "http://q.invalid/mcp", "en_tetes": {"Authorization": f"Bearer {JETON_QGIS}"}}, "headers.Authorization"),
        ({"commande": "npx", "arguments": ["serveur"], "env": {"API_KEY": "abcdef123456"}}, "env.API_KEY"),
        ({"url": "http://q.invalid/mcp?token=abcdef123456"}, "?token="),
        ({"url": "http://moi:secret@q.invalid/mcp"}, "identifiants"),
        ({"url": "http://q.invalid/mcp", "en_tetes": {"X-Cle": "${QGIS_CLE}"}}, "${"),
        ({"commande": "npx", "arguments": ["--header", f"Authorization: Bearer {JETON_QGIS}"]}, "args["),
    ],
)
def test_aucun_secret_ne_passe_par_un_argument(
    atelier: Any, sondes: list[str], arguments: dict[str, Any], motif: str
) -> None:
    # Refusé dès l'aperçu : pas de jeton, rien n'est fait.
    reponse = _executer(atelier, "atelier_connecteur_ajouter", {"nom": "qgis", **arguments})
    assert reponse.statut == REFUSE and "confirmation" not in reponse.charge
    assert motif in reponse.charge["erreur"] and "atelier_connecteur_accorder" in reponse.charge["erreur"]
    assert "qgis" not in _pool(atelier)


def test_ajouter_refuse_un_nom_pris_ou_tenu(atelier: Any, sondes: list[str]) -> None:
    _mettre_au_pool(atelier, qgis={"type": "http", "url": "http://q.invalid/mcp"})
    tenu = _executer(atelier, "atelier_connecteur_ajouter", {"nom": "wikichat", "url": "http://w.invalid/sse"})
    assert tenu.statut == REFUSE and "tenu par l'Atelier" in tenu.charge["erreur"]
    deja = _ajouter(atelier, {"nom": "qgis", "url": "http://autre.invalid/mcp"})
    assert deja.statut == REFUSE and "déjà dans le pool" in deja.charge["erreur"]


def test_ajouter_et_choisir_pour_un_projet_qui_a_fait_son_choix(atelier: Any, sondes: list[str]) -> None:
    _mettre_au_pool(atelier, n8n={"type": "http", "url": "http://n8n.invalid/mcp"})
    projet = _projet(atelier, "carte")
    assert _executer(atelier, "atelier_connecteur_choisir", {"projet": "carte", "connecteurs": ["n8n"]}).statut == FAIT
    fait = _ajouter(atelier, {"nom": "qgis", "url": "http://qgis.invalid/mcp", "projets": ["carte"]})
    assert fait.statut == FAIT, fait.charge
    assert {"qgis", "n8n"} <= _servis(projet)


# ── Retirer, et l'annuler ───────────────────────────────────────────────


def test_retirer_garde_la_declaration_et_annuler_la_remet(atelier: Any, sondes: list[str]) -> None:
    _mettre_au_pool(
        atelier,
        qgis={"type": "http", "url": "http://qgis.invalid/mcp", "headers": {"Authorization": f"Bearer {JETON_QGIS}"}},
    )
    projet = _projet(atelier, "carte")
    from mcp_gateway.atelier.mcp_sync import lier_le_projet

    lier_le_projet(atelier.app.state.settings, projet)
    assert "qgis" in _servis(projet)

    retire = _executer(atelier, "atelier_connecteur_retirer", {"nom": "qgis"})
    assert retire.statut == FAIT, retire.charge
    assert _pool(atelier)["qgis"]["enabled"] is False
    assert "qgis" not in _servis(projet)
    ligne = atelier.app.state.commandes.journal.lire(commande="atelier_connecteur_retirer", limite=1)[0]
    assert ligne["action"]["inverse"] == {
        "commande": "atelier_connecteur_ajouter",
        "arguments": {"nom": "qgis", "reprendre": True},
    }
    assert JETON_QGIS not in json.dumps(ligne)

    # Un autre modèle n'annule pas sans accord : la reprise est engageante.
    autre = Contexte(acteur="conversation:autre", origine=ORIGINE_MCP)
    assert _executer(atelier, "atelier_annuler", {"action": retire.action}, autre).statut == REFUSE
    assert _pool(atelier)["qgis"]["enabled"] is False
    # Son auteur, si : son geste vaut accord pour l'inverse, sans jeton ni secret.
    annule = _executer(atelier, "atelier_annuler", {"action": retire.action})
    assert annule.statut == FAIT, annule.charge
    reprise = atelier.app.state.commandes.journal.lire(commande="atelier_connecteur_ajouter", limite=1)[0]
    assert reprise["resultat"] == "fait" and reprise["action"]["classe"] == "engageante"
    assert reprise["action"]["via"] == f"atelier_annuler:{retire.action}"
    entree = _pool(atelier)["qgis"]
    assert entree["enabled"] is True
    assert entree["headers"]["Authorization"] == f"Bearer {JETON_QGIS}"
    assert "qgis" in _servis(projet)
    assert JETON_QGIS not in (projet / ".mcp.json").read_text(encoding="utf-8")


def test_reprendre_n_ouvre_pas_ce_que_la_personne_a_coupe(atelier: Any, sondes: list[str]) -> None:
    _mettre_au_pool(atelier, qgis={"type": "http", "url": "http://qgis.invalid/mcp", "enabled": False})
    for ctx in (_modele(), contexte_interface()):
        reponse = _executer(atelier, "atelier_connecteur_ajouter", {"nom": "qgis", "reprendre": True}, ctx)
        assert reponse.statut == REFUSE and "n'a pas été retiré par l'Atelier" in reponse.charge["erreur"]
    assert _pool(atelier)["qgis"]["enabled"] is False


def test_annuler_un_ajout_retire_le_connecteur(atelier: Any, sondes: list[str]) -> None:
    fait = _ajouter(atelier, {"nom": "qgis", "url": "http://qgis.invalid/mcp"})
    annule = _executer(atelier, "atelier_annuler", {"action": fait.action})
    assert annule.statut == FAIT, annule.charge
    assert _pool(atelier)["qgis"]["enabled"] is False


# ── Choisir ─────────────────────────────────────────────────────────────


def test_choisir_passe_par_la_fonction_de_profil_et_s_annule(atelier: Any) -> None:
    _mettre_au_pool(
        atelier,
        qgis={"type": "http", "url": "http://qgis.invalid/mcp"},
        n8n={"type": "http", "url": "http://n8n.invalid/mcp"},
    )
    projet = _projet(atelier, "carte")
    reponse = _executer(atelier, "atelier_connecteur_choisir", {"projet": "carte", "connecteurs": ["qgis"]})
    assert reponse.statut == FAIT, reponse.charge
    assert reponse.charge["herite"] is False and reponse.charge["connecteurs"] == ["qgis"]
    servis = _servis(projet)
    assert "qgis" in servis and "n8n" not in servis and "atelier" in servis
    # Même configuration que celle que calcule le profil pour ce dossier.
    from mcp_gateway.atelier.mcp_sync import configuration_du_profil

    attendu = configuration_du_profil(atelier.app.state.settings, profil="code", cwd=projet)
    assert json.loads((projet / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"] == attendu
    assert reponse.charge["carte"]["annuler"]["inverse"] == "atelier_connecteur_choisir"

    annule = _executer(atelier, "atelier_annuler", {"action": reponse.action})
    assert annule.statut == FAIT, annule.charge
    assert {"qgis", "n8n"} <= _servis(projet)
    from mcp_gateway.atelier.mcp_sync import herite_du_pool

    assert herite_du_pool(projet)


@pytest.mark.parametrize(
    "arguments, motif",
    [
        ({"projet": "carte", "connecteurs": ["absent"]}, "absents du pool"),
        ({"projet": "carte"}, "exactement"),
        ({"projet": "carte", "connecteurs": [], "heriter": True}, "exactement"),
        ({"projet": "inconnu", "heriter": True}, "projet inconnu"),
    ],
)
def test_choisir_refuse(atelier: Any, arguments: dict[str, Any], motif: str) -> None:
    _projet(atelier, "carte")
    reponse = _executer(atelier, "atelier_connecteur_choisir", arguments)
    assert reponse.statut == REFUSE and motif in reponse.charge["erreur"]


# ── Accorder un secret ──────────────────────────────────────────────────


def test_accorder_est_reserve_et_ne_montre_jamais_la_valeur(atelier: Any) -> None:
    settings = atelier.app.state.settings
    _mettre_au_pool(atelier, qgis={"type": "http", "url": "http://qgis.invalid/mcp"})
    settings.secrets_dir.mkdir(parents=True, exist_ok=True)
    fichier = settings.secrets_dir / "qgis_jeton"
    fichier.write_text(JETON_QGIS + "\n", encoding="utf-8")
    fichier.chmod(0o600)
    arguments = {"nom": "qgis", "champ": "headers.Authorization", "secret": "qgis_jeton", "schema": "Bearer"}

    refus = _executer(atelier, "atelier_connecteur_accorder", arguments)
    assert refus.statut == REFUSE and "réservée" in refus.charge["erreur"]
    assert "headers" not in _pool(atelier)["qgis"]

    fait = _executer(atelier, "atelier_connecteur_accorder", arguments, contexte_interface())
    assert fait.statut == FAIT, fait.charge
    assert _pool(atelier)["qgis"]["headers"]["Authorization"] == f"Bearer {JETON_QGIS}"
    assert JETON_QGIS not in json.dumps(fait.charge)
    journal = json.dumps(atelier.app.state.commandes.journal.lire(commande="atelier_connecteur_accorder", limite=5))
    assert JETON_QGIS not in journal
    projet = _projet(atelier, "carte")
    from mcp_gateway.atelier.mcp_sync import lier_le_projet

    lier_le_projet(settings, projet)
    assert JETON_QGIS not in (projet / ".mcp.json").read_text(encoding="utf-8")


def test_accorder_refuse_une_valeur_ou_un_chemin(atelier: Any) -> None:
    _mettre_au_pool(atelier, qgis={"type": "http", "url": "http://qgis.invalid/mcp"})
    for secret in ("../cle", "Bearer abc def", "/etc/passwd"):
        reponse = _executer(
            atelier,
            "atelier_connecteur_accorder",
            {"nom": "qgis", "champ": "headers.Authorization", "secret": secret},
            contexte_interface(),
        )
        assert reponse.statut == REFUSE


# ── La clé `atelier` d'une entrée du pool (vues relayées, équipe B) ─────

VUES = {"vues": [{"nom": "bureau", "genre": "bureau", "amont": "http://blender-remote-mcp:6080", "vnc": "/websockify"}]}


def test_un_modele_ne_pose_pas_la_cle_atelier(atelier: Any, sondes: list[str]) -> None:
    arguments = {"nom": "blender", "url": "http://blender.invalid/mcp", "atelier": VUES}
    reponse = _executer(atelier, "atelier_connecteur_ajouter", arguments)
    assert reponse.statut == REFUSE and "la personne" in reponse.charge["erreur"]
    assert "confirmation" not in reponse.charge
    assert "blender" not in _pool(atelier)


def test_la_personne_pose_la_cle_atelier_qui_n_est_jamais_rendue(atelier: Any, sondes: list[str]) -> None:
    arguments = {"nom": "blender", "url": "http://blender.invalid/mcp", "atelier": VUES}
    apercu = _executer(atelier, "atelier_connecteur_ajouter", arguments, contexte_interface())
    assert apercu.statut == APERCU
    assert "atelier" not in apercu.charge["apercu"]["declaration"]
    assert apercu.charge["apercu"]["declaration"]["vues_relayees"] == 1
    fait = _executer(
        atelier, "atelier_connecteur_ajouter", {**arguments, "confirmation": apercu.charge["confirmation"]},
        contexte_interface(),
    )
    assert fait.statut == FAIT, fait.charge
    assert _pool(atelier)["blender"]["atelier"] == VUES
    assert "blender-remote-mcp" not in json.dumps(fait.charge)
    journal = atelier.app.state.commandes.journal.lire(commande="atelier_connecteur_ajouter", limite=5)
    assert "blender-remote-mcp" not in json.dumps(journal)
    assert journal[0]["action"]["arguments"]["vues_relayees"] == 1
    # Un modèle qui retire puis annule ne perd ni n'expose la clé.
    retire = _executer(atelier, "atelier_connecteur_retirer", {"nom": "blender"})
    assert retire.statut == FAIT, retire.charge
    remis = _executer(atelier, "atelier_annuler", {"action": retire.action})
    assert remis.statut == FAIT, remis.charge
    assert _pool(atelier)["blender"]["atelier"] == VUES
    assert "blender-remote-mcp" not in json.dumps(retire.charge) + json.dumps(remis.charge)
