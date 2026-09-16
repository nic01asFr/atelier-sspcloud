"""Une conversation trouve le même CLI, qu'on l'ouvre dans l'Atelier ou dans VS Code.

Mesuré le 16 septembre 2026 sur le pod, en lançant chaque surface comme elle se
lance et en lisant sa ligne `system/init` : l'Atelier tournait en 2.1.248, VS Code
en 2.1.273. Pour la même conversation, 239 outils d'un côté et 184 de l'autre,
des agents et des commandes différents. Le lien `~/work/bin/claude` avait été
posé une fois à la main, sur la version du moment ; l'extension, elle, se met
à jour seule.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from mcp_gateway.atelier.claude_home import (
    aligner_le_lien_claude,
    binaire_claude_le_plus_recent,
)
from mcp_gateway.atelier.harness import ClaudeHarness


def _extension(racine: Path, version: str) -> Path:
    binaire = racine / f"anthropic.claude-code-{version}-linux-x64/resources/native-binary/claude"
    binaire.parent.mkdir(parents=True)
    binaire.write_text("#!/bin/sh\n", encoding="utf-8")
    binaire.chmod(0o755)
    return binaire


@pytest.fixture()
def extensions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    racine = tmp_path / "extensions"
    racine.mkdir()
    monkeypatch.setenv("ATELIER_EXTENSIONS", str(racine))
    return racine


def test_la_version_la_plus_recente_gagne_par_ses_numeros(extensions: Path) -> None:
    """Classées comme du texte, 2.1.99 passerait après 2.1.273."""
    _extension(extensions, "2.1.99")
    attendu = _extension(extensions, "2.1.273")
    _extension(extensions, "2.1.248")
    assert binaire_claude_le_plus_recent() == attendu


def test_sans_extension_rien(extensions: Path) -> None:
    assert binaire_claude_le_plus_recent() is None


def test_le_harnais_prend_le_binaire_de_vs_code(extensions: Path, reglages, tmp_path: Path) -> None:
    ancien = _extension(extensions, "2.1.248")
    recent = _extension(extensions, "2.1.273")
    reglages.claude_bin.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        reglages.claude_bin.symlink_to(ancien)
    assert ClaudeHarness(reglages)._resolve_claude_bin() == recent


@pytest.mark.skipif(os.name == "nt", reason="liens symboliques du pod")
def test_le_lien_suit_l_extension(extensions: Path, reglages) -> None:
    ancien = _extension(extensions, "2.1.248")
    recent = _extension(extensions, "2.1.273")
    reglages.claude_bin.parent.mkdir(parents=True, exist_ok=True)
    reglages.claude_bin.symlink_to(ancien)
    assert aligner_le_lien_claude(reglages) == recent
    assert reglages.claude_bin.resolve() == recent.resolve()


def test_un_vrai_fichier_a_la_place_du_lien_est_respecte(extensions: Path, reglages) -> None:
    _extension(extensions, "2.1.273")
    reglages.claude_bin.parent.mkdir(parents=True, exist_ok=True)
    reglages.claude_bin.write_text("posé à la main", encoding="utf-8")
    assert aligner_le_lien_claude(reglages) is None
    assert reglages.claude_bin.read_text(encoding="utf-8") == "posé à la main"


def test_le_service_aligne_au_demarrage() -> None:
    api = (Path(__file__).resolve().parent.parent / "mcp_gateway/atelier/api.py").read_text(encoding="utf-8")
    debut = api.index("async def lifespan")
    corps = api[debut : debut + 2500]
    assert "aligner_le_lien_claude(settings)" in corps
    assert "ecrire_mode_machine(settings)" in corps
