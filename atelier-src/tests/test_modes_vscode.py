"""Le mode de permission, le même pour l'app, VS Code et le terminal.

Contrat `docs/vision/profils-acces.md`, « Mode de permission » :

- une liste : `default`, `acceptEdits`, `plan`, `bypassPermissions` ;
- un défaut par projet (`.claude/settings.local.json`, `permissions.defaultMode`),
  que le CLI résout de lui-même ;
- un choix par conversation, dans le magasin où l'extension VS Code tient
  déjà le mode de chaque conversation (`session-permission-modes/<id>.json`) :
  l'app y écrit et y lit, l'extension aussi, l'enveloppeur le lit au terminal ;
- aucun résidu : ni mode machine imposé, ni bypass permis sans qu'un choix le
  demande, ni `bypassPermissions` recopié dans un projet.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.modes_permission import (
    CLE_BYPASS,
    CLE_MODE_INITIAL,
    dossier_des_conversations,
    ecrire_mode_de_la_conversation,
    ecrire_mode_du_projet,
    mode_de_la_conversation,
    mode_du_projet,
    mode_resolu,
    nettoyer_les_residus,
)
from mcp_gateway.atelier.vscode_bridge import folder_abs
from mcp_gateway.atelier.vscode_handoff import mode_pour_extension, write_vscode_workspace_config

from test_canal_decision import _cle

ENVELOPPEUR = Path(__file__).resolve().parents[1] / "bin" / "atelier-claude-vscode"
BASH = shutil.which("bash")


def _machine() -> dict:
    fichier = Path.home() / ".local/share/code-server/Machine/settings.json"
    return json.loads(fichier.read_text(encoding="utf-8")) if fichier.is_file() else {}


def _magasin(identifiant: str) -> dict:
    return json.loads((dossier_des_conversations() / f"{identifiant}.json").read_text(encoding="utf-8"))


def _espion(atelier: TestClient, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    vus: list[str] = []
    harnais = atelier.app.state.harness
    vrai = harnais.run_turn

    def espion(session_id, message, **kw):
        vus.append(kw.get("permission_mode", ""))
        return vrai(session_id, message, **kw)

    monkeypatch.setattr(harnais, "run_turn", espion)
    return vus


def test_les_noms_de_l_extension() -> None:
    for mode in ("plan", "default", "acceptEdits", "bypassPermissions"):
        assert mode_pour_extension(mode) == mode
    assert mode_pour_extension("manual") == "default"
    assert mode_pour_extension("auto") == ""


def test_le_choix_fait_dans_l_app_est_ecrit_la_ou_vs_code_le_lit(atelier: TestClient) -> None:
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    sid = atelier.post("/v1/sessions", headers=entete, json={"slug": "essai"}).json()["session_id"]
    r = atelier.patch(f"/v1/sessions/{sid}", headers=entete, json={"permission_mode": "plan"})
    assert r.status_code == 200 and r.json()["permission_mode"] == "plan"
    ecrit = _magasin(sid)
    assert ecrit["mode"] == "plan" and abs(ecrit["updatedAt"] - time.time() * 1000) < 60_000
    # Revenir au défaut retire le choix, plutôt que d'y écrire une valeur.
    atelier.patch(f"/v1/sessions/{sid}", headers=entete, json={"permission_mode": ""})
    assert not (dossier_des_conversations() / f"{sid}.json").exists()


def test_le_choix_fait_dans_vs_code_vaut_pour_le_tour_de_l_app(
    atelier: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    sid = atelier.post("/v1/sessions", headers=entete, json={"slug": "essai"}).json()["session_id"]
    # Ce qu'écrit l'extension quand on change de mode dans la conversation.
    dossier_des_conversations().mkdir(parents=True, exist_ok=True)
    (dossier_des_conversations() / f"{sid}.json").write_text(
        json.dumps({"mode": "plan", "updatedAt": int(time.time() * 1000)}), encoding="utf-8"
    )
    vus = _espion(atelier, monkeypatch)
    atelier.app.state.store.send(sid, "bonjour", peut_attendre=True)
    assert vus == ["plan"]
    assert atelier.get(f"/v1/sessions/{sid}", headers=entete).json()["permission_mode"] == "plan"


def test_le_defaut_du_projet_puis_le_choix_de_la_conversation(
    atelier: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    settings = atelier.app.state.settings
    sid = atelier.post("/v1/sessions", headers=entete, json={"slug": "essai"}).json()["session_id"]
    dossier = Path(folder_abs(settings, "essai"))
    ecrire_mode_du_projet(settings, dossier, "default")
    vus = _espion(atelier, monkeypatch)
    atelier.app.state.store.send(sid, "un", peut_attendre=False)
    atelier.patch(f"/v1/sessions/{sid}", headers=entete, json={"permission_mode": "acceptEdits"})
    atelier.app.state.store.send(sid, "deux", peut_attendre=False)
    assert vus == ["default", "acceptEdits"]
    assert mode_resolu(settings, dossier, sid) == ("acceptEdits", "conversation")


def test_le_bypass_n_est_permis_a_l_extension_que_tant_qu_un_choix_le_demande(
    reglages: AtelierSettings, tmp_path: Path
) -> None:
    machine = Path.home() / ".local/share/code-server/Machine/settings.json"
    machine.parent.mkdir(parents=True)
    machine.write_text(json.dumps({CLE_MODE_INITIAL: "acceptEdits", CLE_BYPASS: True, "editor.fontSize": 15}))
    nettoyer_les_residus(reglages)
    assert CLE_MODE_INITIAL not in _machine() and CLE_BYPASS not in _machine()
    assert _machine()["editor.fontSize"] == 15

    ecrire_mode_de_la_conversation(reglages, "conv-1", "bypassPermissions")
    assert _machine()[CLE_BYPASS] is True
    ecrire_mode_de_la_conversation(reglages, "conv-1", "acceptEdits")
    assert CLE_BYPASS not in _machine()

    projet = reglages.projects_dir / "p"
    projet.mkdir(parents=True)
    ecrire_mode_du_projet(reglages, projet, "bypassPermissions")
    assert _machine()[CLE_BYPASS] is True
    ecrire_mode_du_projet(reglages, projet, "")
    assert CLE_BYPASS not in _machine()


def test_ouvrir_vs_code_ne_recopie_plus_le_mode(atelier: TestClient, tmp_path: Path, monkeypatch) -> None:
    """L'ancien passage écrivait le mode de la conversation en défaut du projet et en réglage machine."""
    monkeypatch.setattr("mcp_gateway.atelier.claude_home.home_claude_dir", lambda: tmp_path / "faux-home")
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    sid = atelier.post("/v1/sessions", headers=entete, json={"slug": "essai"}).json()["session_id"]
    atelier.patch(f"/v1/sessions/{sid}", headers=entete, json={"permission_mode": "bypassPermissions"})
    r = atelier.get(f"/v1/vscode/open?session={sid}", headers=entete, follow_redirects=False)
    assert r.status_code == 302
    dossier = Path(folder_abs(atelier.app.state.settings, "essai"))
    # Le projet garde le défaut du service, posé à sa liaison : pas le bypass de la conversation.
    assert mode_du_projet(dossier) == "acceptEdits"
    assert CLE_MODE_INITIAL not in _machine()
    # Le choix est là où l'extension le lit, et le bypass lui est permis.
    assert mode_de_la_conversation(sid) == "bypassPermissions"
    assert _machine()[CLE_BYPASS] is True


