"""Partir avec un effort que chaque modèle de la passerelle accepte, partout.

Mesuré le 16 septembre 2026, CLI 2.1.273, repli neutralisé, sur chacun des trois
modèles servis :

    qwen3-6-35b-moe   low ok   medium ok   high ok     xhigh ok
    gemma4-26b-moe    low ok   medium ok   high ok     xhigh ok
    qwen3-8-27b       low ok   medium ok   high REFUS  xhigh ok

Le même jour, dans VS Code, une conversation trop grosse a été refusée par le
modèle principal (fenêtre dépassée), puis par le premier repli (« 'None' has no
attribute 'split' »), puis par le second — et c'est ce dernier refus, « Unexpected
reasoning effort high », qui s'est affiché, masquant les deux autres. Notre
harnais fixait l'effort pour ses propres tours seulement ; VS Code, le terminal
et les agents de wikichat partaient avec le défaut du CLI, `high`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_gateway.atelier import harness as module
from mcp_gateway.atelier.config import (
    EFFORT_SUR_LA_PASSERELLE,
    EFFORTS_ACCEPTES_PARTOUT,
    effort_accepte_partout,
)
from mcp_gateway.atelier.harness import ClaudeHarness
from mcp_gateway.atelier.vscode_handoff import _merge_claude_settings_file

FAUX = Path(__file__).parent / "faux_claude.py"
RACINE = Path(__file__).resolve().parent.parent.parent


def test_les_niveaux_qui_passent_partout_restent() -> None:
    for niveau in ("low", "medium", "xhigh"):
        assert effort_accepte_partout(niveau) == niveau
    assert EFFORTS_ACCEPTES_PARTOUT == ("low", "medium", "xhigh")
    assert EFFORT_SUR_LA_PASSERELLE == "medium"


def test_viser_plus_haut_garde_l_intention() -> None:
    """`high` est refusé par le repli : on le relève, on ne le réduit pas."""
    assert effort_accepte_partout("high") == "xhigh"
    assert effort_accepte_partout("HIGH") == "xhigh"
    assert effort_accepte_partout("max") == "xhigh"


def test_rien_ou_n_importe_quoi_donne_le_niveau_de_la_passerelle() -> None:
    for niveau in (None, "", "  ", "turbo"):
        assert effort_accepte_partout(niveau) == EFFORT_SUR_LA_PASSERELLE


def _reglages_ecrits(reglages, chemin: Path, existant: dict | None = None) -> dict:
    reglages.llm_key_path.parent.mkdir(parents=True, exist_ok=True)
    reglages.llm_key_path.write_text("factice", encoding="utf-8")
    if existant is not None:
        chemin.write_text(json.dumps(existant), encoding="utf-8")
    _merge_claude_settings_file(chemin, reglages)
    return json.loads(chemin.read_text(encoding="utf-8"))


def test_les_reglages_partages_portent_l_effort(reglages, tmp_path: Path) -> None:
    """C'est ce fichier que lisent VS Code, le terminal et les agents de wikichat."""
    ecrit = _reglages_ecrits(reglages, tmp_path / "settings.json")
    assert ecrit["effortLevel"] == "medium"
    assert ecrit["env"]["CLAUDE_CODE_EFFORT_LEVEL"] == "medium"


def test_un_high_deja_ecrit_est_releve(reglages, tmp_path: Path) -> None:
    ecrit = _reglages_ecrits(reglages, tmp_path / "settings.json", {"effortLevel": "high"})
    assert ecrit["effortLevel"] == "xhigh"
    assert ecrit["env"]["CLAUDE_CODE_EFFORT_LEVEL"] == "xhigh"


def test_un_choix_qui_passe_partout_est_garde(reglages, tmp_path: Path) -> None:
    """Ce que la personne a réglé dans VS Code lui appartient, tant qu'il passe."""
    ecrit = _reglages_ecrits(reglages, tmp_path / "settings.json", {"effortLevel": "low"})
    assert ecrit["effortLevel"] == "low"


def test_sans_choix_ecrit_le_reglage_du_service_prime(reglages, tmp_path: Path) -> None:
    reglages.effort = "xhigh"
    ecrit = _reglages_ecrits(reglages, tmp_path / "settings.json")
    assert ecrit["effortLevel"] == "xhigh"


def test_le_harnais_releve_un_effort_de_service_refuse(reglages) -> None:
    reglages.effort = "high"
    assert ClaudeHarness(reglages)._env()["CLAUDE_CODE_EFFORT_LEVEL"] == "xhigh"


def test_une_conversation_en_high_part_en_xhigh(reglages, monkeypatch: pytest.MonkeyPatch) -> None:
    """La fiche garde `high` ; la ligne de commande porte ce que le repli accepte."""
    vues: list[list[str]] = []
    vrai_popen = subprocess.Popen

    def popen(cmd, **kw):
        vues.append(list(cmd))
        return vrai_popen([sys.executable, str(FAUX)], **kw)

    monkeypatch.setattr(module.subprocess, "Popen", popen)
    monkeypatch.setattr(ClaudeHarness, "_resolve_claude_bin", lambda self: FAUX)
    reglages.cli_processus_vivant = False
    h = ClaudeHarness(reglages)
    base = reglages.work_dir
    h.run_turn(
        "s1", "bonjour", cwd=base / "p", model=None, resume=False,
        transcript_path=base / "t.jsonl", log_path=base / "l.log", timeout_s=30,
        permission_mode="acceptEdits", effort="high",
    )
    cmd = vues[0]
    assert cmd[cmd.index("--effort") + 1] == "xhigh"


def test_l_installation_ecrit_l_effort() -> None:
    texte = (RACINE / "install" / "atelier-init.sh").read_text(encoding="utf-8")
    assert '"effortLevel": "medium"' in texte
    assert '"CLAUDE_CODE_EFFORT_LEVEL": "medium"' in texte


def test_le_service_pose_les_reglages_partages_au_demarrage() -> None:
    """Sans cela, seul un VS Code ouvert par l'Atelier les recevait."""
    api = (RACINE / "atelier-src" / "mcp_gateway" / "atelier" / "api.py").read_text(encoding="utf-8")
    debut = api.index("async def lifespan")
    assert "write_claude_settings_env(settings)" in api[debut : debut + 1500]
