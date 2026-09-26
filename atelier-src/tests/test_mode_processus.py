"""Un mode changé ne reste pas lettre morte pour un processus déjà lancé (constat du 26/09).

Sur le pod : une conversation passée en bypass, ouverte dans VS Code, puis
rendue au défaut du projet dans l'app, gardait un `claude` en bypass pendant
plus d'une heure et demie. Trois choses sont vérifiées ici :

- le harnais de l'Atelier éteint son processus gardé au repos, ou lui envoie
  `set_permission_mode` en plein tour (le CLI 2.1.282 l'accepte) ;
- l'Atelier dit si un processus VS Code de la conversation est vivant, pour
  que l'interface annonce « s'applique à la prochaine ouverture » ;
- le gardien de sécurité rattache un processus VS Code à sa fiche par
  `sessions/<pid>.json`, et signale un processus plus permissif que le mode
  choisi.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier import harness as module
from mcp_gateway.atelier.api import build_app
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.harness import ClaudeHarness
from mcp_gateway.atelier.sessions import processus_cli_de
from mcp_gateway.gardiens.controles import securite
from mcp_gateway.gardiens.controles.commun import Contexte, Processus
from mcp_gateway.gardiens.declaration import Controle

FAUX = Path(__file__).parent / "faux_claude.py"


@pytest.fixture()
def harnais(reglages: AtelierSettings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Le vrai harnais, avec notre faux `claude` qui reçoit la vraie ligne de commande."""
    reglages.cli_inactivite_s = 600
    reglages.cli_processus_max = 3
    vrai_popen = subprocess.Popen
    controles = tmp_path / "controles.jsonl"
    monkeypatch.setenv("FAUX_CLAUDE_CONTROLES", str(controles))

    def popen(cmd: list[str], **kw: object) -> subprocess.Popen:
        return vrai_popen([sys.executable, str(FAUX), *cmd[1:]], **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(module.subprocess, "Popen", popen)
    monkeypatch.setattr(ClaudeHarness, "_resolve_claude_bin", lambda self: FAUX)
    h = ClaudeHarness(reglages)
    h.controles = controles  # type: ignore[attr-defined]
    yield h
    for sid in list(h.processus_vivants()):
        h.interrupt(sid)


def _tour(h: ClaudeHarness, sid: str, message: str, mode: str):
    base = h.settings.work_dir
    return h.run_turn(
        sid, message, cwd=base / "projets" / sid, model=None, resume=False,
        transcript_path=base / "t" / f"{sid}.jsonl", log_path=base / "l" / f"{sid}.log",
        timeout_s=30, permission_mode=mode,
    )


def test_au_repos_le_processus_est_eteint_et_repart_avec_le_nouveau_mode(harnais: ClaudeHarness) -> None:
    un = _tour(harnais, "s1", "mode ?", "bypassPermissions")
    assert "mode:bypassPermissions" in un.text
    assert "s1" in harnais.processus_vivants(), "le processus est gardé entre deux tours"
    assert harnais.changer_de_mode("s1", "default") == "eteint"
    assert "s1" not in harnais.processus_vivants()
    deux = _tour(harnais, "s1", "mode ?", "default")
    assert "mode:default" in deux.text
    assert deux.text.split("pid:")[1].split()[0] != un.text.split("pid:")[1].split()[0]
    assert harnais.changer_de_mode("inconnue", "plan") == "aucun"


def test_en_plein_tour_le_nouveau_mode_est_envoye_au_cli(harnais: ClaudeHarness) -> None:
    resultat: dict = {}
    fil = threading.Thread(target=lambda: resultat.setdefault("r", _tour(harnais, "s2", "dors 1.5", "bypassPermissions")))
    fil.start()
    for _ in range(100):
        if harnais.tour_en_cours("s2"):
            break
        time.sleep(0.02)
    assert harnais.changer_de_mode("s2", "plan") == "envoye"
    fil.join(10)
    assert resultat["r"].exit_code == 0, "le tour ne doit pas souffrir de la réponse de contrôle"
    recu = [json.loads(l) for l in harnais.controles.read_text(encoding="utf-8").splitlines()]  # type: ignore[attr-defined]
    assert recu == [{"subtype": "set_permission_mode", "mode": "plan"}]
    # Le tour suivant repart de toute façon avec le mode choisi.
    assert "mode:plan" in _tour(harnais, "s2", "mode ?", "plan").text


def test_changer_le_mode_d_une_conversation_le_transmet_au_harnais(reglages: AtelierSettings, cle_du_proprietaire: str) -> None:
    (reglages.projects_dir / "alpha").mkdir(parents=True)
    with TestClient(build_app(settings=reglages, use_fake=True), base_url="https://testserver") as client:
        fiche = client.app.state.store.create(slug="alpha")
        r = client.patch(
            f"/v1/sessions/{fiche.session_id}", headers={"Authorization": f"Bearer {cle_du_proprietaire}"},
            json={"permission_mode": "plan"},
        )
        assert r.status_code == 200, r.text
        assert client.app.state.harness.modes_changes == [(fiche.session_id, "plan")]


# --- un processus VS Code vivant ---------------------------------------------


def _fichier_de_processus(dossier: Path, pid: int, session: str, entree: str = "claude-vscode") -> None:
    (dossier / "sessions").mkdir(parents=True, exist_ok=True)
    (dossier / "sessions" / f"{pid}.json").write_text(json.dumps({
        "pid": pid, "sessionId": session, "entrypoint": entree, "status": "idle",
        "startedAt": 1790391683670, "version": "2.1.282", "kind": "interactive",
    }), encoding="utf-8")


def test_processus_cli_de_la_conversation(tmp_path: Path) -> None:
    _fichier_de_processus(tmp_path, 11, "conv-a")
    _fichier_de_processus(tmp_path, 12, "conv-a", "cli")
    _fichier_de_processus(tmp_path, 13, "conv-b")
    _fichier_de_processus(tmp_path, 14, "conv-a")  # mort
    lignes = {11: ["claude", "--permission-mode", "bypassPermissions", "--resume", "conv-a"], 12: ["claude"]}
    trouves = processus_cli_de(
        [tmp_path], "conv-a", vivant=lambda pid: pid != 14, ligne_de_commande=lambda pid: lignes.get(pid, []),
    )
    assert {(p["pid"], p["surface"], p["mode_au_lancement"]) for p in trouves} == {
        (11, "vscode", "bypassPermissions"), (12, "terminal", None),
    }


def test_la_route_dit_qu_un_onglet_vscode_est_ouvert(reglages: AtelierSettings, cle_du_proprietaire: str, monkeypatch: pytest.MonkeyPatch) -> None:
    (reglages.projects_dir / "alpha").mkdir(parents=True)
    config = reglages.work_dir / "config-claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    with TestClient(build_app(settings=reglages, use_fake=True), base_url="https://testserver") as client:
        fiche = client.app.state.store.create(slug="alpha")
        entetes = {"Authorization": f"Bearer {cle_du_proprietaire}"}
        r = client.get(f"/v1/sessions/{fiche.session_id}/processus", headers=entetes)
        assert r.status_code == 200 and r.json()["vscode_vivant"] is False
        # Un processus bien vivant (celui des tests) se déclare pour cette conversation.
        _fichier_de_processus(config, os.getpid(), fiche.session_id)
        corps = client.get(f"/v1/sessions/{fiche.session_id}/processus", headers=entetes).json()
        assert corps["vscode_vivant"] is True
        assert "prochaine ouverture dans VS Code" in corps["note"]
        assert corps["mode_choisi"] == "acceptEdits"
        assert client.get("/v1/sessions/inconnue/processus", headers=entetes).status_code == 404
        assert client.get(f"/v1/sessions/{fiche.session_id}/processus").status_code == 401


# --- le gardien de sécurité ---------------------------------------------------


def _ctx(tmp_path: Path) -> Contexte:
    work, home = tmp_path / "work", tmp_path / "home"
    (work / "sessions").mkdir(parents=True)
    home.mkdir()
    return Contexte(work=work, home=home, code_server_dir=home / "code-server", env={}, ecoutes=lambda: [], processus=lambda: [])


def _controle() -> Controle:
    return Controle(id="securite.bypass", gardien="securite", portee="pod", quand={"toutes_les_min": 5}, commande=["interne", "securite.bypass"])


def test_un_processus_vscode_se_rattache_a_sa_fiche_par_sessions_pid(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    (ctx.sessions_dir / "a.json").write_text(json.dumps({
        "session_id": "atelier-a", "claude_session_id": "cli-a", "permission_mode": "bypassPermissions",
    }), encoding="utf-8")
    _fichier_de_processus(ctx.home / ".claude", 42, "cli-a")
    # La ligne de commande de l'extension ne nomme pas la conversation.
    ctx.processus = lambda: [Processus(42, ["/x/native-binary/claude", "--permission-mode", "bypassPermissions"], "/w/p", 1)]
    res = securite.bypass(ctx, _controle())
    assert res["constats"] == [], "faux positif : la fiche existe"
    assert res["donnees"]["claude_en_bypass"] == 1


def test_un_processus_plus_permissif_que_le_mode_choisi_est_un_constat(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    (ctx.sessions_dir / "a.json").write_text(json.dumps({
        "session_id": "atelier-a", "claude_session_id": "cli-a", "permission_mode": "", "cwd": str(tmp_path / "p"),
    }), encoding="utf-8")
    # Le choix de la conversation, là où l'app et VS Code l'écrivent : revenue au défaut.
    magasin = ctx.code_server_dir / "User" / "globalStorage" / "anthropic.claude-code" / "session-permission-modes"
    magasin.mkdir(parents=True)
    (magasin / "cli-a.json").write_text(json.dumps({"mode": "default", "updatedAt": 1790391683670}), encoding="utf-8")
    _fichier_de_processus(ctx.home / ".claude", 42, "cli-a")
    ctx.processus = lambda: [
        Processus(42, ["/x/native-binary/claude", "--permission-mode", "bypassPermissions"], "/w/p", 1),
        # Moins permissif que le choix : ce n'est pas l'affaire de la sécurité.
        Processus(43, ["/x/native-binary/claude", "--permission-mode", "plan", "--resume", "cli-a"], "/w/p", 1),
    ]
    res = securite.bypass(ctx, _controle())
    assert [c["empreinte"] for c in res["constats"]] == ["securite.bypass:cli-a:mode"]
    constat = res["constats"][0]
    assert "bypassPermissions" in constat["resume"] and "default" in constat["resume"]
    assert constat["niveau"] == "alerte" and "claude-vscode" in constat["preuve"]


def test_sans_aucune_fiche_le_bypass_reste_signale(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _fichier_de_processus(ctx.home / ".claude", 7, "cli-inconnue")
    ctx.processus = lambda: [Processus(7, ["/x/claude", "--permission-mode", "bypassPermissions"], "/tmp", 1)]
    res = securite.bypass(ctx, _controle())
    assert [c["empreinte"] for c in res["constats"]] == ["securite.bypass:cli-inconnue"]
