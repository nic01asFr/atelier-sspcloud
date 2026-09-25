"""Audit G1 : ~/.bashrc charge le fichier d'environnement avant sa garde non interactive.

On lance le vrai script (`bin/atelier-bashrc`) sur un ~/.bashrc à la Debian,
puis un shell non interactif qui le lit : il doit voir la variable du fichier
d'environnement. Et un second passage ne change rien.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "atelier-bashrc"
INIT = Path(__file__).resolve().parents[2] / "install" / "atelier-init.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="pas de bash")

DEBIAN = """# ~/.bashrc: executed by bash(1) for non-login shells.

# If not running interactively, don't do anything
case $- in
    *i*) ;;
      *) return;;
esac

HISTCONTROL=ignoreboth
alias ll='ls -alF'
"""


def _poser(bashrc: Path, env: Path) -> str:
    fini = subprocess.run(
        [BASH, str(SCRIPT), str(bashrc).replace("\\", "/"), str(env).replace("\\", "/")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert fini.returncode == 0, fini.stderr
    return fini.stdout.strip()


def _lu_par_un_shell_non_interactif(bashrc: Path) -> str:
    fini = subprocess.run(
        [BASH, "-c", f'. "{bashrc.as_posix()}"; printf %s "${{ATELIER_MCP_ESSAI-absente}}"'],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return fini.stdout


def _env(tmp_path: Path) -> Path:
    env = tmp_path / "secrets" / "claude-env.sh"
    env.parent.mkdir()
    env.write_text("export ATELIER_MCP_ESSAI=presente\n", encoding="utf-8")
    return env


def test_une_ligne_mal_placee_est_deplacee_avant_la_garde(tmp_path: Path) -> None:
    env = _env(tmp_path)
    bashrc = tmp_path / ".bashrc"
    # Ce que l'ancienne init laissait : la ligne en fin de fichier, après la garde.
    ancien = (
        DEBIAN
        + "\n# Atelier : valeurs des références ${ATELIER_MCP_...} (voir docs/coherence-projet.md)\n"
        + f'[ -r "{env.as_posix()}" ] && . "{env.as_posix()}"\n'
    )
    bashrc.write_text(ancien, encoding="utf-8", newline="\n")
    assert _lu_par_un_shell_non_interactif(bashrc) == "absente"  # le défaut G1

    assert _poser(bashrc, env) == "posé"
    texte = bashrc.read_text(encoding="utf-8")
    assert texte.count(env.as_posix()) == 2  # une seule ligne : `-r` puis `.`
    assert texte.index(env.as_posix()) < texte.index("case $- in")
    assert _lu_par_un_shell_non_interactif(bashrc) == "presente"
    # Le reste du fichier est gardé.
    assert "alias ll='ls -alF'" in texte and "HISTCONTROL=ignoreboth" in texte


def test_second_passage_ne_change_rien(tmp_path: Path) -> None:
    env = _env(tmp_path)
    bashrc = tmp_path / ".bashrc"
    bashrc.write_text(DEBIAN, encoding="utf-8", newline="\n")
    assert _poser(bashrc, env) == "posé"
    premier = bashrc.read_bytes()
    assert _poser(bashrc, env) == "inchangé"
    assert bashrc.read_bytes() == premier
    assert _lu_par_un_shell_non_interactif(bashrc) == "presente"


def test_un_bashrc_absent_est_cree_avec_la_seule_ligne(tmp_path: Path) -> None:
    env = _env(tmp_path)
    bashrc = tmp_path / ".bashrc"
    assert _poser(bashrc, env) == "posé"
    assert _lu_par_un_shell_non_interactif(bashrc) == "presente"


def test_l_init_passe_par_le_script_et_ne_rajoute_plus_en_fin() -> None:
    texte = INIT.read_text(encoding="utf-8")
    assert "bin/atelier-bashrc" in texte
    assert '>> "$HOME/.bashrc"' not in texte
