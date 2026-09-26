"""Le dossier de l'Assistant (vague 3, équipe A) : fichiers générés, contexte C1, délégation.

Contrat : `docs/vision/assistant-synthese.md` (A4), `assistant-contexte.md`
(C0 à C3), `assistant-role.md` §3.2, `mesures-vague1.md` §3, `decisions.md`
(A-2, A-3, A-6, S6).

Tout passe par les vraies portes : `build_app` en mode factice (seul le
harnais est faux), le vrai magasin de conversations, le vrai catalogue. La
carte est remplacée par une fausse au même contrat (`forme`, `obtenir`) : la
vraie lirait wikichat et les gardiens de la machine qui lance la suite.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier import assistant as A
from mcp_gateway.atelier.api import build_app
from mcp_gateway.atelier.coherence import Dossier, Vu, ecarts_du_dossier
from mcp_gateway.atelier.commandes import profils
from mcp_gateway.atelier.commandes.modele import ENGAGEANTE, RESERVEE
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.mcp_sync import configuration_du_profil, lier_le_projet
from mcp_gateway.atelier.project_context import DEBUT, FIN, ecrire_contexte
from mcp_gateway.atelier.vscode_bridge import COOKIE_NAME

ORIGINE = "https://testserver"


class FausseCarte:
    """La carte de l'Atelier, au contrat de `carte.Carte` : `forme` et `obtenir`."""

    def __init__(self, propositions: list[dict[str, Any]] | None = None) -> None:
        self.appels = 0
        self.propositions = propositions if propositions is not None else [
            {"id": "av-1", "titre": "Fusionner la branche agent/export", "source": "agent", "projet": "alpha"}
        ]

    async def forme(self, forme: str = "synthetique", **_: Any) -> dict[str, Any]:
        self.appels += 1
        return {
            "forme": "synthetique",
            "calcule_le": "2026-09-26T10:00:00+00:00",
            "texte": "Atelier de test — 2 projets (1 actif). MARQUEUR-CARTE\n- alpha | 1 h | 2 conv.",
        }

    async def obtenir(self, rafraichir: bool = False) -> dict[str, Any]:
        return {"sources": {"a_valider": {"etat": "ok"}}, "a_valider": list(self.propositions)}


def _client(reglages: AtelierSettings) -> TestClient:
    return TestClient(build_app(settings=reglages, use_fake=True), base_url=ORIGINE)


def _cle(client: TestClient) -> dict[str, str]:
    cle = client.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()
    return {"Authorization": f"Bearer {cle}"}


def _personne(client: TestClient) -> dict[str, str]:
    sid = client.app.state.auth.ouvrir_session()
    return {"Cookie": f"{COOKIE_NAME}={sid}", "X-Atelier-Interface": "1", "Origin": ORIGINE}


def _lire(chemin: Path) -> str:
    return chemin.read_text(encoding="utf-8")


# ── Le gabarit ──────────────────────────────────────────────────────────


def test_le_dossier_est_genere_et_n_est_pas_un_depot(reglages: AtelierSettings) -> None:
    assert A.ecrire_le_dossier(reglages) is True
    racine = reglages.assistant_root
    for nom in ("CLAUDE.md", "atelier/consignes.md", "atelier/outils.md", "atelier/carte.md",
                "atelier/a-valider.md", ".claude/settings.json"):
        assert (racine / nom).is_file(), nom
    assert (racine / "notes").is_dir()
    assert not (racine / ".git").exists(), "S6 : le dossier de l'Assistant n'est pas un dépôt"
    assert A.ecrire_le_dossier(reglages) is False, "rien à réécrire au second passage"


def test_les_imports_du_claude_md_designent_des_fichiers_qui_existent(reglages: AtelierSettings) -> None:
    A.ecrire_le_dossier(reglages)
    texte = _lire(reglages.assistant_root / "CLAUDE.md")
    imports = re.findall(r"^@(\S+)$", texte, flags=re.MULTILINE)
    assert imports == [f"atelier/{n}" for n in A.FICHIERS_C1]
    for chemin in imports:
        assert (reglages.assistant_root / chemin).is_file(), chemin
    # La consigne de compaction est dans le fichier lui-même, après les imports.
    assert "# Compact instructions" in texte
    assert texte.index("# Compact instructions") > texte.index("@atelier/a-valider.md")


def test_la_consigne_de_compaction_garde_les_delegations_et_jette_ce_qui_se_relit(reglages: AtelierSettings) -> None:
    texte = A.texte_de_compaction()
    for garde in ("lc-", "Annuler", "« Oui »", "questions encore ouvertes"):
        assert garde in texte, garde
    for jete in ("la carte", "« À valider »", "résultats d'outils", "aucun secret"):
        assert jete in texte, jete


