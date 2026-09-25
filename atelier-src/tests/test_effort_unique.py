"""L'effort n'a qu'une source : `CLAUDE_CODE_EFFORT_LEVEL` (mesures de la vague 1)."""

from __future__ import annotations

import json
from pathlib import Path

from mcp_gateway.atelier.config import AtelierSettings


# ── L'effort n'a qu'une source ──────────────────────────────────────────


def test_l_effort_par_modele_est_retire_des_reglages(tmp_path: Path) -> None:
    from mcp_gateway.atelier.vscode_handoff import _merge_claude_settings_file

    reglages = AtelierSettings(work_dir=tmp_path / "work")
    reglages.llm_key_path.parent.mkdir(parents=True, exist_ok=True)
    reglages.llm_key_path.write_text("cle", encoding="utf-8")
    chemin = tmp_path / "settings.json"
    chemin.write_text(
        json.dumps(
            {
                "modelSettings": {
                    "qwen3-6-35b-moe": {"effortLevel": "xhigh"},
                    "qwen3-8-27b": {"effortLevel": "xhigh", "autre": 1},
                },
                "effortLevel": "medium",
            }
        ),
        encoding="utf-8",
    )
    _merge_claude_settings_file(chemin, reglages)
    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    assert donnees["modelSettings"] == {"qwen3-8-27b": {"autre": 1}}
    assert donnees["env"]["CLAUDE_CODE_EFFORT_LEVEL"] == "medium"

    chemin.write_text(json.dumps({"modelSettings": {"qwen3-6-35b-moe": {"effortLevel": "xhigh"}}}), encoding="utf-8")
    _merge_claude_settings_file(chemin, reglages)
    assert "modelSettings" not in json.loads(chemin.read_text(encoding="utf-8"))


