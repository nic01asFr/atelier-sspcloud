"""Les profils de la porte `atelier` : ce que voit et peut appeler chaque acteur.

Contrat : `docs/vision/profils-acces.md`. Le profil se déduit de la
conversation (`X-Atelier-Conversation`) : un agent code ne reçoit que les outils
de son projet — ses créations, `atelier_montrer`, `atelier_navigateur_ouvrir` —
et le projet vient de sa conversation, jamais d'un argument ; l'Assistant
reçoit tout, et trouve les commandes de l'Atelier par `gateway_find_tools`
(audit M7). `X-Atelier-Profil` ne peut que restreindre. Sans conversation,
rien ne change, et c'est noté.

Les appels passent par la vraie porte `/mcp` (`register_mcp_endpoint`), la
vraie passerelle (`McpGateway`) et le vrai catalogue de commandes d'un Atelier
de test ; seul le pool de la passerelle est remplacé (pas de serveur amont).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mcp_gateway.atelier.api import build_app
from mcp_gateway.atelier.auth import OwnerAuth
from mcp_gateway.atelier.commandes import profils
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.mcp_endpoint import register_mcp_endpoint
from mcp_gateway.mcp.gateway import McpGateway

APPS = "https://apps.test"
ATELIER = "https://testserver"

OUTILS_CODE = {
    "atelier_artefacts",
    "atelier_artefact_creer",
    "atelier_artefact_verifier",
    "atelier_artefact_demarrer",
    "atelier_artefact_arreter",
    "atelier_artefact_journal",
    "atelier_montrer",
    "atelier_navigateur_ouvrir",
}


# ── Montage ────────────────────────────────────────────────────────────


class _Rien:
    db = None
    bundles: dict[str, Any] = {}

    def get(self, *_: Any) -> None:
        return None


class _Pool(_Rien):
    """Le pool amont : il note ce qu'on lui demande, pour prouver qu'on ne lui demande rien."""

    def __init__(self) -> None:
        self.appels: list[str] = []

    async def call(self, nom: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.appels.append(nom)
        return {"content": [{"type": "text", "text": "fait"}]}


# Ce que la passerelle expose d'elle-même et du pool pour un profil large.
_EXPOSES = [
    {"name": "gateway_find_tools", "description": "Chercher un outil.", "kind": "meta"},
    {"name": "gateway_call_tool", "description": "Appeler un outil.", "kind": "meta"},
    {"name": "gateway_list_compositions", "description": "Lister les compositions.", "kind": "meta"},
    {"name": "composition_resume", "description": "Une composition.", "kind": "composition"},
    {"name": "wikichat__recall", "description": "Recall memories.", "kind": "tool", "server": "wikichat"},
]


class _Passerelle(McpGateway):
    def _resolve_exposed(self, session_id: str | None) -> dict[str, Any]:
        return {"tools": [dict(t) for t in _EXPOSES]}

    def _tool_exposure(self, session_id: str | None) -> str:
        return "full"

    def _unavailable_servers(self, session_id: str | None) -> list[str]:
        return []


@pytest.fixture()
def atelier(tmp_path: Path) -> Iterator[TestClient]:
    settings = AtelierSettings(work_dir=tmp_path / "work", apps_public_url=APPS, public_url=ATELIER)
    settings.ensure_dirs()
    for slug, nom in (("demo", "site"), ("autre", "secret")):
        dossier = settings.projects_dir / slug / "artifacts" / nom
        dossier.mkdir(parents=True)
        (dossier / "index.html").write_text(f"<h1>{slug}/{nom}</h1>", encoding="utf-8")
    with TestClient(build_app(settings=settings, use_fake=True), base_url=ATELIER) as client:
        for slug in ("demo", "autre"):
            client.post("/v1/projects", json={"slug": slug, "kind": "code"}, headers=porteur(client))
        yield client


def porteur(client: TestClient) -> dict[str, str]:
    cle = client.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()
    return {"Authorization": f"Bearer {cle}"}


def conversation(client: TestClient, slug: str = "demo") -> str:
    r = client.post("/v1/sessions", json={"slug": slug, "kind": "code"}, headers=porteur(client))
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


class Porte:
    """La porte `/mcp` montée sur la passerelle et le catalogue de l'Atelier de test."""

    def __init__(self, atelier: TestClient) -> None:
        self.atelier = atelier
        self.pool = _Pool()
        app = FastAPI()
        app.state.db = atelier.app.state.db
        app.state.mcp = _Passerelle(
            _Rien(), _Rien(), self.pool, None, outils_locaux=atelier.app.state.commandes  # type: ignore[arg-type]
        )
        register_mcp_endpoint(app, OwnerAuth(atelier.app.state.settings))
        self.client = TestClient(app, base_url=ATELIER)

    def rpc(self, methode: str, params: dict[str, Any] | None = None, *, profil: str | None = None,
            conv: str | None = None, projet: str | None = None, dossier: str | None = None) -> dict[str, Any]:
        entetes = porteur(self.atelier)
        if dossier is not None:
            entetes["X-Atelier-Dossier"] = dossier
        if projet is not None:
            entetes["X-Atelier-Projet"] = projet
        if profil is not None:
            entetes["X-Atelier-Profil"] = profil
        if conv is not None:
            entetes["X-Atelier-Conversation"] = conv
        corps = {"jsonrpc": "2.0", "id": 1, "method": methode, "params": params or {}}
        r = self.client.post("/mcp", json=corps, headers=entetes)
        assert r.status_code == 200, r.text
        return r.json()

    def noms(self, **kw: Any) -> set[str]:
        return {t["name"] for t in self.rpc("tools/list", **kw)["result"]["tools"]}

    def appeler(self, outil: str, arguments: dict[str, Any] | None = None, **kw: Any) -> tuple[Any, bool]:
        resultat = self.rpc("tools/call", {"name": outil, "arguments": arguments or {}}, **kw)["result"]
        texte = resultat["content"][0]["text"]
        try:
            charge: Any = json.loads(texte)
        except ValueError:
            charge = texte
        return charge, bool(resultat.get("isError"))