def test_un_claude_md_etranger_est_mis_de_cote_pas_ecrase(reglages: AtelierSettings) -> None:
    reglages.assistant_root.mkdir(parents=True, exist_ok=True)
    (reglages.assistant_root / "CLAUDE.md").write_text("mes notes à moi\n", encoding="utf-8")
    A.ecrire_le_dossier(reglages)
    assert _lire(reglages.assistant_root / "CLAUDE.md.avant-atelier") == "mes notes à moi\n"
    assert A.MARQUE in _lire(reglages.assistant_root / "CLAUDE.md")


def test_la_consigne_forte_et_le_mode_d_emploi_des_meta_outils(reglages: AtelierSettings) -> None:
    outils = A.texte_des_outils()
    assert "Ne conclus JAMAIS qu'une capacité manque sans avoir cherché" in outils
    assert "deux formulations, dont une en anglais" in outils
    assert "`gateway_find_tools`" in outils and "`gateway_call_tool" in outils
    consignes = A.texte_des_consignes()
    # Les cinq conditions d'assistant-role.md §3.2, et les trois classes.
    for condition in ("une commande de l'Atelier existe", "pas le contenu d'un projet", "quelques appels",
                      "une inverse", "si elle a réussi"):
        assert condition in consignes, condition
    for classe in ("réversible", "engageante", "réservée"):
        assert f"**{classe}**" in consignes


def test_chaque_commande_citee_existe_et_est_permise_a_l_assistant(reglages: AtelierSettings) -> None:
    """Le mode d'emploi ne cite pas une commande que le serveur refuserait à l'Assistant."""
    with _client(reglages) as client:
        catalogue = client.app.state.commandes
        citees = set(re.findall(r"`(atelier_[a-z_]+)", A.texte_des_outils() + A.texte_des_consignes()))
        assert {"atelier_lancer_agent", "atelier_lancements", "atelier_carte", "atelier_a_valider"} <= citees
        for nom in sorted(citees):
            commande = catalogue.commande(nom)
            assert commande is not None, f"{nom} : inconnue du catalogue"
            assert commande.exposee_mcp and commande.classe != RESERVEE, nom
            assert profils.outil_permis(nom, profils.PROFIL_ASSISTANT), nom
            assert not profils.outil_permis(nom, profils.PROFIL_CODE) or nom in profils.OUTILS_DU_PROFIL_CODE
        assert catalogue.commande("atelier_lancer_agent").classe == ENGAGEANTE


# ── Les réglages du profil, sur toutes les surfaces ─────────────────────


def test_les_reglages_refusent_bash_et_l_ecriture_hors_du_dossier(reglages: AtelierSettings) -> None:
    donnees = A.reglages_du_profil(reglages)
    refus = donnees["permissions"]["deny"]
    permis = donnees["permissions"]["allow"]
    travail = reglages.work_dir.resolve().as_posix().lstrip("/")
    racine = reglages.assistant_root.resolve().as_posix().lstrip("/")
    assert "Bash" in refus and "WebSearch" in refus and "NotebookEdit" in refus
    # Les natifs qui ne servent pas l'Assistant : 13 000 unités par requête, mesurées.
    for natif in ("Task", "Skill", "Workflow", "CronCreate", "EnterWorktree", "SendMessage"):
        assert natif in refus, natif
    for garde in ("Read", "Glob", "Grep"):
        assert garde in permis and garde not in refus
    assert f"Edit(//{travail}/projects/**)" in refus and f"Write(//{travail}/projects/**)" in refus
    assert f"Edit(//{racine}/CLAUDE.md)" in refus and f"Edit(//{racine}/atelier/**)" in refus
    assert f"Edit(//{racine}/notes/**)" in permis and "mcp__atelier" in permis
    assert not any(r.startswith("Bash(") for r in permis)


def test_chaque_conversation_recoit_les_memes_reglages_et_sa_configuration(reglages: AtelierSettings) -> None:
    with _client(reglages) as client:
        r = client.post("/v1/sessions", headers=_cle(client), json={"slug": reglages.assistant_slug, "kind": "assistant"})
        assert r.status_code == 200, r.text
        fiche = r.json()
        cwd = Path(fiche["cwd"])
        assert cwd.parent == reglages.assistant_sessions_dir and fiche["kind"] == "assistant"
        attendu = _lire(reglages.assistant_root / ".claude" / "settings.json")
        assert _lire(cwd / ".claude" / "settings.json") == attendu, "dès la naissance : VS Code peut l'ouvrir avant un tour"
        # La configuration MCP est celle du profil `assistant`, la même pour l'app, VS Code et le terminal.
        lier_le_projet(reglages, cwd, kind="assistant")
        servie = json.loads(_lire(cwd / ".mcp.json"))["mcpServers"]
        assert servie == configuration_du_profil(reglages, profil="assistant", cwd=cwd)
        assert servie["atelier"]["headers"]["X-Atelier-Profil"] == "assistant"
        assert "X-Atelier-Projet" not in servie["atelier"]["headers"]


