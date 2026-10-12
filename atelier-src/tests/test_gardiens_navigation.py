"""Hook `PreToolUse` de navigation : le navigateur d'un agent n'ouvre que des pages web."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_gateway.gardiens.garde_bash import MODULE as MODULE_BASH
from mcp_gateway.gardiens.garde_bash import poser as poser_bash
from mcp_gateway.gardiens.garde_navigation import (
    MATCHER,
    MODULE,
    commande_du_hook_navigation,
    main_hook,
    poser,
    raison_de_refus,
    raison_de_refus_url,
)

REFUSEES = [
    # Pas du web
    "file:///etc/hostname",
    "file:///home/onyxia/work/.secrets/atelier_owner_key",
    "FILE:///etc/passwd",
    "chrome://settings",
    "chrome://inspect/#devices",
    "devtools://devtools/bundled/inspector.html",
    "javascript:alert(1)",
    "blob:http://example.com/x",
    "view-source:file:///etc/hostname",
    "view-source:http://127.0.0.1:3777/",
    "ftp://example.com/x",
    # Le pod et son réseau
    "http://127.0.0.1:3777/api/health",
    "http://localhost:8787/",
    "http://LOCALHOST:8080/",
    "http://localhost./",
    "http://app.localhost/",
    "http://0.0.0.0:8080/",
    "http://[::1]:3777/",
    "http://[::ffff:127.0.0.1]/",
    "http://127.1/",
    "http://127.0.0.2/",
    "http://10.233.115.38:8080/",
    "http://192.168.1.10/",
    "http://172.16.0.5/",
    "http://169.254.169.254/latest/meta-data/",
    "http://metadata.google.internal/",
    "http://kubernetes.default.svc/",
    "http://atelier-0.atelier.user-nic01asfr.svc.cluster.local:8787/",
    "http://wikichat:3777/",
    "http://printer.local/",
    # Écritures détournées
    "http://2130706433/",
    "http://0x7f000001/",
    "http://0x7f.0.0.1/",
    "http://0177.0.0.1/",
    "http://%31%32%37.0.0.1/",
    "http://127。0。0。1/",
    "http://user@127.0.0.1/",
    "http://127.0.0.1\\@example.com/",  # Chrome lit `\` comme `/` : l'hôte est 127.0.0.1
    "http:127.0.0.1:3777",
    "localhost:3000/page",
    "127.0.0.1:8080",
    "http://127.0.0.1\t:3777/",
    # Le proxy de code-server
    "https://user-nic01asfr-atelier.user.lab.sspcloud.fr/vscode/proxy/3000/",
    "https://exemple.fr/proxy/8080/",
    "https://exemple.fr/absproxy/3777/x",
    "https://exemple.fr/%76scode/proxy/3000/",
]
ACCEPTEES = [
    "",
    "about:blank",
    "https://example.com/",
    "http://example.com/page?q=127.0.0.1",
    "https://html.duckduckgo.com/html/?q=localhost+proxy",
    "https://fr.wikipedia.org/wiki/Localhost",
    "https://user-nic01asfr-atelier-apps.user.lab.sspcloud.fr/essai/index.html",
    "https://nic01asfr.github.io/Widgets-Grist/atlas/?scene=https%3A%2F%2Fexemple.fr%2Fscene.json",
    "https://exemple.fr/docs/proxying-guide",
    "https://8.8.8.8/",
    "https://[2001:4860:4860::8888]/",
    "view-source:https://example.com/",
    "example.com",
    "http://example.com\\@127.0.0.1/",  # Chrome : l'hôte est example.com, le reste est un chemin
]


@pytest.mark.parametrize("url", REFUSEES)
def test_refuse(url: str) -> None:
    assert raison_de_refus_url(url), url


@pytest.mark.parametrize("url", ACCEPTEES)
def test_accepte(url: str) -> None:
    assert raison_de_refus_url(url) is None, url


def test_la_raison_dit_quoi_faire_a_la_place() -> None:
    for url in ("file:///etc/passwd", "http://127.0.0.1:3777", "https://x.fr/vscode/proxy/3000/"):
        raison = raison_de_refus_url(url)
        assert "atelier_navigateur_ouvrir" in raison and "atelier_artefact_creer" in raison, url
        assert raison.startswith("Refusé par le socle de l'Atelier")


def test_les_outils_vises_et_leurs_arguments() -> None:
    srv = "mcp__chrome-devtools-mcp__"
    assert raison_de_refus(srv + "navigate_page", {"type": "url", "url": "file:///etc/hostname"})
    assert raison_de_refus(srv + "new_page", {"url": "http://localhost:8787"})
    assert raison_de_refus("WebFetch", {"url": "http://127.0.0.1:3777/api", "prompt": "x"})
    assert raison_de_refus("mcp__chrome-devtools__navigate_page", {"url": "chrome://settings"})  # ancien nom du serveur
    # Rien à juger : retour arrière, rechargement, onglet sans adresse, outil étranger.
    assert raison_de_refus(srv + "navigate_page", {"type": "back"}) is None
    assert raison_de_refus(srv + "new_page", {}) is None
    assert raison_de_refus(srv + "take_snapshot", {}) is None
    assert raison_de_refus("Bash", {"command": "curl http://127.0.0.1:3777"}) is None, "Bash garde sa règle à lui"
    assert raison_de_refus("WebFetch", {"url": "https://example.com/"}) is None


def test_un_script_evalue_dans_la_page_est_relu_au_mieux() -> None:
    srv = "mcp__chrome-devtools-mcp__evaluate_script"
    assert raison_de_refus(srv, {"function": "() => { location.href = 'file:///etc/passwd'; }"})
    assert raison_de_refus(srv, {"function": "() => fetch('http://127.0.0.1:3777/api/health').then(r => r.text())"})
    assert raison_de_refus(srv, {"function": "() => window.open(\"http://localhost:8080/\")"})
    assert raison_de_refus(srv, {"function": "() => document.body.innerText.slice(0, 20000)"}) is None
    assert raison_de_refus(srv, {"function": "() => fetch('https://example.com/data.json')"}) is None


def _lancer(entree: dict, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", MODULE],
        input=json.dumps(entree),
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        timeout=30,
    )


def test_le_hook_bloque_en_code_2_avec_une_raison_lisible(tmp_path: Path) -> None:
    fini = _lancer(
        {"hook_event_name": "PreToolUse", "tool_name": "mcp__chrome-devtools-mcp__navigate_page",
         "tool_input": {"type": "url", "url": "file:///home/onyxia/work/.secrets/"}},
        tmp_path,
    )
    assert fini.returncode == 2
    assert "Refusé par le socle" in fini.stderr and "atelier_navigateur_ouvrir" in fini.stderr
    assert fini.stdout == ""


def test_le_hook_laisse_passer_le_reste_sans_rien_dire(tmp_path: Path) -> None:
    for entree in (
        {"tool_name": "mcp__chrome-devtools-mcp__navigate_page", "tool_input": {"type": "url", "url": "https://example.com/"}},
        {"tool_name": "mcp__chrome-devtools-mcp__take_snapshot", "tool_input": {}},
        {"tool_name": "Bash", "tool_input": {"command": "ls"}},
        {"tool_name": "WebFetch", "tool_input": {"url": "https://example.com/"}},
    ):
        fini = _lancer(entree, tmp_path)
        assert fini.returncode == 0 and fini.stderr == "" and fini.stdout == "", entree
    assert main_hook("pas du json") == 0
    assert main_hook("[]") == 0
    assert main_hook(json.dumps({"tool_name": "WebFetch", "tool_input": "texte"})) == 0


def test_le_matcher_vise_les_outils_de_navigation_et_webfetch() -> None:
    import re

    for nom in ("mcp__chrome-devtools-mcp__navigate_page", "mcp__chrome-devtools-mcp__new_page",
                "mcp__chrome-devtools-mcp__evaluate_script", "WebFetch", "mcp__chrome-devtools__new_page"):
        assert re.fullmatch(MATCHER, nom), nom
    for nom in ("mcp__chrome-devtools-mcp__take_snapshot", "Bash", "WebSearch", "mcp__atelier__atelier_montrer"):
        assert not re.fullmatch(MATCHER, nom), nom


# ── la pose ─────────────────────────────────────────────────────────────────


def _reglages(tmp_path: Path) -> Path:
    chemin = tmp_path / "settings.json"
    chemin.write_text(json.dumps({
        "env": {"X": "1"},
        "hooks": {"Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "node wikichat-hook.mjs"}]}]},
    }), encoding="utf-8")
    return chemin


def test_les_deux_hooks_du_socle_cohabitent_et_la_pose_est_idempotente(tmp_path: Path) -> None:
    chemin = _reglages(tmp_path)
    assert poser_bash(chemin) == "posé"
    assert poser(chemin) == "posé"
    assert poser(chemin) == "déjà posé" and poser_bash(chemin) == "déjà posé"
    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    groupes = donnees["hooks"]["PreToolUse"]
    assert {g["matcher"] for g in groupes} == {"Bash", MATCHER}
    commandes = [h["command"] for g in groupes for h in g["hooks"]]
    assert sum(MODULE_BASH in c for c in commandes) == 1 and sum(MODULE in c for c in commandes) == 1
    assert donnees["hooks"]["Stop"][0]["hooks"][0]["command"] == "node wikichat-hook.mjs", "les hooks des autres ne bougent pas"
    assert donnees["env"] == {"X": "1"}


def test_la_pose_met_a_jour_une_commande_perimee_sans_doublon(tmp_path: Path) -> None:
    chemin = _reglages(tmp_path)
    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    donnees["hooks"]["PreToolUse"] = [{"matcher": "x", "hooks": [{"type": "command", "command": f"vieux -m {MODULE}"}]}]
    chemin.write_text(json.dumps(donnees), encoding="utf-8")
    assert poser(chemin) == "mis à jour"
    commandes = [h["command"] for g in json.loads(chemin.read_text())["hooks"]["PreToolUse"] for h in g["hooks"]]
    assert commandes == [commande_du_hook_navigation()]


def test_la_commande_posee_bloque_depuis_un_dossier_quelconque(tmp_path: Path) -> None:
    chemin = _reglages(tmp_path)
    poser(chemin)
    commande = json.loads(chemin.read_text())["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    fini = subprocess.run(
        ["sh", "-c", commande], input=json.dumps({"tool_name": "WebFetch", "tool_input": {"url": "http://localhost:8787/"}}),
        capture_output=True, text=True, cwd=str(tmp_path), env=env, timeout=30,
    )
    assert fini.returncode == 2, fini.stderr


def test_pose_ne_cree_ni_n_ecrase_un_fichier_absent_ou_illisible(tmp_path: Path) -> None:
    assert "rien posé" in poser(tmp_path / "absent.json")
    casse = tmp_path / "casse.json"
    casse.write_text("{pas du json", encoding="utf-8")
    assert "rien posé" in poser(casse) and casse.read_text(encoding="utf-8") == "{pas du json"
