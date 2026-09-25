"""L'enveloppeur du `claude` de l'extension VS Code : plus de secret dans code-server.

`claudeCode.environmentVariables` portait en clair, dans les réglages de
code-server, les valeurs des références `${ATELIER_MCP_…}`. L'extension connaît
`claudeCode.claudeProcessWrapper` (portée machine) : elle lance alors
`<enveloppeur> <binaire claude> <arguments>`. `bin/atelier-claude-vscode` source
`~/work/.secrets/claude-env.sh` puis `exec "$@"` ; l'Atelier pose le réglage et
retire les valeurs des réglages.

L'essai avec la vraie extension (processus `claude` lancé par VS Code, variables
vues dans `/proc/<pid>/environ`) est une vérification du déploiement
(docs/coherence-projet.md, « Déploiement du 26/09 »).
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.env_secrets import chemin_du_fichier
from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
from mcp_gateway.atelier.vscode_handoff import (
    CLE_ENVELOPPEUR,
    CLE_ENVIRONNEMENT,
    ENVELOPPEUR,
    ecrire_mode_machine,
    enveloppeur_vscode,
    environnement_du_claude_vscode,
    write_user_code_server_settings,
)
from mcp_gateway.db import connect

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / ENVELOPPEUR
INIT = Path(__file__).resolve().parents[2] / "install" / "atelier-init.sh"
JETON = "jeton-onyxia-0123456789abcdef"
VARIABLE = "ATELIER_MCP_ONYXIA_AUTHORIZATION"
CLE = "cle-proprietaire-0123456789"

shell_posix = pytest.mark.skipif(
    os.name == "nt" or shutil.which("sh") is None, reason="enveloppeur shell : pod Linux"
)


def _preparer(reglages: AtelierSettings) -> None:
    conn = connect(reglages.gateway_db_path)
    try:
        IntegratedMcpStore(conn).upsert(
            "Onyxia",
            {
                "type": "http",
                "url": "https://passerelle.exemple/mcp",
                "headers": {"Authorization": f"Bearer {JETON}"},
            },
        )
    finally:
        conn.close()
    reglages.owner_key_path.parent.mkdir(parents=True, exist_ok=True)
    reglages.owner_key_path.write_text(CLE, encoding="utf-8")


def _code_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    donnees = tmp_path / "code-server"
    monkeypatch.setenv("ATELIER_CODE_SERVER_DATA", str(donnees))
    return donnees


# --- ce que l'Atelier écrit -------------------------------------------------


def test_les_reglages_de_code_server_ne_portent_plus_de_secret(
    reglages: AtelierSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    donnees = _code_server(tmp_path, monkeypatch)
    _preparer(reglages)
    write_user_code_server_settings(reglages)
    for fichier in (donnees / "User/settings.json", donnees / "Machine/settings.json"):
        texte = fichier.read_text(encoding="utf-8")
        assert JETON not in texte and CLE not in texte, fichier
    utilisateur = json.loads((donnees / "User/settings.json").read_text(encoding="utf-8"))
    noms = {e["name"] for e in utilisateur[CLE_ENVIRONNEMENT]}
    assert "ANTHROPIC_BASE_URL" in noms
    assert not any(n.startswith("ATELIER_MCP_") for n in noms)


def test_l_enveloppeur_est_pose_et_designe_des_deux_portees(
    reglages: AtelierSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    donnees = _code_server(tmp_path, monkeypatch)
    write_user_code_server_settings(reglages)
    pose = enveloppeur_vscode(reglages)
    assert pose == reglages.work_dir / "bin" / "atelier-claude-vscode"
    assert pose.read_bytes() == SCRIPT.read_bytes()
    if os.name != "nt":
        assert pose.stat().st_mode & stat.S_IXUSR
    for portee in ("User", "Machine"):
        lu = json.loads((donnees / portee / "settings.json").read_text(encoding="utf-8"))
        assert lu[CLE_ENVELOPPEUR] == str(pose), portee


def test_un_enveloppeur_perime_est_remplace(
    reglages: AtelierSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _code_server(tmp_path, monkeypatch)
    pose = enveloppeur_vscode(reglages)
    pose.parent.mkdir(parents=True, exist_ok=True)
    pose.write_text("#!/bin/sh\nexec \"$@\"\n", encoding="utf-8")
    write_user_code_server_settings(reglages)
    assert pose.read_bytes() == SCRIPT.read_bytes()


def test_les_reglages_machine_gardent_le_mode_et_perdent_les_secrets(
    reglages: AtelierSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un fichier machine écrit à la main avec des valeurs en est purgé, le reste gardé."""
    donnees = _code_server(tmp_path, monkeypatch)
    _preparer(reglages)
    ecrire_mode_machine(reglages, "plan")
    machine = donnees / "Machine/settings.json"
    lu = json.loads(machine.read_text(encoding="utf-8"))
    lu[CLE_ENVIRONNEMENT] = [
        {"name": VARIABLE, "value": JETON},
        {"name": "ATELIER_MCP_KEY", "value": CLE},
        {"name": "HTTP_PROXY", "value": "http://mandataire:3128"},
    ]
    machine.write_text(json.dumps(lu), encoding="utf-8")
    write_user_code_server_settings(reglages)
    apres = json.loads(machine.read_text(encoding="utf-8"))
    assert apres["claudeCode.initialPermissionMode"] == "plan"
    assert apres[CLE_ENVIRONNEMENT] == [{"name": "HTTP_PROXY", "value": "http://mandataire:3128"}]
    assert JETON not in machine.read_text(encoding="utf-8")
    # Et le mode, réécrit ensuite, ne retire pas l'enveloppeur.
    ecrire_mode_machine(reglages, "acceptEdits")
    assert CLE_ENVELOPPEUR in json.loads(machine.read_text(encoding="utf-8"))