def test_le_dossier_ne_porte_pas_de_mode(tmp_path: Path, reglages) -> None:
    write_vscode_workspace_config(reglages, "essai", tmp_path, "plan")
    ecrit = json.loads((tmp_path / ".vscode/settings.json").read_text(encoding="utf-8"))
    assert CLE_MODE_INITIAL not in ecrit


def test_les_residus_sont_ranges_une_fois(reglages: AtelierSettings) -> None:
    projets = reglages.projects_dir
    for nom, mode in (("sans-nom", "bypassPermissions"), ("ancien", "manual"), ("classe", "auto"), ("plan", "plan")):
        (projets / nom / ".claude").mkdir(parents=True)
        (projets / nom / ".claude/settings.local.json").write_text(
            json.dumps({"permissions": {"defaultMode": mode, "allow": ["Bash(ls:*)"]}}), encoding="utf-8"
        )
    fait = nettoyer_les_residus(reglages, [("conv-a", "manual"), ("conv-b", "")])
    assert sorted(fait["projets"]) == ["ancien", "classe", "sans-nom"]
    assert mode_du_projet(projets / "sans-nom") == "acceptEdits"  # le défaut du service
    assert mode_du_projet(projets / "ancien") == "default"
    assert mode_du_projet(projets / "plan") == "plan"
    garde = json.loads((projets / "sans-nom/.claude/settings.local.json").read_text(encoding="utf-8"))
    assert garde["permissions"]["allow"] == ["Bash(ls:*)"]
    assert mode_de_la_conversation("conv-a") == "default"
    assert mode_de_la_conversation("conv-b") == ""
    # Un bypass choisi ensuite pour un projet n'est plus retiré.
    ecrire_mode_du_projet(reglages, projets / "sans-nom", "bypassPermissions")
    nettoyer_les_residus(reglages)
    assert mode_du_projet(projets / "sans-nom") == "bypassPermissions"