@pytest.fixture()
def porte(atelier: TestClient) -> Porte:
    return Porte(atelier)


# ── Profil code : la liste ─────────────────────────────────────────────


def test_le_profil_code_ne_liste_que_les_outils_du_projet(porte: Porte) -> None:
    assert porte.noms(profil="code", conv=conversation(porte.atelier)) == OUTILS_CODE


def test_le_profil_code_ne_demande_ni_projet_ni_auteur(porte: Porte) -> None:
    """Le projet et l'auteur viennent de la conversation : le schéma ne les exige plus."""
    outils = porte.rpc("tools/list", profil="code", conv=conversation(porte.atelier))["result"]["tools"]
    for outil in outils:
        schema = outil["inputSchema"]
        assert "projet" not in schema.get("required", []), outil["name"]
        assert "auteur" not in schema.get("properties", {}), outil["name"]
    creer = next(o for o in outils if o["name"] == "atelier_artefact_creer")
    assert creer["inputSchema"]["required"] == ["nom"]


def test_une_valeur_de_profil_inconnue_vaut_le_profil_code(porte: Porte) -> None:
    assistant = porte.atelier.app.state.store.create(kind="assistant").session_id
    assert porte.noms(profil="administrateur", conv=assistant) == OUTILS_CODE
    assert porte.noms(profil="administrateur") == OUTILS_CODE


def test_le_profil_code_a_ses_propres_consignes_et_rien_de_la_passerelle(porte: Porte) -> None:
    conv = conversation(porte.atelier)
    init = porte.rpc("initialize", profil="code", conv=conv)["result"]
    assert "gateway_" not in init["instructions"]
    assert "wikichat" in init["instructions"]
    assert porte.rpc("prompts/list", profil="code", conv=conv)["result"]["prompts"] == []
    assert porte.rpc("resources/list", profil="code", conv=conv)["result"]["resources"] == []
    assert "error" in porte.rpc("resources/read", {"uri": "profile://active"}, profil="code", conv=conv)