def test_le_verificateur_voit_bash_chez_l_assistant(reglages: AtelierSettings) -> None:
    reglages.assistant_root.mkdir(parents=True, exist_ok=True)
    lier_le_projet(reglages, reglages.assistant_root, kind="assistant")
    dossier = Dossier("assistant", reglages.assistant_root, "assistant")
    outils = ["Read", "mcp__atelier__gateway_find_tools", "mcp__atelier__gateway_call_tool"]
    vu = Vu("app", ok=True, version="2.1.282", mode="acceptEdits", modele="m", effort="medium",
            serveurs={"atelier": "connected"}, outils=outils + ["Bash"])
    assert any("l'Assistant a ['Bash']" in e for e in ecarts_du_dossier(reglages, dossier, {"app": vu}, ""))
    vu.outils = outils
    assert not any("Bash" in e for e in ecarts_du_dossier(reglages, dossier, {"app": vu}, ""))


def test_les_dossiers_sont_approuves_confiance_et_imports(reglages: AtelierSettings) -> None:
    """Sans `hasClaudeMdExternalIncludesApproved`, Claude Code ignore les imports du CLAUDE.md parent (mesuré)."""
    dossier = reglages.assistant_sessions_dir / "s1"
    dossier.mkdir(parents=True)
    claude_json = Path.home() / ".claude.json"
    claude_json.write_text(json.dumps({"userID": "garde", "projects": {"/autre": {"x": 1}}}), encoding="utf-8")
    A.ecrire_le_dossier(reglages)
    donnees = json.loads(claude_json.read_text(encoding="utf-8"))
    for chemin in (dossier, reglages.assistant_root):
        entree = donnees["projects"][str(chemin)]
        # Sans la confiance, les `allow` du dossier sont ignorés (mesuré) ; sans
        # l'approbation, les imports du CLAUDE.md parent le sont aussi.
        assert entree["hasTrustDialogAccepted"] is True
        assert entree["hasClaudeMdExternalIncludesApproved"] is True
        assert entree["hasClaudeMdExternalIncludesWarningShown"] is True
    assert donnees["userID"] == "garde" and donnees["projects"]["/autre"] == {"x": 1}, "le reste est gardé"
    assert A.approuver_les_imports(dossier) is False, "déjà approuvé : rien à réécrire"
    claude_json.write_text("{illisible", encoding="utf-8")
    assert A.approuver_les_imports(dossier) is False
    assert claude_json.read_text(encoding="utf-8") == "{illisible", "un fichier illisible n'est pas écrasé"


# ── La couche C1 : carte, « À valider », budget ─────────────────────────


def test_la_carte_et_a_valider_sont_rafraichies_avant_chaque_tour(reglages: AtelierSettings) -> None:
    with _client(reglages) as client:
        carte = FausseCarte()
        client.app.state.carte = carte
        fiche = client.post(
            "/v1/sessions", headers=_cle(client), json={"slug": reglages.assistant_slug, "kind": "assistant"}
        ).json()
        r = client.post(f"/v1/sessions/{fiche['session_id']}/messages", headers=_cle(client), json={"message": "Quoi de neuf ?"})
        assert r.status_code == 200, r.text
        c1 = reglages.assistant_root / "atelier"
        assert "MARQUEUR-CARTE" in _lire(c1 / "carte.md")
        assert "carte de 26/09" in _lire(c1 / "carte.md"), "la carte dit son heure"
        assert "`av-1` Fusionner la branche agent/export (agent, alpha)" in _lire(c1 / "a-valider.md")
        assert carte.appels >= 1
        # Le tour a bien eu lieu dans le dossier de la conversation, sous la racine qui porte le CLAUDE.md.
        appel = client.app.state.harness.appels[-1]
        assert Path(appel["cwd"]).resolve().parent == reglages.assistant_sessions_dir.resolve()
        assert not (Path(appel["cwd"]) / "CLAUDE.md").exists(), "une seule consigne : celle de la racine"


