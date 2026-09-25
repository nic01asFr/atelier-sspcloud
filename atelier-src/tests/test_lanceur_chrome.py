"""Le lanceur `atelier-chrome`, sans Chrome ni chrome-devtools-mcp réels.

Un faux `node` note ses arguments et lit son entrée jusqu'au bout, comme le
serveur ; un faux Chrome dort. On vérifie ce que le lanceur décide — options,
profil jetable rangé à la sortie, portée de la passerelle, rattachement à un
Chrome existant, plafond de navigateurs — et ce qu'il dit quand il manque
quelque chose. L'essai réel (vrai Chrome, vraie conversation `claude -p`) est
dans docs/navigateur-atelier.md.
"""

from __future__ import annotations

import os
import shutil
import signal
import stat
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None, reason="lanceur shell : pod Linux"
)

LANCEUR = Path(__file__).resolve().parents[1] / "bin" / "atelier-chrome"


def _executable(chemin: Path, texte: str) -> Path:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(texte, encoding="utf-8")
    chemin.chmod(chemin.stat().st_mode | stat.S_IEXEC)
    return chemin


@pytest.fixture()
def banc(tmp_path: Path) -> dict[str, Path]:
    work = tmp_path / "work"
    notes = tmp_path / "notes"
    node = _executable(
        work / "bin" / "node",
        "#!/bin/bash\n"
        'if [ "$1" = "-p" ]; then echo "${FAUX_NODE_VERSION:-22}"; exit 0; fi\n'
        f'printf "%s\\n" "$@" > "{notes}/args"\n'
        f'env | grep "^ATELIER_CHROME_\\|^CHROME_DEVTOOLS" | sort > "{notes}/env"\n'
        f'echo "$PWD" > "{notes}/pwd"\n'
        "cat > /dev/null\n",
    )
    serveur = work / ".tools/chrome-devtools-mcp/node_modules/chrome-devtools-mcp/build/src/bin"
    serveur.mkdir(parents=True)
    (serveur / "chrome-devtools-mcp.js").write_text("// faux\n", encoding="utf-8")
    # Sans `exec` : le processus doit garder « chrome » sur sa ligne de commande.
    chrome = _executable(tmp_path / "chrome-faux" / "chrome", "#!/bin/bash\nsleep 30\n")
    notes.mkdir()
    return {"work": work, "notes": notes, "node": node, "chrome": chrome, "racine": tmp_path / "racine"}


def _env(banc: dict[str, Path], **extra: str) -> dict[str, str]:
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(banc["work"].parent),
        "ATELIER_WORK": str(banc["work"]),
        "ATELIER_CHROME_BIN": str(banc["chrome"]),
        "ATELIER_CHROME_RACINE": str(banc["racine"]),
        "ATELIER_OUTILS": str(banc["work"] / "absent"),
    }
    env.update(extra)
    return env


