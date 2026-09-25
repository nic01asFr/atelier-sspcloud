"""gemma4-26b-moe n'est plus ni au créneau opus ni parmi les replis.

Mesuré le 25 septembre 2026 : il échoue dès le premier tour de Claude Code
(« 'None' has no attribute 'split' »). Au créneau opus ou en repli, il faisait
tomber une conversation au moment précis où l'on changeait de modèle.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp_gateway.atelier.config import MODELE_PRINCIPAL
from mcp_gateway.atelier.models_catalog import list_available_models
from mcp_gateway.atelier.vscode_handoff import _merge_claude_settings_file

INIT = Path(__file__).resolve().parents[2] / "install" / "atelier-init.sh"


def test_un_pod_ancien_est_corrige(reglages, tmp_path: Path) -> None:
    reglages.llm_key_path.parent.mkdir(parents=True, exist_ok=True)
    reglages.llm_key_path.write_text("factice", encoding="utf-8")
    chemin = tmp_path / "settings.json"
    chemin.write_text(
        json.dumps(
            {
                "model": "qwen3-6-35b-moe",
                "fallbackModel": ["gemma4-26b-moe", "qwen3-8-27b"],
                "env": {
                    "ANTHROPIC_DEFAULT_OPUS_MODEL": "gemma4-26b-moe",
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "qwen3-8-27b",
                },
            }
        ),
        encoding="utf-8",
    )
    _merge_claude_settings_file(chemin, reglages)
    ecrit = json.loads(chemin.read_text(encoding="utf-8"))
    assert ecrit["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] == MODELE_PRINCIPAL == "qwen3-6-35b-moe"
    assert ecrit["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "qwen3-8-27b"
    assert ecrit["fallbackModel"] == ["qwen3-8-27b"]
    assert "gemma4-26b-moe" not in json.dumps(ecrit)


def test_le_choix_des_modeles_ne_propose_plus_gemma(reglages, tmp_path: Path, monkeypatch) -> None:
    """L'interface lit les créneaux dans le fichier corrigé."""
    maison = tmp_path / "maison"
    (maison / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(maison))
    monkeypatch.setenv("USERPROFILE", str(maison))
    reglages.llm_key_path.parent.mkdir(parents=True, exist_ok=True)
    reglages.llm_key_path.write_text("factice", encoding="utf-8")
    chemin = maison / ".claude" / "settings.json"
    chemin.write_text(
        json.dumps({"fallbackModel": ["gemma4-26b-moe"], "env": {"ANTHROPIC_DEFAULT_OPUS_MODEL": "gemma4-26b-moe"}}),
        encoding="utf-8",
    )
    _merge_claude_settings_file(chemin, reglages)
    ids = [m["id"] for m in list_available_models(reglages)["models"]]
    assert "gemma4-26b-moe" not in ids


def test_l_installation_ne_le_pose_plus() -> None:
    """Un pod neuf : créneau opus et replis par défaut, sans gemma."""
    texte = INIT.read_text(encoding="utf-8")
    lignes = [l for l in texte.splitlines() if l.startswith(("MODELE_OPUS=", "MODELES_DE_REPLI="))]
    assert lignes == [
        'MODELE_OPUS="${ATELIER_MODELE_OPUS:-qwen3-6-35b-moe}"',
        'MODELES_DE_REPLI="${ATELIER_MODELES_DE_REPLI:-qwen3-8-27b}"',
    ]
    assert '"ANTHROPIC_DEFAULT_OPUS_MODEL": "$MODELE_OPUS"' in texte