def test_une_carte_en_panne_ne_bloque_pas_le_tour(reglages: AtelierSettings) -> None:
    class Panne(FausseCarte):
        async def forme(self, *_: Any, **__: Any) -> dict[str, Any]:
            raise RuntimeError("wikichat absent")

        async def obtenir(self, rafraichir: bool = False) -> dict[str, Any]:
            raise RuntimeError("wikichat absent")

    with _client(reglages) as client:
        client.app.state.carte = Panne()
        fiche = client.post(
            "/v1/sessions", headers=_cle(client), json={"slug": reglages.assistant_slug, "kind": "assistant"}
        ).json()
        r = client.post(f"/v1/sessions/{fiche['session_id']}/messages", headers=_cle(client), json={"message": "Salut"})
        assert r.status_code == 200, r.text
        texte = _lire(reglages.assistant_root / "atelier" / "carte.md")
        assert "n'a pas pu être calculée (RuntimeError)" in texte and "`atelier_carte`" in texte


def test_a_valider_est_borne() -> None:
    propositions = [{"id": f"av-{i}", "titre": "une proposition assez longue " * 3, "source": "gardien"} for i in range(200)]
    texte = A.texte_d_a_valider(propositions)
    assert len(texte) <= A.PLAFOND_A_VALIDER_CARACTERES + 200
    assert texte.startswith("# À valider (200 en attente)") and "autres : `atelier_a_valider`" in texte
    assert "Rien n'attend" in A.texte_d_a_valider([])


def test_le_budget_c1_tient_au_pire_cas(reglages: AtelierSettings) -> None:
    """Carte au plafond du code (8 000 caractères) et file pleine : C1 reste sous son plafond."""
    from mcp_gateway.atelier.carte import BUDGET_SYNTHETIQUE

    A.ecrire_le_dossier(reglages)
    c1 = reglages.assistant_root / "atelier"
    (c1 / "carte.md").write_text(
        A.texte_de_la_carte({"calcule_le": "2026-09-26T10:00:00+00:00", "texte": "x" * BUDGET_SYNTHETIQUE}),
        encoding="utf-8",
    )
    (c1 / "a-valider.md").write_text(
        A.texte_d_a_valider([{"id": f"av-{i}", "titre": "t" * 120} for i in range(100)]), encoding="utf-8"
    )
    mesure = A.mesurer_c1(reglages)
    assert mesure["dans_le_plafond"], mesure
    assert mesure["unites"] <= A.PLAFOND_C1_UNITES < A.BUDGET_FIXE_UNITES
    fixes = {f["fichier"]: f["unites"] for f in mesure["fichiers"]}
    # Ce qui ne dépend pas de l'Atelier (gabarit, rôle, outils) reste court.
    assert fixes["CLAUDE.md"] + fixes["atelier/consignes.md"] + fixes["atelier/outils.md"] <= 2_500


# ── Création et reprise d'une conversation ──────────────────────────────


def test_le_contexte_ne_s_ecrit_que_dans_le_dossier_de_l_assistant(reglages: AtelierSettings, tmp_path: Path) -> None:
    dossier = reglages.assistant_sessions_dir / "s1"
    dossier.mkdir(parents=True)
    assert ecrire_contexte(dossier, reglages.assistant_slug, reglages) is True
    assert (reglages.assistant_root / "CLAUDE.md").is_file()
    assert (dossier / ".claude" / "settings.json").is_file()
    etranger = tmp_path / "ailleurs"
    etranger.mkdir()
    assert ecrire_contexte(etranger, reglages.assistant_slug, reglages) is False
    assert not (etranger / "CLAUDE.md").exists() and not (etranger / ".claude").exists()


def test_l_ancienne_section_d_une_conversation_est_retiree(reglages: AtelierSettings) -> None:
    dossier = reglages.assistant_sessions_dir / "ancienne"
    dossier.mkdir(parents=True)
    (dossier / "CLAUDE.md").write_text(f"{DEBUT}\n## Ce dossier dans l'Atelier\n{FIN}\n", encoding="utf-8")
    garde = reglages.assistant_sessions_dir / "gardee"
    garde.mkdir()
    (garde / "CLAUDE.md").write_text(f"Ma note\n\n{DEBUT}\nvieux\n{FIN}\n", encoding="utf-8")
    A.ecrire_le_dossier(reglages)
    assert not (dossier / "CLAUDE.md").exists()
    assert _lire(garde / "CLAUDE.md") == "Ma note\n"