# ── Profil code : l'appel ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "outil, arguments",
    [
        ("gateway_find_tools", {"query": "journal"}),
        ("gateway_call_tool", {"name": "atelier_journal", "arguments": {}}),
        ("gateway_list_compositions", {}),
        ("composition_resume", {}),
        ("wikichat__recall", {"query": "x"}),
        ("atelier_decider", {"conversation": "x", "demande": "y", "decision": "allow"}),
        ("atelier_journal", {}),
        ("atelier_a_valider", {}),
        ("atelier_projets", {}),
        ("atelier_suivre", {"conversation": "x"}),
        ("atelier_transcript", {"conversation": "x"}),
        ("atelier_envoyer", {"conversation": "x", "texte": "y"}),
        ("atelier_projet_creer", {"titre": "z"}),
    ],
)
def test_le_profil_code_refuse_a_l_appel_ce_qu_il_ne_liste_pas(
    porte: Porte, outil: str, arguments: dict[str, Any]
) -> None:
    conv = conversation(porte.atelier)
    charge, erreur = porte.appeler(outil, arguments, profil="code", conv=conv)
    assert erreur, charge
    assert "profil code" in json.dumps(charge, ensure_ascii=False)
    assert porte.pool.appels == [], "rien n'est parti vers le pool"


def test_le_refus_hors_profil_est_au_journal(porte: Porte) -> None:
    conv = conversation(porte.atelier)
    porte.appeler("atelier_journal", {}, profil="code", conv=conv)
    ligne = porte.atelier.app.state.commandes.journal.lire(commande="atelier_journal")[0]
    assert ligne["resultat"] == "refus"
    assert ligne["acteur"] == f"conversation:{conv}"


def test_le_projet_vient_de_la_conversation(porte: Porte) -> None:
    conv = conversation(porte.atelier, "demo")
    charge, erreur = porte.appeler("atelier_artefacts", {}, profil="code", conv=conv)
    assert not erreur, charge
    assert {a["nom"] for a in charge["artefacts"]} == {"site"}, "les créations de demo, pas celles d'autre"

    charge, erreur = porte.appeler("atelier_artefacts", {"projet": "autre"}, profil="code", conv=conv)
    assert erreur and "projet refusé : autre" in charge["erreur"]


def test_une_creation_se_fait_dans_le_projet_de_la_conversation(porte: Porte) -> None:
    conv = conversation(porte.atelier, "demo")
    charge, erreur = porte.appeler(
        "atelier_artefact_creer", {"nom": "rapport", "auteur": "un-autre"}, profil="code", conv=conv
    )
    assert not erreur, charge
    racine = porte.atelier.app.state.settings.projects_dir
    assert (racine / "demo" / "artifacts" / "rapport").is_dir()
    assert not (racine / "autre" / "artifacts" / "rapport").exists()
    # L'auteur est la conversation, pas ce que l'agent dit être.
    auteur = (racine / "demo" / "artifacts" / "rapport" / ".auteur").read_text(encoding="utf-8").strip()
    assert auteur == conv

    charge, erreur = porte.appeler(
        "atelier_artefact_creer", {"projet": "autre", "nom": "intrus"}, profil="code", conv=conv
    )
    assert erreur
    assert not (racine / "autre" / "artifacts" / "intrus").exists()


@pytest.mark.parametrize("conv", [None, "", "poste", "inconnue-123", "../../etc/passwd"])
def test_sans_conversation_connue_le_profil_code_n_agit_pas(porte: Porte, conv: str | None) -> None:
    charge, erreur = porte.appeler("atelier_artefacts", {"projet": "demo"}, profil="code", conv=conv)
    assert erreur
    assert "le projet ne peut pas être établi" in charge["erreur"]


def test_montrer_passe_en_profil_code_pour_son_projet(porte: Porte) -> None:
    conv = conversation(porte.atelier, "demo")
    charge, erreur = porte.appeler("atelier_montrer", {"nom": "site"}, profil="code", conv=conv)
    assert not erreur, charge
    assert charge["vue"]["projet"] == "demo"
    charge, erreur = porte.appeler("atelier_montrer", {"nom": "secret", "projet": "autre"}, profil="code", conv=conv)
    assert erreur


