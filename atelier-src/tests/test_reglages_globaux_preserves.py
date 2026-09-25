"""Le `.claude/settings.json` d'un projet n'écrase jamais le réglage global.

`vscode_handoff.sync_claude_home` le recopiait sur `~/.claude/settings.json` à
chaque ouverture dans VS Code : modèle, `apiKeyHelper`, crochets et adresse du
relais devenaient ceux du dernier projet ouvert, pour toutes les surfaces.
Claude Code lit de lui-même le réglage du dossier où il tourne.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp_gateway.atelier.claude_home import sync_claude_home as synchroniser
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.vscode_handoff import prepare_vscode_handoff, sync_claude_home

GLOBAL = {"model": "qwen3-6-35b-moe", "hooks": {"Stop": []}, "env": {"A": "global"}}
PROJET = {"model": "autre", "permissions": {"allow": ["Bash(rm:*)"]}, "env": {"A": "projet"}}


def _poser(reglages: AtelierSettings, slug: str) -> tuple[Path, Path]:
    globale = Path.home() / ".claude" / "settings.json"
    globale.parent.mkdir(parents=True, exist_ok=True)
    globale.write_text(json.dumps(GLOBAL), encoding="utf-8")
    projet = reglages.projects_dir / slug / ".claude" / "settings.json"
    projet.parent.mkdir(parents=True, exist_ok=True)
    projet.write_text(json.dumps(PROJET), encoding="utf-8")
    return globale, projet


def test_la_synchronisation_ne_propage_pas_le_projet(reglages: AtelierSettings) -> None:
    globale, _ = _poser(reglages, "p")
    sync_claude_home(reglages, "p")
    lu = json.loads(globale.read_text(encoding="utf-8"))
    assert lu["model"] == "qwen3-6-35b-moe" and lu["env"]["A"] == "global"
    assert "permissions" not in lu
    durable = reglages.work_dir / ".claude" / "settings.json"
    assert "Bash(rm:*)" not in durable.read_text(encoding="utf-8")


def test_l_ouverture_dans_vscode_non_plus(reglages: AtelierSettings) -> None:
    globale, projet = _poser(reglages, "p")
    reglages.llm_key_path.parent.mkdir(parents=True, exist_ok=True)
    reglages.llm_key_path.write_text("factice", encoding="utf-8")
    prepare_vscode_handoff(reglages, "p", "conv-1", reglages.projects_dir / "p")
    lu = json.loads(globale.read_text(encoding="utf-8"))
    assert lu["model"] == "qwen3-6-35b-moe"
    assert "permissions" not in lu and lu["env"]["A"] == "global"
    # Le réglage du projet, lui, reste où il est et tel qu'il est.
    assert json.loads(projet.read_text(encoding="utf-8")) == PROJET


def test_la_synchronisation_pvc_home_ne_regarde_pas_les_projets(reglages: AtelierSettings) -> None:
    _poser(reglages, "p")
    synchroniser(reglages)
    for chemin in (Path.home() / ".claude", reglages.work_dir / ".claude"):
        texte = "".join(
            f.read_text(encoding="utf-8", errors="replace") for f in chemin.rglob("*.json")
        )
        assert "Bash(rm:*)" not in texte
