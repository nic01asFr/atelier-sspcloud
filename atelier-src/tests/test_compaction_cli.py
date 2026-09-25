"""Ce que le CLI doit savoir pour compacter de lui-même, sur toutes les surfaces.

Le décompte de jetons venait à zéro de la passerelle : la compaction native ne
partait jamais, et l'Atelier avait posé des fenêtres étroites (30 000, 40 000)
qu'une seule main tenait. Le relais LLM rend le décompte ; le CLI reçoit donc
la vraie fenêtre du modèle, passe par le relais, et les anciens réglages sont
retirés là où ils traînent — ils feraient compacter à contretemps.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp_gateway.atelier.config import OBSOLETES, fenetre_minimale
from mcp_gateway.atelier.vscode_handoff import _merge_claude_settings_file


def _reglages_ecrits(reglages, tmp_path: Path, avant: dict | None = None) -> dict:
    # Le fichier n'est écrit que si le coffre existe : c'est de lui que le CLI
    # tire sa clé, et sans clé le reste ne sert à rien.
    reglages.llm_key_path.parent.mkdir(parents=True, exist_ok=True)
    reglages.llm_key_path.write_text("factice", encoding="utf-8")
    chemin = tmp_path / "settings.json"
    if avant is not None:
        chemin.write_text(json.dumps(avant), encoding="utf-8")
    _merge_claude_settings_file(chemin, reglages)
    return json.loads(chemin.read_text(encoding="utf-8"))


def test_la_compaction_automatique_est_demandee(reglages, tmp_path: Path) -> None:
    ecrit = _reglages_ecrits(reglages, tmp_path)
    assert ecrit["autoCompactEnabled"] is True
    assert "autoCompactWindow" not in ecrit


def test_la_vraie_fenetre_est_dite_au_cli(reglages, tmp_path: Path) -> None:
    """131 072, pas 40 000 : c'est le relais qui fait tomber la compaction à temps."""
    ecrit = _reglages_ecrits(reglages, tmp_path)
    assert ecrit["env"]["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == str(fenetre_minimale()) == "131072"
    assert ecrit["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "8192"


def test_les_surfaces_parlent_au_modele_par_le_relais(reglages, tmp_path: Path) -> None:
    ecrit = _reglages_ecrits(reglages, tmp_path)
    assert ecrit["env"]["ANTHROPIC_BASE_URL"] == f"http://127.0.0.1:{reglages.relais_llm_port}"


def test_sans_relais_voulu_les_surfaces_vont_a_la_passerelle(reglages, tmp_path: Path) -> None:
    reglages.relais_llm = False
    ecrit = _reglages_ecrits(reglages, tmp_path)
    assert ecrit["env"]["ANTHROPIC_BASE_URL"] == reglages.anthropic_base_url


def test_les_anciens_reglages_sont_retires(reglages, tmp_path: Path) -> None:
    """Un pod installé avant le relais les porte encore dans son fichier."""
    ecrit = _reglages_ecrits(
        reglages,
        tmp_path,
        avant={
            "autoCompactWindow": 30000,
            "env": {
                "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "50000",
                "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "40000",
                "CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT": "1",
            },
        },
    )
    assert "autoCompactWindow" not in ecrit
    for ancien in OBSOLETES:
        assert ancien not in ecrit["env"]
    assert ecrit["env"]["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "131072"


def test_la_cle_du_modele_n_est_jamais_ecrite_en_clair(reglages, tmp_path: Path) -> None:
    """Un agent qui inspecte sa configuration la recopierait dans son journal."""
    ecrit = _reglages_ecrits(reglages, tmp_path)
    assert "factice" not in json.dumps(ecrit)
    assert ecrit["apiKeyHelper"].startswith("cat ")
    assert "ANTHROPIC_API_KEY" not in ecrit["env"]


def test_les_reglages_deja_la_ne_sont_pas_chasses(reglages, tmp_path: Path) -> None:
    ecrit = _reglages_ecrits(
        reglages, tmp_path, avant={"hooks": {"x": 1}, "env": {"MON_VAR": "a moi"}}
    )
    assert ecrit["hooks"] == {"x": 1}
    assert ecrit["env"]["MON_VAR"] == "a moi"
    assert ecrit["autoCompactEnabled"] is True
