"""git lit le jeton GitHub dans son fichier, à chaque usage : un agent qui pousse n'a rien à lui passer, et la variable périmée du chart ne lui arrive plus."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from mcp_gateway.atelier import git_repos
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.harness import ClaudeHarness

JETON_1 = "github_pat_" + "AAAA1111bbbb2222" * 3
JETON_2 = "github_pat_" + "ZZZZ9999yyyy8888" * 3


@pytest.fixture()
def git_isole(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Une config git globale à soi : le test ne touche jamais à celle de la machine."""
    globale = tmp_path / "gitconfig"
    globale.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(globale))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return globale


def _helper(reglages: AtelierSettings, action: str, entree: str) -> str:
    chemin = git_repos.poser_credential_helper(reglages)
    return subprocess.run([str(chemin), action], input=entree, capture_output=True, text=True, check=True).stdout


def _poser_jeton(reglages: AtelierSettings, jeton: str) -> None:
    reglages.github_token_path.parent.mkdir(parents=True, exist_ok=True)
    reglages.github_token_path.write_text(jeton, encoding="utf-8")


def test_le_script_ne_repond_qu_a_github_en_https(reglages: AtelierSettings, git_isole: Path) -> None:
    _poser_jeton(reglages, JETON_1)
    sortie = _helper(reglages, "get", "protocol=https\nhost=github.com\n\n")
    assert "username=x-access-token" in sortie and f"password={JETON_1}" in sortie
    for entree in ("protocol=https\nhost=gitlab.com\n\n", "protocol=http\nhost=github.com\n\n", "protocol=https\nhost=github.com.evil.test\n\n"):
        assert _helper(reglages, "get", entree) == ""  # un autre hôte ne reçoit jamais le jeton
    assert _helper(reglages, "store", "protocol=https\nhost=github.com\nusername=x\npassword=y\n\n") == ""  # il ne mémorise rien
    assert _helper(reglages, "erase", "protocol=https\nhost=github.com\n\n") == ""


def test_le_script_ne_porte_aucun_secret_et_relit_le_fichier_a_chaque_usage(reglages: AtelierSettings, git_isole: Path) -> None:
    _poser_jeton(reglages, JETON_1)
    chemin = git_repos.poser_credential_helper(reglages)
    assert JETON_1 not in chemin.read_text(encoding="utf-8")
    assert stat.S_IMODE(chemin.stat().st_mode) == 0o700
    assert JETON_1 in _helper(reglages, "get", "protocol=https\nhost=github.com\n\n")
    _poser_jeton(reglages, JETON_2)  # la personne reconnecte GitHub dans Réglages : aucun redémarrage
    sortie = _helper(reglages, "get", "protocol=https\nhost=github.com\n\n")
    assert JETON_2 in sortie and JETON_1 not in sortie


def test_sans_jeton_le_script_se_tait(reglages: AtelierSettings, git_isole: Path) -> None:
    assert _helper(reglages, "get", "protocol=https\nhost=github.com\n\n") == ""


def test_git_global_s_en_sert_pour_github_seulement_et_c_est_idempotent(reglages: AtelierSettings, git_isole: Path) -> None:
    _poser_jeton(reglages, JETON_1)
    git_repos.poser_credential_helper(reglages)
    git_repos.poser_credential_helper(reglages)
    config = git_isole.read_text(encoding="utf-8")
    assert config.count("helper") == 1 and "https://github.com" in config  # une seule ligne, limitée à github.com
    rempli = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n", capture_output=True, text=True, check=True).stdout
    assert f"password={JETON_1}" in rempli
    ailleurs = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=example.org\n\n", capture_output=True, text=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}, check=False)
    assert JETON_1 not in ailleurs.stdout + ailleurs.stderr


def test_un_agent_ne_recoit_plus_la_variable_perimee_du_chart(reglages: AtelierSettings, git_isole: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_GITHUB_TOKEN", "github_pat_perime")
    monkeypatch.setenv("ATELIER_OWNER_KEY", "reste-pour-l-instant")  # D-54 n'est pas soldé : seule la variable GitHub sort ici
    _poser_jeton(reglages, JETON_1)
    env = ClaudeHarness(reglages)._env()  # noqa: SLF001
    assert "ATELIER_GITHUB_TOKEN" not in env
    assert "ATELIER_OWNER_KEY" in env
    assert "https://github.com" in git_isole.read_text(encoding="utf-8")  # et git est prêt pour lui
