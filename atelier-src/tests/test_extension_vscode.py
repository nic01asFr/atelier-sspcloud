"""« VS Code ouvre toujours la conversation courante » : ce qui le rend possible.

Le lien « VS Code » de la page passe par `/v1/vscode/open`, qui dépose une
consigne (`.atelier/session.json`) dans le dossier de la conversation. Seule
l'extension `atelier-ouvre-claude`, dans code-server, la lit et ouvre Claude
Code sur cette conversation. Sans elle, rien ne la lit : code-server rouvre la
dernière conversation. Seul un outil de déploiement la posait (retiré en
0.3.0) : l'image et le script de démarrage ne l'installaient pas.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.vscode_handoff import write_resume_sidecar

RACINE = Path(__file__).resolve().parent.parent.parent
INIT = RACINE / "install" / "atelier-init.sh"
EXTENSION = RACINE / "atelier-src" / "vscode-extension" / "atelier-ouvre-claude"


def _bloc_extension() -> str:
    texte = INIT.read_text(encoding="utf-8")
    trouve = re.search(r"# >>> extension-atelier\n(.*?)# <<< extension-atelier", texte, re.S)
    assert trouve, "le bloc « extension-atelier » manque au script de démarrage"
    return trouve.group(1)


def _lancer(source: Path, extensions: Path) -> subprocess.CompletedProcess[str]:
    """Le bloc du script de démarrage, tel quel, dans un dossier d'essai."""
    script = f"""
avertir() {{ echo "AVERT: $*"; }}
SOURCE_ATELIER={source.as_posix()!r}
EXTENSIONS={extensions.as_posix()!r}
{_bloc_extension()}
"""
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, encoding="utf-8", timeout=30)


def test_le_script_de_demarrage_pose_l_extension(tmp_path: Path) -> None:
    extensions = tmp_path / "extensions"
    extensions.mkdir()
    r = _lancer(RACINE / "atelier-src", extensions)
    assert r.returncode == 0, r.stderr
    assert "AVERT" not in r.stdout, r.stdout
    pose = extensions / "atelier-ouvre-claude"
    for nom in ("package.json", "extension.js"):
        assert (pose / nom).read_bytes() == (EXTENSION / nom).read_bytes(), nom
    # Au démarrage suivant elle suit la version de l'Atelier : recopiée par-dessus.
    (pose / "extension.js").write_text("// périmée\n", encoding="utf-8")
    _lancer(RACINE / "atelier-src", extensions)
    assert (pose / "extension.js").read_bytes() == (EXTENSION / "extension.js").read_bytes()


def test_sans_la_source_le_script_le_dit_au_lieu_de_se_taire(tmp_path: Path) -> None:
    extensions = tmp_path / "extensions"
    extensions.mkdir()
    r = _lancer(tmp_path / "source-absente", extensions)
    assert r.returncode == 0
    assert "AVERT" in r.stdout and "VS Code n'ouvrira pas la conversation courante" in r.stdout
    assert not (extensions / "atelier-ouvre-claude").exists()


def test_l_extension_porte_le_nom_de_son_dossier() -> None:
    manifeste = json.loads((EXTENSION / "package.json").read_text(encoding="utf-8"))
    assert manifeste["name"] == "atelier-ouvre-claude"
    assert "onStartupFinished" in manifeste["activationEvents"]
    assert (EXTENSION / manifeste["main"]).is_file()


def test_la_consigne_porte_sa_date_et_designe_la_conversation(tmp_path: Path) -> None:
    settings = AtelierSettings(work_dir=tmp_path / "work")
    settings.ensure_dirs()
    dossier = tmp_path / "projet"
    avant = int(time.time())
    write_resume_sidecar(settings, "demo", "conv-courante", dossier)
    consigne = json.loads((dossier / ".atelier" / "session.json").read_text(encoding="utf-8"))
    assert consigne["session_id"] == "conv-courante" and consigne["slug"] == "demo"
    assert avant <= consigne["ecrit_le"] <= int(time.time())
    # Une autre ouverture remplace la précédente : la consigne désigne toujours la dernière.
    write_resume_sidecar(settings, "demo", "conv-suivante", dossier)
    consigne = json.loads((dossier / ".atelier" / "session.json").read_text(encoding="utf-8"))
    assert consigne["session_id"] == "conv-suivante"