def test_la_conversation_se_retrouve_par_l_identifiant_du_cli(porte: Porte) -> None:
    """Reprise dans VS Code : l'en-tête porte `CLAUDE_CODE_SESSION_ID`, pas l'identifiant de l'Atelier."""
    conv = conversation(porte.atelier, "demo")
    store = porte.atelier.app.state.store
    rec = store.get(conv)
    rec.claude_session_id = "0f1e2d3c-cli-id"
    store.save(rec)
    charge, erreur = porte.appeler("atelier_artefacts", {}, profil="code", conv="0f1e2d3c-cli-id")
    assert not erreur, charge
    assert {a["nom"] for a in charge["artefacts"]} == {"site"}


# ── Profil assistant et compatibilité ──────────────────────────────────


def test_le_profil_assistant_voit_tout_l_atelier_et_la_passerelle(porte: Porte) -> None:
    noms = porte.noms(profil="assistant")
    assert OUTILS_CODE <= noms
    for nom in ("atelier_decider", "atelier_journal", "atelier_a_valider", "atelier_suivre",
                "atelier_transcript", "atelier_projet_creer", "atelier_annuler",
                "gateway_find_tools", "gateway_call_tool", "composition_resume"):
        assert nom in noms, nom
    assert "atelier_a_valider_accepter" not in noms, "une commande réservée n'est jamais exposée"


def test_sans_conversation_rien_ne_change_et_c_est_note(
    porte: Porte, caplog: pytest.LogCaptureFixture
) -> None:
    """La passerelle et claude.ai n'ont pas de conversation : l'accès d'avant, noté."""
    profils._SANS_PROFIL_VUS.clear()
    with caplog.at_level(logging.WARNING, logger="atelier.profils"):
        sans = porte.noms()
        porte.noms()
    assert "gateway_find_tools" in sans and "atelier_decider" in sans
    notes = [r for r in caplog.records if "sans X-Atelier-Conversation" in r.getMessage()]
    assert len(notes) == 1, "une ligne, pas une par requête"


def test_sans_conversation_l_en_tete_code_restreint_encore(porte: Porte) -> None:
    assert porte.noms(profil="code") == OUTILS_CODE


# ── Le profil se déduit de la conversation ─────────────────────────────


def _conversation_de_l_assistant(atelier: TestClient) -> str:
    return atelier.app.state.store.create(kind="assistant").session_id


def test_un_agent_code_qui_annonce_assistant_reste_en_code(porte: Porte) -> None:
    conv = conversation(porte.atelier, "demo")
    assert porte.noms(profil="assistant", conv=conv) == OUTILS_CODE
    charge, erreur = porte.appeler("atelier_journal", {}, profil="assistant", conv=conv)
    assert erreur and "profil code" in charge["erreur"]
    charge, erreur = porte.appeler("gateway_find_tools", {"query": "x"}, profil="assistant", conv=conv)
    assert erreur


def test_un_agent_code_sans_en_tete_est_en_code(porte: Porte) -> None:
    conv = conversation(porte.atelier, "demo")
    assert porte.noms(conv=conv) == OUTILS_CODE


def test_une_conversation_inconnue_est_en_code(porte: Porte) -> None:
    assert porte.noms(profil="assistant", conv="inventee-7") == OUTILS_CODE


def test_la_conversation_de_l_assistant_a_tout(porte: Porte) -> None:
    conv = _conversation_de_l_assistant(porte.atelier)
    for annonce in ("assistant", None):
        noms = porte.noms(profil=annonce, conv=conv)
        assert {"atelier_decider", "atelier_journal", "gateway_find_tools"} <= noms, annonce


def test_la_conversation_de_l_assistant_qui_annonce_code_est_restreinte(porte: Porte) -> None:
    conv = _conversation_de_l_assistant(porte.atelier)
    assert porte.noms(profil="code", conv=conv) == OUTILS_CODE
    charge, erreur = porte.appeler("atelier_decider", {}, profil="code", conv=conv)
    assert erreur


def test_v1_commandes_deduit_aussi_le_profil(atelier: TestClient) -> None:
    conv = conversation(atelier, "demo")
    entetes = {**porteur(atelier), "X-Atelier-Profil": "assistant", "X-Atelier-Conversation": conv}
    r = atelier.post("/v1/commandes/atelier_journal", json={"arguments": {}}, headers=entetes)
    assert r.status_code == 403
    assistant = _conversation_de_l_assistant(atelier)
    entetes["X-Atelier-Conversation"] = assistant
    r = atelier.post("/v1/commandes/atelier_journal", json={"arguments": {}}, headers=entetes)
    assert r.status_code == 200