def test_les_modes_des_fiches_passent_dans_le_magasin(reglages: AtelierSettings) -> None:
    reglages.sessions_dir.mkdir(parents=True, exist_ok=True)
    (reglages.sessions_dir / "s1.json").write_text(
        json.dumps({"session_id": "s1", "claude_session_id": "cli-1", "permission_mode": "plan"}), encoding="utf-8"
    )
    (reglages.sessions_dir / "s2.json").write_text(json.dumps({"session_id": "s2", "permission_mode": ""}), encoding="utf-8")
    assert nettoyer_les_residus(reglages)["conversations"] == 1
    assert mode_de_la_conversation("cli-1") == "plan"


def test_un_choix_perime_ne_compte_plus(reglages: AtelierSettings) -> None:
    """Comme l'extension : une entrée de plus de 30 jours est ignorée."""
    dossier_des_conversations().mkdir(parents=True, exist_ok=True)
    vieux = int(time.time() * 1000) - 31 * 24 * 3600 * 1000
    (dossier_des_conversations() / "vieille.json").write_text(json.dumps({"mode": "plan", "updatedAt": vieux}))
    assert mode_de_la_conversation("vieille") == ""


# --- L'enveloppeur, pour VS Code et le terminal ------------------------------


def _faux_claude(tmp_path: Path) -> Path:
    faux = tmp_path / "faux-claude"
    faux.write_text('#!/bin/sh\nfor a do printf "%s\\n" "$a"; done\n', encoding="utf-8", newline="\n")
    faux.chmod(0o755)
    return faux


def _posix(chemin: Path | str) -> str:
    return str(chemin).replace("\\", "/")


