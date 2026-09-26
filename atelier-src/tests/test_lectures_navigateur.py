"""J-f3 : les outils du navigateur qui ne font que lire sont autorisés d'office.

Naviguer, cliquer, remplir, exécuter un script restent soumis au mode. Les
règles passent par la fonction que lisent les réglages de chaque tour, de
VS Code, du terminal et de wikichat (`navigateur.refuser_les_outils_simules`).
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.navigateur import (
    OUTILS_EN_LECTURE,
    autoriser_les_lectures_du_navigateur,
    refuser_les_outils_simules,
    regles_de_lecture_du_navigateur,
)


def _reglages(tmp_path: Path, **options: object) -> AtelierSettings:
    s = AtelierSettings(work_dir=tmp_path / "work", **options)
    s.ensure_dirs()
    return s


def test_seules_les_lectures_sont_autorisees() -> None:
    regles = regles_de_lecture_du_navigateur()
    assert "mcp__chrome-devtools-mcp__list_pages" in regles
    assert "mcp__chrome-devtools-mcp__take_snapshot" in regles
    assert "mcp__chrome-devtools-mcp__take_screenshot" in regles
    assert "mcp__chrome-devtools-mcp__wait_for" in regles
    assert "mcp__chrome-devtools-mcp__list_console_messages" in regles
    assert "mcp__chrome-devtools-mcp__list_network_requests" in regles
    assert all(r.startswith("mcp__chrome-devtools-mcp__") for r in regles)
    for agir in ("navigate_page", "new_page", "select_page", "close_page", "click", "fill", "fill_form",
                 "type_text", "press_key", "evaluate_script", "upload_file", "handle_dialog", "drag", "hover"):
        assert agir not in OUTILS_EN_LECTURE, agir


def test_chaque_tour_autorise_les_lectures_et_rien_d_autre(tmp_path: Path) -> None:
    from mcp_gateway.atelier.harness import ClaudeHarness

    arguments = ClaudeHarness(_reglages(tmp_path))._arguments_de_reglages("conv-1", None)  # noqa: SLF001
    reglages = json.loads(arguments[arguments.index("--settings") + 1])
    permises = reglages["permissions"]["allow"]
    assert set(regles_de_lecture_du_navigateur()) <= set(permises)
    assert not any("navigate_page" in r or "click" in r for r in permises)
    assert "WebSearch" in reglages["permissions"]["deny"]


def test_navigateur_eteint_les_regles_partent_celles_de_la_personne_restent(tmp_path: Path) -> None:
    allume = _reglages(tmp_path)
    perso = {"permissions": {"allow": ["Read", "mcp__autre__outil"]}}
    avec = autoriser_les_lectures_du_navigateur(perso, allume)
    assert avec["permissions"]["allow"][:2] == ["Read", "mcp__autre__outil"]
    assert autoriser_les_lectures_du_navigateur(avec, allume) == avec, "idempotent"
    eteint = _reglages(tmp_path, navigateur=False)
    sans = refuser_les_outils_simules(avec, eteint)
    assert sans["permissions"]["allow"] == ["Read", "mcp__autre__outil"]
