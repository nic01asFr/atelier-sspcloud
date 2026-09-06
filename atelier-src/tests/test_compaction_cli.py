"""Ce que le CLI doit savoir pour ne pas se laisser étouffer.

Une conversation menée depuis VS Code grossit jusqu'au refus : notre propre
filet ne couvre que les tours de l'Atelier. Le CLI sait compacter tout seul,
mais son compte de jetons sous-estime celui du modèle servi — une conversation
qu'il situait à 50 000 a été refusée à 122 881, soit environ 2,7 fois.

Ces réglages vivaient à la main sur le pod, donc nulle part : un redéploiement
les emportait sans bruit, et la panne revenait des semaines plus tard sans
qu'on fasse le lien.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp_gateway.atelier.vscode_handoff import _merge_claude_settings_file


def _reglages_ecrits(reglages, tmp_path: Path) -> dict:
    # Le fichier n'est écrit que si le coffre existe : c'est de lui que le CLI
    # tire sa clé, et sans clé le reste ne sert à rien.
    reglages.llm_key_path.parent.mkdir(parents=True, exist_ok=True)
    reglages.llm_key_path.write_text("factice", encoding="utf-8")
    chemin = tmp_path / "settings.json"
    _merge_claude_settings_file(chemin, reglages)
    return json.loads(chemin.read_text(encoding="utf-8"))


def test_la_compaction_automatique_est_demandee(reglages, tmp_path: Path) -> None:
    ecrit = _reglages_ecrits(reglages, tmp_path)
    assert ecrit["autoCompactEnabled"] is True
    assert ecrit["autoCompactWindow"] == reglages.cli_fenetre_compaction


def test_le_plafond_de_contexte_est_dit_au_cli(reglages, tmp_path: Path) -> None:
    """Sans lui, le CLI se croit au large jusqu'au refus du serveur."""
    ecrit = _reglages_ecrits(reglages, tmp_path)
    assert ecrit["env"]["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == str(reglages.cli_contexte_max)


def test_les_deux_plafonds_laissent_de_quoi_compacter(reglages) -> None:
    """La fenêtre de compaction doit se déclencher avant le plafond.

    Réglés à l'envers, le CLI atteindrait la limite sans jamais avoir compacté
    — et une conversation qui ne peut plus être compactée ne peut plus rien
    recevoir. C'est exactement la panne qu'on répare.
    """
    assert 0 < reglages.cli_fenetre_compaction < reglages.cli_contexte_max


def test_la_cle_du_modele_n_est_jamais_ecrite_en_clair(reglages, tmp_path: Path) -> None:
    """Un agent qui inspecte sa configuration la recopierait dans son journal."""
    ecrit = _reglages_ecrits(reglages, tmp_path)
    assert "factice" not in json.dumps(ecrit)
    assert ecrit["apiKeyHelper"].startswith("cat ")
    assert "ANTHROPIC_API_KEY" not in ecrit["env"]


def test_les_reglages_deja_la_ne_sont_pas_chasses(reglages, tmp_path: Path) -> None:
    chemin = tmp_path / "settings.json"
    chemin.write_text(
        json.dumps({"hooks": {"x": 1}, "env": {"MON_VAR": "a moi"}}), encoding="utf-8"
    )
    reglages.llm_key_path.parent.mkdir(parents=True, exist_ok=True)
    reglages.llm_key_path.write_text("factice", encoding="utf-8")

    _merge_claude_settings_file(chemin, reglages)
    ecrit = json.loads(chemin.read_text(encoding="utf-8"))
    assert ecrit["hooks"] == {"x": 1}
    assert ecrit["env"]["MON_VAR"] == "a moi"
    assert ecrit["autoCompactEnabled"] is True
