"""Chrome sur le volume : l'installation de l'init, idempotente, sans réseau.

Le pod ne tourne pas sur l'image de l'Atelier : `/usr/bin/google-chrome`,
posé à la main, disparaît au redémarrage. L'init installe un Chrome sans écran
dans `~/work/.tools` par `npx @puppeteer/browsers install`. Ici, un faux `npx`
note son appel et pose le binaire là où `@puppeteer/browsers` le poserait
(`<path>/<navigateur>/linux-<version>/<navigateur>-linux64/<binaire>`).
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None, reason="bloc shell de l'init : pod Linux"
)

INIT = Path(__file__).resolve().parents[2] / "install" / "atelier-init.sh"
DEBUT = "# Chrome lui-même, sur le volume."
FIN = "# --- code-server et l'extension Claude Code"


def _bloc() -> str:
    texte = INIT.read_text(encoding="utf-8")
    return texte[texte.index(DEBUT) : texte.index(FIN)]


def _banc(tmp_path: Path) -> dict[str, Path]:
    outils = tmp_path / "work" / ".tools"
    noeud = tmp_path / "node" / "bin"
    noeud.mkdir(parents=True)
    notes = tmp_path / "npx.appels"
    npx = noeud / "npx"
    npx.write_text(
        "#!/bin/bash\n"
        f'echo "$*" >> "{notes}"\n'
        'nav="${4%@*}"\n'
        'case "$nav" in\n'
        '  chrome) d="$6/chrome/linux-153.0.8010.47/chrome-linux64"; b=chrome ;;\n'
        '  *) d="$6/chrome-headless-shell/linux-153.0.8010.47/chrome-headless-shell-linux64"; b=chrome-headless-shell ;;\n'
        "esac\n"
        'mkdir -p "$d" && printf "#!/bin/sh\\n" > "$d/$b" && chmod +x "$d/$b"\n',
        encoding="utf-8",
    )
    npx.chmod(npx.stat().st_mode | stat.S_IEXEC)
    return {"outils": outils, "noeud": noeud.parent, "notes": notes, "journaux": tmp_path / "logs"}


def _executer(banc: dict[str, Path], **env: str) -> subprocess.CompletedProcess[str]:
    banc["outils"].mkdir(parents=True, exist_ok=True)
    banc["journaux"].mkdir(parents=True, exist_ok=True)
    script = (
        "set -euo pipefail\n"
        "dire() { printf '%s\\n' \"$*\"; }\n"
        "avertir() { printf 'ATTENTION %s\\n' \"$*\" >&2; }\n"
        f'OUTILS="{banc["outils"]}"\nDOSSIER_NODE="{banc["noeud"]}"\nJOURNAUX="{banc["journaux"]}"\n'
        "paquet_navigateur=node_modules/chrome-devtools-mcp/package.json\n" + _bloc()
    )
    return subprocess.run(
        ["bash", "-c", script],
        env={"PATH": "/usr/bin:/bin", "ATELIER_OUTILS": str(banc["outils"] / "absent"), **env},
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_installe_une_fois_chrome_headless_shell(tmp_path: Path) -> None:
    banc = _banc(tmp_path)
    for _ in range(2):
        r = _executer(banc)
        assert r.returncode == 0, r.stderr
    appels = banc["notes"].read_text(encoding="utf-8").splitlines()
    assert len(appels) == 1, "idempotent : un Chrome déjà là ne se réinstalle pas"
    assert appels[0].startswith("--yes @puppeteer/browsers@3.2.3 install chrome-headless-shell@stable --path ")
    assert appels[0].endswith(str(banc["outils"]))
    assert "Chrome du volume :" in r.stdout or "bibliothèques système absentes" in r.stderr


def test_chrome_for_testing_sur_demande(tmp_path: Path) -> None:
    banc = _banc(tmp_path)
    r = _executer(banc, ATELIER_CHROME_NAVIGATEUR="chrome", ATELIER_CHROME_CANAL="153")
    assert r.returncode == 0, r.stderr
    assert "install chrome@153 " in banc["notes"].read_text(encoding="utf-8")
    assert (banc["outils"] / "chrome/linux-153.0.8010.47/chrome-linux64/chrome").is_file()


def test_rien_quand_on_l_a_eteint(tmp_path: Path) -> None:
    banc = _banc(tmp_path)
    for env in ({"ATELIER_CHROME_VOLUME": "0"}, {"ATELIER_CHROME_BIN": "/usr/bin/chromium"}):
        r = _executer(banc, **env)
        assert r.returncode == 0, r.stderr
    assert not banc["notes"].exists()


def test_un_echec_de_telechargement_n_arrete_pas_l_init(tmp_path: Path) -> None:
    banc = _banc(tmp_path)
    (banc["noeud"] / "bin" / "npx").write_text("#!/bin/bash\nexit 1\n", encoding="utf-8")
    r = _executer(banc)
    assert r.returncode == 0
    assert "Chrome ne s'est pas installé" in r.stderr