def test_le_processus_recoit_les_valeurs_par_l_enveloppeur(
    reglages: AtelierSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _code_server(tmp_path, monkeypatch)
    _preparer(reglages)
    env = environnement_du_claude_vscode(reglages)
    assert env[VARIABLE] == JETON
    assert env["ATELIER_MCP_KEY"] == CLE
    assert "ANTHROPIC_BASE_URL" in env


def test_sans_enveloppeur_aucun_reglage_ne_designe_un_fichier_absent(
    reglages: AtelierSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si le script source manque, le réglage n'est pas posé : l'extension lance encore claude."""
    donnees = _code_server(tmp_path, monkeypatch)
    import mcp_gateway.atelier.vscode_handoff as module

    monkeypatch.setattr(module, "_SOURCE_ENVELOPPEUR", tmp_path / "absent")
    write_user_code_server_settings(reglages)
    for portee in ("User", "Machine"):
        lu = json.loads((donnees / portee / "settings.json").read_text(encoding="utf-8"))
        assert CLE_ENVELOPPEUR not in lu, portee


def test_l_init_copie_l_enveloppeur_dans_work_bin() -> None:
    texte = INIT.read_text(encoding="utf-8")
    ligne = next(l for l in texte.splitlines() if l.startswith("for script in "))
    assert ENVELOPPEUR in ligne.replace(";", " ").split()


# --- le script lui-même -----------------------------------------------------


def _banc(tmp_path: Path, contenu: str | None) -> Path:
    work = tmp_path / "work"
    (work / "bin").mkdir(parents=True)
    enveloppeur = work / "bin" / ENVELOPPEUR
    shutil.copy(SCRIPT, enveloppeur)
    enveloppeur.chmod(0o755)
    if contenu is not None:
        secrets = work / ".secrets"
        secrets.mkdir(mode=0o700)
        (secrets / "claude-env.sh").write_text(contenu, encoding="utf-8")
    return enveloppeur


def _lancer(enveloppeur: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(enveloppeur), *args],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", **env},
        timeout=20,
    )


@shell_posix
def test_le_script_charge_le_fichier_puis_cede_la_place(tmp_path: Path) -> None:
    enveloppeur = _banc(tmp_path, f"export {VARIABLE}='{JETON}'\nexport ATELIER_MCP_KEY='{CLE}'\n")
    fini = _lancer(enveloppeur, "sh", "-c", f'printf "%s|%s|%s" "${VARIABLE}" "$ATELIER_MCP_KEY" "$$"')
    assert fini.returncode == 0, fini.stderr
    valeur, cle, _pid = fini.stdout.split("|")
    assert valeur == JETON and cle == CLE
    assert fini.stderr == ""


@shell_posix
def test_le_script_n_affiche_rien_du_fichier(tmp_path: Path) -> None:
    """Même un fichier bavard ne pollue pas le flux du protocole."""
    enveloppeur = _banc(tmp_path, f"echo bavard\necho erreur >&2\nexport {VARIABLE}='{JETON}'\n")
    fini = _lancer(enveloppeur, "true")
    assert fini.returncode == 0
    assert fini.stdout == "" and fini.stderr == ""
    assert JETON not in fini.stdout + fini.stderr


@shell_posix
def test_le_script_sans_fichier_lance_quand_meme(tmp_path: Path) -> None:
    enveloppeur = _banc(tmp_path, None)
    fini = _lancer(enveloppeur, "sh", "-c", f'printf "[%s]" "${{{VARIABLE}:-}}"')
    assert fini.returncode == 0 and fini.stdout == "[]"


@shell_posix
def test_le_script_garde_les_arguments_et_le_code_de_sortie(tmp_path: Path) -> None:
    enveloppeur = _banc(tmp_path, "")
    fini = _lancer(enveloppeur, "sh", "-c", 'printf "%s;" "$@"; exit 7', "zero", "un deux", "--x=y z")
    assert fini.returncode == 7
    assert fini.stdout == "un deux;--x=y z;"


@shell_posix
def test_le_script_sans_commande_refuse(tmp_path: Path) -> None:
    fini = _lancer(_banc(tmp_path, ""))
    assert fini.returncode == 64
    assert "aucune commande" in fini.stderr


@shell_posix
def test_atelier_work_designe_un_autre_volume(tmp_path: Path) -> None:
    enveloppeur = _banc(tmp_path, f"export {VARIABLE}='mauvais'\n")
    autre = tmp_path / "autre"
    (autre / ".secrets").mkdir(parents=True)
    (autre / ".secrets" / "claude-env.sh").write_text(f"export {VARIABLE}='bon'\n", encoding="utf-8")
    fini = _lancer(enveloppeur, "sh", "-c", f'printf "%s" "${VARIABLE}"', ATELIER_WORK=str(autre))
    assert fini.stdout == "bon"


@shell_posix
def test_le_script_suit_le_dossier_de_secrets_de_l_atelier(
    reglages: AtelierSettings, tmp_path: Path
) -> None:
    """`~/work/secrets` s'il existe, comme `config.secrets_dir` : le fichier que l'Atelier régénère."""
    enveloppeur = _banc(tmp_path, f"export {VARIABLE}='cache'\n")
    work = enveloppeur.parents[1]
    (work / "secrets").mkdir()
    (work / "secrets" / "claude-env.sh").write_text(f"export {VARIABLE}='visible'\n", encoding="utf-8")
    assert chemin_du_fichier(AtelierSettings(work_dir=work)) == work / "secrets" / "claude-env.sh"
    fini = _lancer(enveloppeur, "sh", "-c", f'printf "%s" "${VARIABLE}"')
    assert fini.stdout == "visible"