def _lancer(banc: dict[str, Path], cwd: Path | None = None, **extra: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [str(LANCEUR)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_env(banc, **extra),
        cwd=str(cwd or banc["work"]),
    )


def _attendre(chemin: Path, delai: float = 10.0) -> None:
    fin = time.monotonic() + delai
    while not chemin.exists() and time.monotonic() < fin:
        time.sleep(0.05)
    assert chemin.exists(), f"{chemin} jamais écrit"


def _args(banc: dict[str, Path]) -> list[str]:
    _attendre(banc["notes"] / "args")
    time.sleep(0.1)
    return (banc["notes"] / "args").read_text(encoding="utf-8").splitlines()


def test_verifier_dit_ce_qu_il_trouve(banc: dict[str, Path]) -> None:
    r = subprocess.run([str(LANCEUR)], env=_env(banc, ATELIER_CHROME_VERIFIER="1"), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert f"node={banc['node']}" in r.stdout
    assert f"chrome={banc['chrome']}" in r.stdout
    assert "chrome-devtools-mcp.js" in r.stdout


def test_un_node_trop_ancien_est_refuse(banc: dict[str, Path]) -> None:
    r = subprocess.run(
        [str(LANCEUR)],
        env=_env(banc, ATELIER_CHROME_VERIFIER="1", FAUX_NODE_VERSION="18"),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 127 and "node 20" in r.stderr


def test_sans_serveur_installe_le_message_dit_quoi_faire(banc: dict[str, Path]) -> None:
    shutil.rmtree(banc["work"] / ".tools")
    r = subprocess.run([str(LANCEUR)], env=_env(banc), capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 127 and "npm install" in r.stderr


def test_une_conversation_a_son_profil_jetable_range_a_la_fin(banc: dict[str, Path], tmp_path: Path) -> None:
    projet = tmp_path / "projet"
    projet.mkdir()
    p = _lancer(banc, cwd=projet, ATELIER_SESSION="conv-1")
    args = _args(banc)
    profil = Path(args[args.index("--userDataDir") + 1])
    assert profil.parent == banc["racine"] and profil.is_dir()
    assert oct(profil.stat().st_mode & 0o777) == "0o700"
    assert "--headless" in args and args[args.index("--executablePath") + 1] == str(LANCEUR.resolve())
    assert "--no-usage-statistics" in args and "--no-performance-crux" in args
    assert "--no-category-performance" in args and "--no-page-id-routing" in args
    assert "--blockedUrlPattern" not in args, "en conversation, localhost reste joignable"
    espaces = [args[i + 1] for i, a in enumerate(args) if a == "--workspace"]
    assert str(projet) in espaces
    env = (banc["notes"] / "env").read_text(encoding="utf-8")
    assert "ATELIER_CHROME_ROLE=navigateur" in env and "CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS=1" in env
    # Le client ferme son tube : le serveur sort, le profil disparaît.
    p.stdin.close()
    assert p.wait(10) == 0
    assert not profil.exists()


def test_sigterm_est_relaye_et_le_profil_range(banc: dict[str, Path]) -> None:
    p = _lancer(banc)
    args = _args(banc)
    profil = Path(args[args.index("--userDataDir") + 1])
    p.send_signal(signal.SIGTERM)
    assert p.wait(10) == 143
    assert not profil.exists()


def test_la_passerelle_refuse_les_adresses_privees(banc: dict[str, Path]) -> None:
    p = _lancer(banc, ATELIER_CHROME_PORTEE="passerelle")
    args = _args(banc)
    motif = args[args.index("--blockedUrlPattern") + 1]
    assert "127\\." in motif and "10\\." in motif and "[^.]+" in motif
    espaces = [args[i + 1] for i, a in enumerate(args) if a == "--workspace"]
    assert str(banc["work"]) not in espaces, "la passerelle n'écrit pas dans un projet"
    p.stdin.close()
    p.wait(10)


def test_le_rattachement_a_un_chrome_de_l_atelier(banc: dict[str, Path]) -> None:
    """Point d'entrée gardé pour la vue en direct du panneau : Chrome possédé
    par l'Atelier, le serveur s'y rattache au lieu de lancer le sien."""
    (banc["racine"] / "attache").mkdir(parents=True)
    (banc["racine"] / "attache" / "conv-7").write_text("ws://127.0.0.1:9333/devtools/browser/x\n", encoding="utf-8")
    p = _lancer(banc, ATELIER_SESSION="conv-7")
    args = _args(banc)
    assert args[args.index("--wsEndpoint") + 1] == "ws://127.0.0.1:9333/devtools/browser/x"
    assert "--headless" not in args and "--executablePath" not in args
    p.stdin.close()
    p.wait(10)


def test_un_profil_orphelin_est_balaye_pas_un_profil_vivant(banc: dict[str, Path]) -> None:
    racine = banc["racine"]
    orphelin = racine / "profil.999999"
    orphelin.mkdir(parents=True)
    vivant = racine / f"profil.{os.getpid()}"
    vivant.mkdir()
    p = _lancer(banc)
    _args(banc)
    assert not orphelin.exists() and vivant.exists()
    p.stdin.close()
    p.wait(10)


def test_le_plafond_de_navigateurs(banc: dict[str, Path]) -> None:
    env = _env(banc, ATELIER_CHROME_ROLE="navigateur", ATELIER_CHROME_MAX="1")
    premier = subprocess.Popen([str(LANCEUR), "--headless"], env=env, stderr=subprocess.PIPE)
    try:
        fiche = banc["racine"] / "navigateurs" / str(premier.pid)
        _attendre(fiche)
        time.sleep(0.2)
        second = subprocess.run([str(LANCEUR)], env=env, capture_output=True, text=True, timeout=10)
        assert second.returncode == 75
        assert "1 navigateurs déjà ouverts" in second.stderr and "pour 1 permis" in second.stderr
    finally:
        premier.kill()
        premier.wait(5)
    # Le premier parti, la place se libère.
    troisieme = subprocess.Popen([str(LANCEUR)], env=env)
    try:
        _attendre(banc["racine"] / "navigateurs" / str(troisieme.pid))
        assert troisieme.poll() is None
    finally:
        troisieme.kill()
        troisieme.wait(5)
