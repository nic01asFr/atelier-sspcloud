"""Le vérificateur réécrit : il lit `system/init` sur chaque surface et compare au profil.

Un faux `claude` annonce, comme le vrai, un `system/init` : sa version, son
mode (celui de `--permission-mode`, sinon le `defaultMode` du projet), ses
serveurs (ceux de `--mcp-config`, sinon du `.mcp.json` du dossier) et ses
outils. Puis il attend, comme un vrai tour : le vérificateur doit le tuer.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from mcp_gateway.atelier.coherence import (
    Dossier,
    Lancement,
    Vu,
    ecarts_du_dossier,
    echantillon,
    lire_init,
    rapport_en_texte,
)
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.mcp_sync import lier_le_projet

FAUX = r'''
import json, os, sys, time
args = sys.argv[1:]
def valeur(nom):
    return args[args.index(nom) + 1] if nom in args else None
mode = valeur("--permission-mode")
if not mode:
    try:
        mode = json.load(open(".claude/settings.local.json"))["permissions"]["defaultMode"]
    except Exception:
        mode = "default"
config = valeur("--mcp-config") or ".mcp.json"
try:
    serveurs = json.load(open(config))["mcpServers"]
except Exception:
    serveurs = {}
outils = ["Bash", "Read"] + [f"mcp__{n}__ping" for n in serveurs] + os.environ.get("FAUX_OUTILS", "").split(",")
sys.stdin.readline()
with open(os.environ["FAUX_PID"], "w") as f:
    f.write(str(os.getpid()))
print(json.dumps({"type": "system", "subtype": "init", "claude_code_version": os.environ.get("FAUX_VERSION", "2.1.282"),
                  "permissionMode": mode, "model": "qwen3-6-35b-moe", "tools": [o for o in outils if o],
                  "mcp_servers": [{"name": n, "status": "connected"} for n in serveurs]}), flush=True)
time.sleep(600)
'''


def _faux(tmp_path: Path) -> Path:
    chemin = tmp_path / "faux_claude.py"
    chemin.write_text(FAUX, encoding="utf-8")
    return chemin


def _vivant(pid: int) -> bool:
    if sys.platform == "win32":
        import subprocess

        brut = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True).stdout or b""
        return str(pid) in brut.decode("utf-8", "replace")
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        return "Z" not in Path(f"/proc/{pid}/stat").read_text().split()[2]
    except OSError:
        return True


def test_lire_init_rend_ce_qu_annonce_le_cli_et_tue_le_processus(tmp_path: Path) -> None:
    faux = _faux(tmp_path)
    projet = tmp_path / "p"
    projet.mkdir()
    (projet / ".mcp.json").write_text(json.dumps({"mcpServers": {"atelier": {}, "qgis": {}}}), encoding="utf-8")
    pid = tmp_path / "pid"
    env = {**os.environ, "FAUX_PID": str(pid), "FAUX_OUTILS": "WebSearch"}
    vu = lire_init(Lancement("app", [sys.executable, str(faux), "--permission-mode", "plan"], env, projet), delai=30)
    assert vu.ok and vu.version == "2.1.282" and vu.mode == "plan" and vu.modele == "qwen3-6-35b-moe"
    assert vu.serveurs == {"atelier": "connected", "qgis": "connected"}
    assert "mcp__qgis__ping" in vu.outils and "WebSearch" in vu.outils
    time.sleep(0.5)
    assert not _vivant(int(pid.read_text()))


def test_lire_init_sans_init_le_dit(tmp_path: Path) -> None:
    muet = tmp_path / "muet.py"
    muet.write_text("import sys\nsys.stdin.readline()\n", encoding="utf-8")
    vu = lire_init(Lancement("vscode", [sys.executable, str(muet)], dict(os.environ), tmp_path), delai=10)
    assert not vu.ok and "system/init" in vu.erreur


def _vu(surface: str, **champs) -> Vu:
    base = dict(version="2.1.282", mode="acceptEdits", modele="qwen3-6-35b-moe", effort="medium",
                serveurs={"atelier": "connected"}, outils=["Bash", "mcp__atelier__atelier_montrer"])
    base.update(champs)
    return Vu(surface, ok=True, **base)


def test_des_surfaces_conformes_ne_donnent_aucun_ecart(reglages: AtelierSettings) -> None:
    projet = reglages.projects_dir / "p"
    lier_le_projet(reglages, projet)
    dossier = Dossier("p", projet, "code")
    vus = {s: _vu(s) for s in ("app", "vscode", "terminal", "bash-lc")}
    assert ecarts_du_dossier(reglages, dossier, vus, "2.1.282") == []


def test_les_ecarts_du_contrat_sont_nommes(reglages: AtelierSettings) -> None:
    """Version, mode, serveurs, outils interdits au profil code, WebSearch : ce que l'audit a vu."""
    projet = reglages.projects_dir / "p"
    lier_le_projet(reglages, projet)
    dossier = Dossier("p", projet, "code")
    vus = {
        "app": _vu("app", outils=["Bash", "mcp__atelier__gateway_find_tools", "mcp__atelier__atelier_montrer"]),
        "vscode": _vu("vscode", mode="bypassPermissions"),
        "terminal": _vu("terminal", version="2.1.281", outils=["Bash", "WebSearch", "mcp__atelier__atelier_montrer"]),
        "bash-lc": _vu("bash-lc", serveurs={"atelier": "failed"}),
    }
    ecarts = " | ".join(ecarts_du_dossier(reglages, dossier, vus, "2.1.282"))
    assert "version différent selon la surface" in ecarts and "terminal : version 2.1.281" in ecarts
    assert "vscode : mode bypassPermissions, attendu acceptEdits (projet)" in ecarts
    assert "bash-lc : serveurs en échec ['atelier']" in ecarts
    assert "app : outils hors du profil code ['mcp__atelier__gateway_find_tools']" in ecarts
    assert "terminal : WebSearch présent" in ecarts