def test_le_profil_ne_survit_pas_a_l_appel(porte: Porte) -> None:
    porte.noms(profil="code", conv=conversation(porte.atelier))
    assert profils.PROFIL_APPELANT.get() == ""


# ── La recherche de l'Assistant trouve les commandes (audit M7) ────────


def _chercher(porte: Porte, **arguments: Any) -> list[str]:
    charge, erreur = porte.appeler("gateway_find_tools", arguments, profil="assistant")
    assert not erreur, charge
    return [t["name"] for t in charge["tools"]]


@pytest.mark.parametrize(
    "requete, attendu",
    [
        ("montrer ma page dans le panneau", "atelier_montrer"),
        ("autorisation en attente", "atelier_decider"),
        ("historique de ce qui a été fait", "atelier_journal"),
        ("mes créations", "atelier_artefacts"),
        ("ouvrir la page dans le navigateur", "atelier_navigateur_ouvrir"),
        ("propositions à valider", "atelier_a_valider"),
        ("ranger un projet", "atelier_projet_ranger"),
    ],
)
def test_gateway_find_tools_trouve_les_commandes_par_intention(porte: Porte, requete: str, attendu: str) -> None:
    trouves = _chercher(porte, query=requete, limit=3)
    assert attendu in trouves, trouves


def test_gateway_find_tools_filtre_les_commandes_par_service(porte: Porte) -> None:
    trouves = _chercher(porte, server="atelier", limit=100)
    assert trouves and all(n.startswith("atelier_") for n in trouves)
    assert OUTILS_CODE <= set(trouves)
    inventaire, _ = porte.appeler("gateway_find_tools", {}, profil="assistant")
    assert "atelier_decider" in {t["name"] for t in inventaire["tools"]}


def test_un_refus_d_une_commande_par_la_passerelle_n_est_pas_un_nom_inconnu(porte: Porte) -> None:
    charge, erreur = porte.appeler(
        "gateway_call_tool", {"name": "atelier_a_valider_refuser", "arguments": {}}, profil="assistant"
    )
    assert erreur
    assert "outil_introuvable" not in json.dumps(charge, ensure_ascii=False)


# ── La même garde par `/v1/commandes` (chemin d'atelier-app) ───────────


def test_v1_commandes_tient_le_profil_code(atelier: TestClient) -> None:
    conv = conversation(atelier, "demo")
    entetes = {**porteur(atelier), "X-Atelier-Profil": "code", "X-Atelier-Conversation": conv}

    liste = atelier.get("/v1/commandes", headers=entetes).json()["commandes"]
    assert {c["nom"] for c in liste} == OUTILS_CODE

    r = atelier.post("/v1/commandes/atelier_journal", json={"arguments": {}}, headers=entetes)
    assert r.status_code == 403

    r = atelier.post("/v1/commandes/atelier_montrer", json={"arguments": {"nom": "site"}}, headers=entetes)
    assert r.status_code == 200, r.text
    assert r.json()["resultat"]["vue"]["projet"] == "demo"

    r = atelier.post(
        "/v1/commandes/atelier_montrer",
        json={"arguments": {"nom": "secret", "projet": "autre"}},
        headers=entetes,
    )
    assert r.status_code == 403

    r = atelier.post("/v1/commandes/atelier_navigateur_ouvrir", json={"arguments": {}}, headers=entetes)
    assert r.status_code == 200, r.text
    assert r.json()["resultat"]["portee"] == "demo"


def test_v1_commandes_sans_profil_reste_comme_avant(atelier: TestClient) -> None:
    liste = atelier.get("/v1/commandes", headers=porteur(atelier)).json()["commandes"]
    assert "atelier_journal" in {c["nom"] for c in liste}
    r = atelier.post("/v1/commandes/atelier_journal", json={"arguments": {}}, headers=porteur(atelier))
    assert r.status_code == 200


