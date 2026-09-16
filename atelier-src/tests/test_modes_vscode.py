"""Le mode de travail doit être le même des deux côtés de la vitre.

Une conversation réglée dans l'Atelier sur « Demande » — l'agent s'arrête et
demande avant d'écrire — repartait dans VS Code sous le mode par défaut du CLI.
Rien ne le disait : ni l'onglet de l'Atelier, qui affichait toujours « Demande »,
ni VS Code, qui n'affiche pas d'où lui vient son mode. La précaution prise d'un
côté ne valait pas de l'autre.

Deux limites subsistent, et ces tests les nomment plutôt que de les taire :
le réglage de l'extension vaut pour le dossier, non pour la conversation, et
son manifeste ne connaît pas notre mode `auto`.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from mcp_gateway.atelier.vscode_bridge import folder_abs
from mcp_gateway.atelier.vscode_handoff import (
    ecrire_mode_du_dossier,
    ecrire_mode_machine,
    mode_pour_extension,
    write_vscode_workspace_config,
)

from test_canal_decision import _cle


def test_les_modes_que_vs_code_connait_passent_tels_quels() -> None:
    for mode in ("plan", "manual", "acceptEdits", "bypassPermissions"):
        assert mode_pour_extension(mode) == mode


def test_le_mode_auto_ne_se_traduit_pas() -> None:
    """Il n'a pas d'équivalent dans l'extension : mieux vaut rien qu'à peu près.

    Mesuré : à qui lui demande d'écrire un fichier, `auto` demande
    l'autorisation là où `acceptEdits` écrit sans rien demander. Le traduire
    ainsi accorderait donc une écriture que personne n'a accordée. Il passe par
    le défaut du CLI, qui le connaît sous son vrai nom.
    """
    assert mode_pour_extension("auto") == ""
    assert mode_pour_extension("") == ""
    assert mode_pour_extension(None) == ""
    assert mode_pour_extension("dontAsk") == ""


def _machine(donnees: Path) -> dict:
    return json.loads((donnees / "Machine/settings.json").read_text(encoding="utf-8"))


def test_le_mode_est_ecrit_la_ou_l_extension_le_lit(tmp_path: Path, reglages, monkeypatch) -> None:
    """Portée machine : écrit dans le dossier, VS Code l'ignorait et affichait « Manual »."""
    monkeypatch.setenv("ATELIER_CODE_SERVER_DATA", str(tmp_path / "cs"))
    assert ecrire_mode_machine(reglages, "plan") == "plan"
    assert _machine(tmp_path / "cs")["claudeCode.initialPermissionMode"] == "plan"


def test_sans_mode_de_conversation_le_mode_du_service(tmp_path: Path, reglages, monkeypatch) -> None:
    monkeypatch.setenv("ATELIER_CODE_SERVER_DATA", str(tmp_path / "cs"))
    ecrire_mode_machine(reglages)
    assert _machine(tmp_path / "cs")["claudeCode.initialPermissionMode"] == reglages.permission_mode


def test_le_mode_ne_chasse_pas_les_autres_reglages_machine(tmp_path: Path, reglages, monkeypatch) -> None:
    donnees = tmp_path / "cs"
    (donnees / "Machine").mkdir(parents=True)
    (donnees / "Machine/settings.json").write_text('{"editor.fontSize": 15}', encoding="utf-8")
    monkeypatch.setenv("ATELIER_CODE_SERVER_DATA", str(donnees))
    ecrire_mode_machine(reglages, "manual")
    ecrit = _machine(donnees)
    assert ecrit["editor.fontSize"] == 15
    assert ecrit["claudeCode.initialPermissionMode"] == "manual"


def test_un_mode_intraduisible_retire_la_cle(tmp_path: Path, reglages, monkeypatch) -> None:
    """Écrire une valeur hors de l'énumération ferait rejeter tout le fichier."""
    monkeypatch.setenv("ATELIER_CODE_SERVER_DATA", str(tmp_path / "cs"))
    ecrire_mode_machine(reglages, "plan")
    ecrire_mode_machine(reglages, "auto")
    assert "claudeCode.initialPermissionMode" not in _machine(tmp_path / "cs")


def test_le_dossier_ne_porte_plus_un_mode_ignore(tmp_path: Path, reglages) -> None:
    """Une valeur que l'extension ignore laisserait croire que le mode passe."""
    write_vscode_workspace_config(reglages, "essai", tmp_path, "plan")
    ecrit = json.loads((tmp_path / ".vscode/settings.json").read_text(encoding="utf-8"))
    assert "claudeCode.initialPermissionMode" not in ecrit