def test_l_assistant_doit_avoir_les_meta_outils(reglages: AtelierSettings) -> None:
    reglages.assistant_root.mkdir(parents=True, exist_ok=True)
    lier_le_projet(reglages, reglages.assistant_root, kind="assistant")
    dossier = Dossier("assistant", reglages.assistant_root, "assistant")
    ecarts = ecarts_du_dossier(reglages, dossier, {"app": _vu("app")}, "")
    assert any("méta-outils" in e for e in ecarts)


def test_rapide_prend_un_dossier_par_profil(tmp_path: Path) -> None:
    dossiers = []
    for nom in ("a", "b"):
        (tmp_path / nom).mkdir()
        dossiers.append(Dossier(nom, tmp_path / nom, "code"))
        time.sleep(0.05)
    (tmp_path / "as").mkdir()
    dossiers.append(Dossier("assistant", tmp_path / "as", "assistant"))
    assert [d.slug for d in echantillon(dossiers, None, True)] == ["b", "assistant"]
    assert [d.slug for d in echantillon(dossiers, ["a"], True)] == ["a"]
    assert len(echantillon(dossiers, None, False)) == 3


def test_le_rapport_texte_ne_montre_que_des_noms() -> None:
    rapport = {
        "version_extension": "2.1.282",
        "hooks_introuvables": [],
        "dossiers": [
            {
                "slug": "p",
                "profil": "code",
                "surfaces": {"app": _vu("app").to_dict()},
                "hook_garde": {"pose": True, "code": 2},
                "ecarts": [],
            }
        ],
        "ecarts": 0,
    }
    texte = rapport_en_texte(rapport)
    assert "[p] profil code" in texte and "hook garde_bash : code 2" in texte and "0 écart(s), dont 0 en attente de l'équipe A." in texte


@pytest.mark.skipif(sys.platform == "win32", reason="enveloppeur et shells du pod")
def test_de_bout_en_bout_sur_les_quatre_surfaces(reglages: AtelierSettings, tmp_path: Path, monkeypatch) -> None:
    """Le vrai chemin de chaque surface, avec un faux `claude` : même init partout, aucun écart."""
    import shutil
    import stat

    from mcp_gateway.atelier.coherence import verifier_reel
    from mcp_gateway.atelier.vscode_handoff import assurer_l_enveloppeur

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    faux = bin_dir / "claude"
    faux.write_text("#!" + sys.executable + "\n" + FAUX, encoding="utf-8")
    faux.chmod(faux.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAUX_PID", str(tmp_path / "pid"))
    assurer_l_enveloppeur(reglages)
    projet = reglages.projects_dir / "p"
    lier_le_projet(reglages, projet)
    # `bash -lc` relit /etc/profile, qui réécrit PATH : le faux n'y serait plus trouvé.
    surfaces = ("app", "vscode", "terminal")
    rapport = verifier_reel(reglages, projets=["p"], claude=faux, delai=30, surfaces=surfaces)
    (dossier,) = rapport["dossiers"]
    assert set(dossier["surfaces"]) == set(surfaces)
    assert all(v["ok"] for v in dossier["surfaces"].values()), dossier
    # Le même mode partout : le défaut du service, posé dans le projet à la liaison.
    assert {v["mode"] for v in dossier["surfaces"].values()} == {"acceptEdits"}, dossier
    assert len({tuple(sorted(v["serveurs"])) for v in dossier["surfaces"].values()}) == 1, dossier
    assert shutil.which("bash") is not None


def test_le_reste_au_nom_de_l_assistant_n_est_pas_verifie_comme_un_projet(reglages: AtelierSettings) -> None:
    """Essais du 26/09 : « [wikichat-memory] profil code » à côté de « [assistant] profil assistant ».

    Ce n'était pas le dossier de l'Assistant (`~/work/wikichat-memory`, profil
    `assistant` sur toutes les surfaces) mais `~/work/projects/wikichat-memory`,
    reste de l'ancienne reprise dans VS Code, que l'Atelier ne tient pas pour
    un projet (le slug désigne l'Assistant). Il n'est plus vérifié sous `code` ;
    le rapport le signale, à ranger.
    """
    from mcp_gateway.atelier.coherence import dossiers_masques, dossiers_reels, rapport_en_texte

    reglages.assistant_root.mkdir(parents=True, exist_ok=True)
    (reglages.projects_dir / reglages.assistant_slug).mkdir(parents=True)
    (reglages.projects_dir / "vrai-projet").mkdir(parents=True)
    vus = [(d.slug, d.profil) for d in dossiers_reels(reglages)]
    assert vus == [("vrai-projet", "code"), ("assistant", "assistant")]
    masques = dossiers_masques(reglages)
    assert masques == [str(reglages.projects_dir / reglages.assistant_slug)]
    texte = rapport_en_texte({"version_extension": "x", "dossiers": [], "ecarts": 0, "dossiers_masques": masques})
    assert "porte le nom de l'Assistant sans être son dossier" in texte