def _lancer(tmp_path: Path, *args: str, entree: str = "") -> list[str]:
    import os

    env = dict(os.environ)
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)
    env["ATELIER_WORK"] = _posix(tmp_path / "work")
    env["ATELIER_CODE_SERVER_DATA"] = _posix(Path.home() / ".local/share/code-server")
    if entree:
        env["CLAUDE_CODE_ENTRYPOINT"] = entree
    fini = subprocess.run(
        [BASH, _posix(ENVELOPPEUR), "sh", _posix(_faux_claude(tmp_path)), *args],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert fini.returncode == 0, fini.stderr
    return fini.stdout.splitlines()


@pytest.mark.skipif(BASH is None, reason="pas de bash")
def test_l_enveloppeur_applique_le_choix_de_la_conversation_reprise(reglages: AtelierSettings, tmp_path: Path) -> None:
    ecrire_mode_de_la_conversation(reglages, "conv-1", "plan")
    # VS Code : l'extension passe le mode de son état global.
    assert _lancer(tmp_path, "--resume", "conv-1", "--permission-mode", "default", entree="claude-vscode") == [
        "--resume",
        "conv-1",
        "--permission-mode",
        "plan",
    ]
    # Terminal : `claude -r conv-1`.
    assert _lancer(tmp_path, "-r", "conv-1") == ["-r", "conv-1", "--permission-mode", "plan"]


@pytest.mark.skipif(BASH is None, reason="pas de bash")
def test_sans_choix_l_extension_laisse_le_cli_resoudre_le_defaut_du_projet(tmp_path: Path) -> None:
    assert _lancer(tmp_path, "--session-id", "neuve", "--permission-mode", "default", entree="claude-vscode") == [
        "--session-id",
        "neuve",
    ]
    # Au terminal, un mode tapé sans conversation à reprendre n'est pas touché.
    assert _lancer(tmp_path, "--permission-mode", "plan", "-p", "x y") == ["--permission-mode", "plan", "-p", "x y"]


@pytest.mark.skipif(BASH is None, reason="pas de bash")
def test_l_alias_du_terminal_passe_par_l_enveloppeur(tmp_path: Path) -> None:
    bashrc = tmp_path / ".bashrc"
    script = Path(__file__).resolve().parents[1] / "bin" / "atelier-bashrc"
    args = [_posix(bashrc), "/w/.secrets/claude-env.sh", "/w/bin/atelier-claude-vscode", "/w/bin/claude"]
    for attendu in ("posé", "inchangé"):
        fini = subprocess.run([BASH, _posix(script), *args], capture_output=True, text=True)
        assert fini.stdout.strip() == attendu, fini.stderr
    texte = bashrc.read_text(encoding="utf-8")
    assert texte.count("alias claude=") == 1
    assert "alias claude='\"/w/bin/atelier-claude-vscode\" \"/w/bin/claude\"'" in texte


def test_le_defaut_du_projet_se_regle_par_l_interface(atelier: TestClient) -> None:
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    atelier.post("/v1/sessions", headers=entete, json={"slug": "essai"})
    lu = atelier.get("/v1/projets/essai/mode", headers=entete).json()
    assert lu["mode"] == "" and lu["source"] == "service" and lu["modes"] == ["default", "acceptEdits", "plan", "bypassPermissions"]
    regle = atelier.put("/v1/projets/essai/mode", headers=entete, json={"mode": "bypassPermissions"}).json()
    assert regle["mode"] == "bypassPermissions" and "Sans garde-fou" in regle["avertissement"]
    dossier = Path(folder_abs(atelier.app.state.settings, "essai"))
    assert mode_du_projet(dossier) == "bypassPermissions"
    assert _machine()[CLE_BYPASS] is True
    assert atelier.put("/v1/projets/essai/mode", headers=entete, json={"mode": "auto-magique"}).status_code == 400
    assert atelier.put("/v1/projets/../mode", headers=entete, json={"mode": "plan"}).status_code in (400, 404)
    assert atelier.put("/v1/projets/essai/mode", headers=entete, json={"mode": ""}).json()["source"] == "service"
    assert CLE_BYPASS not in _machine()


def test_le_selecteur_propose_les_quatre_modes() -> None:
    import re

    page = (Path(__file__).resolve().parents[1] / "mcp_gateway/atelier/web/index.html").read_text(encoding="utf-8")
    bloc = page[page.index('<select id="composer-mode"') : page.index("</select>", page.index('<select id="composer-mode"'))]
    assert re.findall(r'<option value="([^"]*)"', bloc) == ["", "plan", "default", "acceptEdits", "bypassPermissions"]
    script = (Path(__file__).resolve().parents[1] / "mcp_gateway/atelier/web/js/controllers/composer-input.js").read_text(encoding="utf-8")
    # Le bypass demande une confirmation avant de partir.
    assert 'mode === "bypassPermissions" && !window.confirm(AVERTISSEMENT_BYPASS)' in script
