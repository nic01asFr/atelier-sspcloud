"""Lot B : le même contexte d'Atelier sur toutes les surfaces, sans doubler le briefing.

`.atelier/contexte.md` est le seul canal de ce que l'Atelier sait (profil,
outils du projet, où exposer, comment joindre les autres projets). Le
`CLAUDE.md` du gabarit l'importe : Claude Code le charge de lui-même dans
l'Atelier, dans VS Code, au terminal, et le relit après compaction. Le
briefing et le courrier restent au hook `SessionStart` de wikichat.

Ce qu'on vérifie : chaque chemin qui l'écrit (tour de l'Atelier, démarrage du
service, création d'un projet, agent lancé) écrit exactement le même texte,
qui ne dépend d'aucune surface ; ce texte annonce les outils que le serveur
`atelier` donne vraiment au profil `code` ; il ne porte ni briefing ni
courrier.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from mcp_gateway.atelier.api import build_app
from mcp_gateway.atelier.commandes.profils import OUTILS_DU_PROFIL_CODE
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.project_context import (
    IMPORT_DU_CONTEXTE,
    contexte_attendu,
    ecrire_tous_les_contextes,
)


def _projet(reglages: AtelierSettings, slug: str) -> Path:
    dossier = reglages.projects_dir / slug
    dossier.mkdir(parents=True)
    (dossier / "CLAUDE.md").write_text(IMPORT_DU_CONTEXTE + "\n\n# Projet\n", encoding="utf-8")
    return dossier


def _contexte(dossier: Path) -> str:
    return (dossier / ".atelier" / "contexte.md").read_text(encoding="utf-8")


def test_tous_les_chemins_ecrivent_le_meme_contexte(reglages: AtelierSettings) -> None:
    dossier = _projet(reglages, "alpha")
    attendu = contexte_attendu(reglages, dossier, "alpha")[1] + "\n"

    # Démarrage du service (ce que lisent VS Code et le terminal sans tour de l'Atelier).
    assert ecrire_tous_les_contextes(reglages) == 1
    assert _contexte(dossier) == attendu
    (dossier / ".atelier" / "contexte.md").unlink()

    with TestClient(build_app(settings=reglages, use_fake=True), base_url="https://testserver") as client:
        # Un tour de l'Atelier.
        fiche = client.app.state.store.create(slug="alpha")
        client.app.state.store.send(fiche.session_id, "bonjour")
        assert _contexte(dossier) == attendu
        # Un agent lancé (lot D).
        (dossier / ".atelier" / "contexte.md").unlink()
        l = client.app.state.lancements.lancer(
            {"projet": "alpha", "message": "x", "plafonds": {"duree_s": 30}},
            acteur="automate:essai", origine="wikichat:essai", exiger_duree=True,
        )
        client.app.state.lancements.attendre(l.id, 10)
        assert _contexte(dossier) == attendu
    # Rien n'y dépend de la surface ni de la conversation.
    assert fiche.session_id not in attendu
    for mot in ("VS Code", "terminal"):
        assert attendu.count(mot) == 1, "seule la phrase qui dit que le texte est le même partout les nomme"


def test_le_contexte_annonce_les_outils_du_profil_code_et_pas_le_briefing(reglages: AtelierSettings) -> None:
    dossier = _projet(reglages, "alpha")
    texte = contexte_attendu(reglages, dossier, "alpha")[1]
    for outil in OUTILS_DU_PROFIL_CODE:
        assert f"`{outil}`" in texte
    for interdit in ("gateway_find_tools", "atelier_projet_creer", "Courrier :", "Présents sur ce projet", "Fils ouverts"):
        assert interdit not in texte, interdit
    assert "contact_agent" in texte and "list_sessions" in texte
    assert "atelier_artefact_creer" in texte and "atelier_montrer" in texte
    assert "Onyxia : aucun outil" in texte
    assert len(texte) < 10_000, "le hook est coupé à 10 000 caractères ; l'import aussi doit rester court"


def test_un_deploiement_declare_change_la_ligne_onyxia(reglages: AtelierSettings) -> None:
    from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
    from mcp_gateway.db import connect

    conn = connect(reglages.gateway_db_path)
    try:
        IntegratedMcpStore(conn).upsert("Onyxia", {"type": "http", "url": "https://onyxia.exemple/mcp"})
    finally:
        conn.close()
    dossier = _projet(reglages, "alpha")
    (dossier / ".atelier").mkdir()
    (dossier / ".atelier" / "projet.json").write_text(
        json.dumps({"slug": "alpha", "titre": "alpha", "deploiement": {"pod": "mon-pod"}}), encoding="utf-8"
    )
    texte = contexte_attendu(reglages, dossier, "alpha")[1]
    ligne = next(l for l in texte.splitlines() if l.startswith("- Onyxia"))
    assert "borné au déploiement de ce projet" in ligne and "mon-pod" in ligne


def test_un_projet_d_avant_la_structure_n_est_pas_touche_au_demarrage(reglages: AtelierSettings) -> None:
    dossier = reglages.projects_dir / "ancien"
    dossier.mkdir(parents=True)
    (dossier / "CLAUDE.md").write_text("# Ancien\n", encoding="utf-8")
    assert ecrire_tous_les_contextes(reglages) == 0
    assert (dossier / "CLAUDE.md").read_text(encoding="utf-8") == "# Ancien\n"


def test_un_projet_cree_recoit_son_contexte_aussitot(reglages: AtelierSettings) -> None:
    with TestClient(build_app(settings=reglages, use_fake=True), base_url="https://testserver") as client:
        sid = client.app.state.auth.ouvrir_session()
        from mcp_gateway.atelier.vscode_bridge import COOKIE_NAME

        r = client.post(
            "/v1/commandes/atelier_projet_creer",
            headers={"Cookie": f"{COOKIE_NAME}={sid}", "X-Atelier-Interface": "1", "Origin": "https://testserver"},
            json={"arguments": {"titre": "Carte des sentiers"}},
        )
        assert r.status_code == 200, r.text
        slug = r.json()["resultat"]["projet"]
    dossier = reglages.projects_dir / slug
    # Le gabarit importe le contexte en tête de son CLAUDE.md.
    assert (dossier / "CLAUDE.md").read_text(encoding="utf-8").startswith(IMPORT_DU_CONTEXTE)
    assert _contexte(dossier) == contexte_attendu(reglages, dossier, slug)[1] + "\n"