def test_une_conversation_d_avant_reprend_dans_son_sous_dossier(reglages: AtelierSettings) -> None:
    """Une fiche d'avant (cwd = racine) passe dans `assistant/sessions/<id>/` et y reçoit ses réglages."""
    with _client(reglages) as client:
        client.app.state.carte = FausseCarte()
        store = client.app.state.store
        fiche = store.create(slug=reglages.assistant_slug, kind="assistant")
        fiche.cwd = str(reglages.assistant_root)
        store.save(fiche)
        r = client.post(f"/v1/sessions/{fiche.session_id}/messages", headers=_cle(client), json={"message": "On reprend"})
        assert r.status_code == 200, r.text
        reprise = store.get(fiche.session_id)
        attendu = (reglages.assistant_sessions_dir / fiche.session_id).resolve()
        assert Path(reprise.cwd).resolve() == attendu
        assert (attendu / ".claude" / "settings.json").is_file()


# ── Délégation : l'aperçu, puis le « Oui » de la personne dans le fil ───


def test_la_delegation_rend_un_apercu_et_part_au_oui_de_la_personne(reglages: AtelierSettings) -> None:
    (reglages.projects_dir / "alpha").mkdir(parents=True)
    with _client(reglages) as client:
        client.app.state.carte = FausseCarte()
        fiche = client.post(
            "/v1/sessions", headers=_cle(client), json={"slug": reglages.assistant_slug, "kind": "assistant"}
        ).json()
        # L'Assistant (sa conversation, la clé du propriétaire) demande : un aperçu, rien ne part.
        modele = {**_cle(client), "X-Atelier-Conversation": fiche["session_id"]}
        r = client.post(
            "/v1/commandes/atelier_lancer_agent", headers=modele,
            json={"arguments": {"projet": "alpha", "message": "Objectif : corriger le test.", "duree_min": 10}},
        )
        assert r.status_code == 200 and r.json()["statut"] == "apercu", r.text
        apercu = r.json()["resultat"]
        assert apercu["confirmation_requise"] is True and apercu["apercu"]["projet"] == "alpha"
        assert client.app.state.lancements.tous() == []
        # Le « Oui » de la carte, au nom de la personne.
        r = client.post("/v1/commandes/confirmer", headers=_personne(client), json={"jeton": apercu["confirmation"]})
        assert r.status_code == 200 and r.json()["statut"] == "fait", r.text
        carte = r.json()["resultat"]["carte"]
        assert carte["titre"] == "Agent lancé" and carte["voir"]["lien"].startswith("/?session=")
        lancement = r.json()["resultat"]["lancement"]
        client.app.state.lancements.attendre(lancement["id"], 10)
        # Le suivi : `atelier_lancements`, ce que l'Assistant lit.
        r = client.post("/v1/commandes/atelier_lancements", headers=modele, json={"arguments": {"projet": "alpha"}})
        assert r.json()["statut"] == "fait"
        assert [l["id"] for l in r.json()["resultat"]["lancements"]] == [lancement["id"]]
        # Le jeton ne sert qu'une fois : l'Assistant qui rappellerait après le clic est refusé.
        r = client.post(
            "/v1/commandes/atelier_lancer_agent", headers=modele,
            json={"arguments": {"projet": "alpha", "message": "Objectif : corriger le test.", "duree_min": 10},
                  "confirmation": apercu["confirmation"]},
        )
        assert r.json()["statut"] == "refus"


# ── Le réglage « Ouvrir l'Atelier sur l'Assistant » ─────────────────────


def test_le_reglage_d_accueil_est_desactive_par_defaut_et_reserve_a_la_personne(reglages: AtelierSettings) -> None:
    with _client(reglages) as client:
        etat = client.get("/v1/assistant", headers=_cle(client)).json()
        assert etat["accueil_assistant"] is False
        assert etat["c1"]["dans_le_plafond"] is True
        r = client.put("/v1/assistant/reglages", headers=_cle(client), json={"accueil_assistant": True})
        assert r.status_code == 403, "la clé du propriétaire, que lisent les agents, ne le change pas"
        r = client.put("/v1/assistant/reglages", headers=_personne(client), json={"accueil_assistant": True})
        assert r.status_code == 200 and r.json()["accueil_assistant"] is True
        assert client.get("/v1/meta", headers=_cle(client)).json()["ui"]["accueil_assistant"] is True
        client.put("/v1/assistant/reglages", headers=_personne(client), json={"accueil_assistant": False})
        assert "accueil_assistant" not in client.get("/v1/meta", headers=_cle(client)).json()["ui"]


@pytest.mark.parametrize("fichier", ["consignes", "outils"])
def test_aucun_secret_ni_chemin_de_secret_dans_la_couche_c1(reglages: AtelierSettings, fichier: str) -> None:
    texte = A.texte_des_consignes() if fichier == "consignes" else A.texte_des_outils()
    assert ".secrets" not in texte and "owner_key" not in texte and "Bearer" not in texte