# ── Conversation inconnue : le projet annoncé (`X-Atelier-Projet`) ─────


def test_une_conversation_inconnue_cree_dans_le_projet_annonce(porte: Porte) -> None:
    """VS Code ou terminal : l'Atelier ne connaît pas la conversation, le `.mcp.json` nomme le projet."""
    charge, erreur = porte.appeler(
        "atelier_artefact_creer", {"nom": "depuis-vscode"}, profil="code", conv="cli-inconnue-1", projet="demo"
    )
    assert not erreur, charge
    racine = porte.atelier.app.state.settings.projects_dir
    assert (racine / "demo" / "artifacts" / "depuis-vscode").is_dir()
    charge, erreur = porte.appeler("atelier_artefacts", {}, conv="cli-inconnue-1", projet="demo")
    assert not erreur and "depuis-vscode" in {a["nom"] for a in charge["artefacts"]}
    charge, erreur = porte.appeler(
        "atelier_artefacts", {"projet": "autre"}, conv="cli-inconnue-1", projet="demo"
    )
    assert erreur and "projet refusé" in charge["erreur"]


@pytest.mark.parametrize("projet", ["inexistant", "../demo", "Demo", ""])
def test_un_projet_annonce_inexistant_est_refuse(porte: Porte, projet: str) -> None:
    charge, erreur = porte.appeler(
        "atelier_artefact_creer", {"nom": "x"}, profil="code", conv="cli-inconnue-2", projet=projet
    )
    assert erreur and "le projet ne peut pas être établi" in charge["erreur"]


def test_une_conversation_connue_ignore_le_projet_annonce(
    porte: Porte, caplog: pytest.LogCaptureFixture
) -> None:
    conv = conversation(porte.atelier, "autre")
    with caplog.at_level(logging.WARNING, logger="atelier.profils"):
        charge, erreur = porte.appeler("atelier_artefacts", {}, profil="code", conv=conv, projet="demo")
    assert not erreur, charge
    assert {a["nom"] for a in charge["artefacts"]} == {"secret"}, "la fiche gagne"
    assert any("projet de la fiche autre retenu" in r.getMessage() for r in caplog.records)


def test_le_projet_annonce_ne_donne_jamais_assistant(porte: Porte) -> None:
    assert porte.noms(profil="assistant", conv="cli-inconnue-3", projet="demo") == OUTILS_CODE


# ── Conversation inconnue de l'Assistant (VS Code, terminal) ───────────


def _dossier_de_l_assistant(atelier: TestClient) -> str:
    dossier = atelier.app.state.settings.assistant_root
    dossier.mkdir(parents=True, exist_ok=True)
    return str(dossier)


def test_une_conversation_inconnue_de_l_assistant_recoit_les_meta_outils(porte: Porte) -> None:
    dossier = _dossier_de_l_assistant(porte.atelier)
    noms = porte.noms(profil="assistant", conv="cli-assistant-1", dossier=dossier)
    assert {"gateway_find_tools", "gateway_call_tool", "atelier_decider", "atelier_journal"} <= noms


def test_une_conversation_inconnue_avec_un_projet_reste_en_code(porte: Porte) -> None:
    dossier = _dossier_de_l_assistant(porte.atelier)
    noms = porte.noms(profil="assistant", conv="cli-assistant-2", dossier=dossier, projet="demo")
    assert noms == OUTILS_CODE


@pytest.mark.parametrize("dossier", [None, "", "/tmp", "{projet}"])
def test_une_conversation_inconnue_hors_du_dossier_de_l_assistant_reste_en_code(
    porte: Porte, dossier: str | None
) -> None:
    if dossier == "{projet}":
        dossier = str(porte.atelier.app.state.settings.projects_dir / "demo")
    assert porte.noms(profil="assistant", conv="cli-assistant-3", dossier=dossier) == OUTILS_CODE


def test_une_conversation_connue_de_code_qui_annonce_assistant_et_le_dossier_reste_en_code(porte: Porte) -> None:
    conv = conversation(porte.atelier, "demo")
    dossier = _dossier_de_l_assistant(porte.atelier)
    assert porte.noms(profil="assistant", conv=conv, dossier=dossier) == OUTILS_CODE