def test_ouvrir_vs_code_emporte_le_mode_de_la_conversation(
    atelier: TestClient, tmp_path: Path, monkeypatch
) -> None:
    """De bout en bout : le mode réglé sur l'onglet arrive dans le dossier."""
    # La porte VS Code commence par miroiter ~/.claude avec le disque durable.
    # Sur un poste de développement, ce dossier est celui de qui lance la suite :
    # on le déplace ailleurs le temps du test, sinon on copierait ses vraies
    # conversations dans un répertoire temporaire — et l'inverse.
    monkeypatch.setattr(
        "mcp_gateway.atelier.claude_home.home_claude_dir", lambda: tmp_path / "faux-home"
    )
    monkeypatch.setenv("ATELIER_CODE_SERVER_DATA", str(tmp_path / "cs"))
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    sid = atelier.post(
        "/v1/sessions",
        headers=entete,
        json={"slug": "essai", "title": "Modes"},
    ).json()["session_id"]
    atelier.patch(
        f"/v1/sessions/{sid}", headers=entete, json={"permission_mode": "acceptEdits"}
    )

    r = atelier.get(f"/v1/vscode/open?session={sid}", headers=entete, follow_redirects=False)
    assert r.status_code == 302

    dossier = Path(folder_abs(atelier.app.state.settings, "essai"))
    assert _machine(tmp_path / "cs")["claudeCode.initialPermissionMode"] == "acceptEdits"
    # Et le même mode dans le fichier que le CLI résout : les deux chemins
    # disent la même chose, faute de quoi ils se contrediraient en silence.
    assert _defaut(dossier) == "acceptEdits"


def _defaut(dossier: Path) -> object:
    fichier = dossier / ".claude/settings.local.json"
    if not fichier.is_file():
        return None
    return json.loads(fichier.read_text(encoding="utf-8")).get("permissions", {}).get(
        "defaultMode"
    )


def test_le_mode_auto_passe_par_le_defaut_du_cli(tmp_path: Path) -> None:
    """Le seul mode que l'extension ignore, et de loin le plus courant.

    Sur le pod, trois des cinq dernières conversations étaient en `auto`.
    Sans ce chemin, la concordance n'aurait donc pas eu lieu là où elle
    manquait le plus.
    """
    ecrire_mode_du_dossier(tmp_path, "auto")
    assert _defaut(tmp_path) == "auto"


def test_manual_se_dit_default_au_cli(tmp_path: Path) -> None:
    """Le CLI ne connaît pas `manual` sous ce nom dans ce fichier-là."""
    ecrire_mode_du_dossier(tmp_path, "manual")
    assert _defaut(tmp_path) == "default"


def test_un_mode_inconnu_n_ecrit_rien(tmp_path: Path) -> None:
    """Une valeur hors énumération ferait rejeter le fichier entier."""
    ecrire_mode_du_dossier(tmp_path, "n-importe-quoi")
    ecrire_mode_du_dossier(tmp_path, "")
    assert not (tmp_path / ".claude/settings.local.json").exists()


def test_le_mode_ne_chasse_pas_ce_qui_etait_deja_la(tmp_path: Path) -> None:
    """Ce fichier porte aussi les autorisations retenues par l'utilisateur."""
    fichier = tmp_path / ".claude/settings.local.json"
    fichier.parent.mkdir(parents=True)
    fichier.write_text(
        json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}, "hooks": {"x": 1}}),
        encoding="utf-8",
    )

    ecrire_mode_du_dossier(tmp_path, "plan")
    garde = json.loads(fichier.read_text(encoding="utf-8"))
    assert garde["permissions"]["allow"] == ["Bash(ls:*)"]
    assert garde["permissions"]["defaultMode"] == "plan"
    assert garde["hooks"] == {"x": 1}


def test_un_fichier_illisible_ne_bloque_pas_l_ouverture(tmp_path: Path) -> None:
    """Mieux vaut repartir d'un fichier neuf que refuser d'ouvrir VS Code."""
    fichier = tmp_path / ".claude/settings.local.json"
    fichier.parent.mkdir(parents=True)
    fichier.write_text("{ceci n'est pas du json", encoding="utf-8")

    ecrire_mode_du_dossier(tmp_path, "plan")
    assert _defaut(tmp_path) == "plan"
