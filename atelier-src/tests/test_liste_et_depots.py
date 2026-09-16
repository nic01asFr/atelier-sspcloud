"""Ce que la liste des conversations doit dire, et ce qu'un dépôt doit porter.

Deux défauts relevés le 14 septembre 2026 en surveillant une session :

- une conversation qui attendait une autorisation se listait « en réponse »
  comme les autres ; l'agent est resté bloqué cinq minutes avant qu'on ouvre
  le fil. La liste porte désormais `attend_une_decision` ;
- quatorze projets signaient « Atelier <atelier@localhost> » : notre réglage
  local recouvrait toute identité, et le `.gitignore` écrit par l'Atelier
  oubliait `.vscode/`, qu'il dépose pourtant — un agent qui « commite tout »
  l'embarquait.
"""

from __future__ import annotations

import os
import subprocess

from fastapi.testclient import TestClient

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.decisions import Demande
from mcp_gateway.atelier.git_repos import (
    LIGNES_DE_L_ATELIER,
    _identite,
    completer_le_gitignore,
    initialiser,
)

from test_canal_decision import _cle


def test_la_liste_dit_quelle_conversation_attend_une_autorisation(
    atelier: TestClient,
) -> None:
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    sid = atelier.post(
        "/v1/sessions", headers=entete, json={"slug": "essai", "title": "Attente"}
    ).json()["session_id"]
    registre = atelier.app.state.harness.decisions

    def fiche() -> dict:
        liste = atelier.get("/v1/sessions", headers=entete).json()["sessions"]
        return next(s for s in liste if s["session_id"] == sid)

    assert fiche()["attend_une_decision"] is False
    registre.poser(Demande(request_id="att1", session_id=sid, outil="Bash"))
    assert fiche()["attend_une_decision"] is True
    registre.clore("att1")
    assert fiche()["attend_une_decision"] is False
    atelier.delete(f"/v1/sessions/{sid}", headers=entete)


def test_archiver_un_projet_range_ses_conversations(atelier: TestClient) -> None:
    """Un projet archivé se rouvre, et ses conversations avec — pas « sans projet »."""
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    atelier.post(
        "/v1/projects", headers=entete, json={"slug": "range", "kind": "code", "title": "Rangé"}
    )
    sid = atelier.post(
        "/v1/sessions", headers=entete, json={"slug": "range", "title": "Dedans"}
    ).json()["session_id"]

    def listee(**params) -> bool:
        liste = atelier.get("/v1/sessions", headers=entete, params=params).json()["sessions"]
        return any(s["session_id"] == sid for s in liste)

    assert listee()
    assert atelier.patch(
        "/v1/projects/range", headers=entete, json={"archived": True}
    ).status_code == 200
    assert not listee(), "rangée avec son projet"
    assert listee(include_archived="true"), "mais pas perdue"
    atelier.patch("/v1/projects/range", headers=entete, json={"archived": False})
    assert listee(), "revenue avec lui"
    atelier.delete(f"/v1/sessions/{sid}", headers=entete)


def _git(chemin, *args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.run(
        ["git", "-C", str(chemin), *args],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    ).stdout.strip()


def test_sans_identite_globale_l_atelier_pose_la_sienne(tmp_path, monkeypatch) -> None:
    # Un fichier global vide, pour ne pas lire — ni écrire — celui du poste.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig-vide"))
    (tmp_path / "gitconfig-vide").write_text("", encoding="utf-8")
    depot = tmp_path / "p"
    reglages = AtelierSettings(work_dir=tmp_path / "work")
    initialiser(reglages, depot)
    assert _git(depot, "config", "--local", "user.email") == reglages.git_user_email


def test_une_identite_globale_prime_et_efface_la_notre(tmp_path, monkeypatch) -> None:
    """La personne signe, pas l'Atelier — et ce qu'on avait posé se retire."""
    globale = tmp_path / "gitconfig"
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(globale))
    globale.write_text("", encoding="utf-8")
    depot = tmp_path / "p"
    reglages = AtelierSettings(work_dir=tmp_path / "work")
    initialiser(reglages, depot)
    assert _git(depot, "config", "--local", "user.name") == reglages.git_user_name

    globale.write_text(
        "[user]" + chr(10) + "name = Nicolas" + chr(10) + "email = nicolas@exemple.fr" + chr(10),
        encoding="utf-8",
    )
    _identite(reglages, depot)
    assert _git(depot, "config", "--local", "user.name") == ""
    assert _git(depot, "config", "--local", "user.email") == ""
    assert _git(depot, "config", "user.email") == "nicolas@exemple.fr"


def test_une_identite_locale_choisie_par_la_personne_reste(tmp_path, monkeypatch) -> None:
    globale = tmp_path / "gitconfig"
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(globale))
    globale.write_text("[user]" + chr(10) + "email = g@exemple.fr" + chr(10), encoding="utf-8")
    depot = tmp_path / "p"
    reglages = AtelierSettings(work_dir=tmp_path / "work")
    initialiser(reglages, depot)
    _git(depot, "config", "--local", "user.email", "moi@exemple.fr")
    _identite(reglages, depot)
    assert _git(depot, "config", "--local", "user.email") == "moi@exemple.fr"


def test_le_gitignore_ecrit_par_l_atelier_ignore_ce_qu_il_depose(tmp_path) -> None:
    depot = tmp_path / "p"
    depot.mkdir()
    assert completer_le_gitignore(depot) == list(LIGNES_DE_L_ATELIER)
    lignes = (depot / ".gitignore").read_text(encoding="utf-8").splitlines()
    for attendue in LIGNES_DE_L_ATELIER:
        assert attendue in lignes
    assert completer_le_gitignore(depot) == [], "rien à ajouter la seconde fois"


def test_un_gitignore_ancien_recoit_seulement_ce_qui_lui_manque(tmp_path) -> None:
    """Le reste du fichier appartient au projet : on n'y touche pas."""
    depot = tmp_path / "p"
    depot.mkdir()
    ancien = "# à moi" + chr(10) + ".venv/" + chr(10) + ".atelier/" + chr(10)
    (depot / ".gitignore").write_text(ancien, encoding="utf-8")
    ajoutees = completer_le_gitignore(depot)
    assert ".vscode/" in ajoutees and ".atelier/" not in ajoutees
    contenu = (depot / ".gitignore").read_text(encoding="utf-8")
    assert contenu.startswith(ancien)
    assert contenu.count(".atelier/") == 1
