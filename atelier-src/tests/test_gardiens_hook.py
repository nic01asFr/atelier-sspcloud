"""Hook `PreToolUse` du socle : ce qu'il refuse, ce qu'il laisse passer, et sa pose."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_gateway.atelier.claude_home import fusionner_les_reglages
from mcp_gateway.gardiens.garde_bash import MODULE, commande_du_hook, poser, raison_de_refus

REFUSEES = [
    'pkill -f "server.mjs"',
    "pkill -f server.mjs",
    "pkill node",
    "sudo pkill -9 -f uvicorn",
    "cd /x && pkill -f 'python -m http'",
    "killall node",
    "kill $(pgrep -f server.mjs)",
    "pgrep -f uvicorn | xargs kill -9",
    "python -m http.server 8000",
    "python3 -m http.server 9000 --directory site",
    "uvicorn app:app --host 0.0.0.0 --port 8000",
    "python -m uvicorn app:app --host=0.0.0.0",
    "flask run --host 0.0.0.0",
    "HOST=0.0.0.0 npm start",
    "node server.js --listen 0.0.0.0",
    "jupyter lab --ip 0.0.0.0",
    "gunicorn -b 0.0.0.0:8000 app:app",
]
ACCEPTEES = [
    "ls -la",
    'kill "$(cat run.pid)"',
    "kill 12345",
    "pkill -f '^python3 -m monservice --port 8123$'",
    "pkill -F run.pid",
    "pgrep -f server.mjs",
    "python -m http.server 8000 -b 127.0.0.1",
    "uvicorn app:app --host 127.0.0.1 --port 8000",
    "~/work/bin/atelier-relancer",
    "git commit -m 'Refuser pkill dans le hook'",
    "curl -s http://127.0.0.1:3777/api/health",
    "grep -rn 0.0.0.0 docs/",
]


@pytest.mark.parametrize("commande", REFUSEES)
def test_refuse(commande: str) -> None:
    assert raison_de_refus(commande), commande


@pytest.mark.parametrize("commande", ACCEPTEES)
def test_accepte(commande: str) -> None:
    assert raison_de_refus(commande) is None, commande


def appeler_le_hook(appel: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", MODULE],
        input=json.dumps(appel),
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(Path(__file__).resolve().parents[1]),
    )


def test_le_hook_bloque_en_code_2_avec_une_raison_lisible() -> None:
    fini = appeler_le_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": 'pkill -f "server.mjs"'}})
    assert fini.returncode == 2
    assert "Tue par PID" in fini.stderr and "wikichat" in fini.stderr
    fini = appeler_le_hook({"tool_name": "Bash", "tool_input": {"command": "uvicorn app:app --host 0.0.0.0"}})
    assert fini.returncode == 2 and "127.0.0.1" in fini.stderr


def test_le_hook_laisse_passer_le_reste_sans_rien_dire() -> None:
    for appel in (
        {"tool_name": "Bash", "tool_input": {"command": "ls"}},
        {"tool_name": "Write", "tool_input": {"file_path": "x", "content": "pkill -f x"}},
        {},
    ):
        fini = appeler_le_hook(appel)
        assert fini.returncode == 0 and fini.stdout == "" and fini.stderr == ""


REGLAGES_WIKICHAT = {
    "model": "qwen3-6-35b-moe",
    "hooks": {
        "SessionStart": [{"matcher": "", "hooks": [{"type": "command", "command": "node /w/wikichat/scripts/wikichat-hook.mjs session-start"}]}],
        "PreToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "node /w/wikichat/scripts/wikichat-hook.mjs pre"}]}],
    },
}


def test_pose_sans_toucher_aux_hooks_de_wikichat_et_idempotente(tmp_path: Path) -> None:
    chemin = tmp_path / "settings.json"
    chemin.write_text(json.dumps(REGLAGES_WIKICHAT))
    assert poser(chemin, "/usr/bin/python3") == "posé"
    donnees = json.loads(chemin.read_text())
    assert donnees["model"] == "qwen3-6-35b-moe"
    assert donnees["hooks"]["SessionStart"] == REGLAGES_WIKICHAT["hooks"]["SessionStart"]
    pre = donnees["hooks"]["PreToolUse"]
    assert pre[0] == REGLAGES_WIKICHAT["hooks"]["PreToolUse"][0]
    assert pre[1] == {"matcher": "Bash", "hooks": [{"type": "command", "command": commande_du_hook("/usr/bin/python3"), "timeout": 10}]}
    assert pre[1]["hooks"][0]["command"].startswith("PYTHONPATH=")
    assert "wikichat" not in pre[1]["hooks"][0]["command"]
    assert poser(chemin, "/usr/bin/python3") == "déjà posé"
    assert poser(chemin, "/opt/python/bin/python3") == "mis à jour"
    assert sum(MODULE in json.dumps(g) for g in json.loads(chemin.read_text())["hooks"]["PreToolUse"]) == 1


def _bash() -> str | None:
    """Un shell POSIX pour lancer la commande telle que Claude Code la lance."""
    import shutil

    return shutil.which("bash") or shutil.which("sh")


@pytest.mark.skipif(_bash() is None, reason="pas de shell POSIX")
def test_la_commande_posee_bloque_depuis_un_dossier_quelconque(tmp_path: Path) -> None:
    """Audit G2 : la commande posée, lancée depuis un dossier de projet, rend le code 2.

    Pas de PYTHONPATH hérité : c'est la commande seule qui doit trouver le paquet.
    """
    projet = tmp_path / "un-projet"
    projet.mkdir()
    # Ni PYTHONPATH hérité, ni paquet homonyme installé chez l'utilisateur :
    # comme sur le pod, rien d'autre que la commande ne dit où est le code.
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONNOUSERSITE"] = "1"
    appel = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "killall node"}}
    fini = subprocess.run(
        [_bash(), "-c", commande_du_hook(sys.executable)],
        input=json.dumps(appel),
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(projet),
        env=env,
    )
    assert fini.returncode == 2, fini.stderr
    assert "Tue par PID" in fini.stderr
    # La même commande sans son PYTHONPATH : l'échec non bloquant d'avant.
    nu = subprocess.run(
        [sys.executable, "-m", MODULE],
        input=json.dumps(appel),
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(projet),
        env=env,
    )
    assert nu.returncode == 1 and "ModuleNotFoundError" in nu.stderr


def test_pose_ne_cree_ni_n_ecrase_un_fichier_absent_ou_illisible(tmp_path: Path) -> None:
    assert "rien posé" in poser(tmp_path / "absent.json")
    assert not (tmp_path / "absent.json").exists()
    casse = tmp_path / "casse.json"
    casse.write_text("{pas du json")
    assert "rien posé" in poser(casse)
    assert casse.read_text() == "{pas du json"


def test_le_hook_survit_a_la_fusion_des_reglages_quand_wikichat_reecrit_le_fichier(tmp_path: Path) -> None:
    """wikichat réécrit par renommage un fichier sans notre hook : la fusion de l'Atelier le garde."""
    volume = tmp_path / "volume.json"
    volume.write_text(json.dumps(REGLAGES_WIKICHAT))
    poser(volume, "/usr/bin/python3")
    du_volume = json.loads(volume.read_text())
    ecrit_par_wikichat = json.loads(json.dumps(REGLAGES_WIKICHAT))
    fusion = fusionner_les_reglages(ecrit_par_wikichat, du_volume)
    commandes = [h["command"] for g in fusion["hooks"]["PreToolUse"] for h in g["hooks"]]
    assert commande_du_hook("/usr/bin/python3") in commandes
    assert "node /w/wikichat/scripts/wikichat-hook.mjs pre" in commandes


@pytest.mark.skipif(os.name != "posix", reason="lien symbolique")
def test_la_pose_suit_le_lien_et_le_laisse_en_place(tmp_path: Path) -> None:
    volume = tmp_path / "work" / ".claude" / "settings.json"
    volume.parent.mkdir(parents=True)
    volume.write_text(json.dumps(REGLAGES_WIKICHAT))
    lien = tmp_path / "home" / ".claude" / "settings.json"
    lien.parent.mkdir(parents=True)
    lien.symlink_to(volume)
    assert poser(lien) == "posé"
    assert lien.is_symlink()
    assert MODULE in volume.read_text()
