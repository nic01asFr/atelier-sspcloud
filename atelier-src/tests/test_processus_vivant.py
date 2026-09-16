"""Un processus par conversation, gardé entre les tours.

Mesuré le 14 septembre 2026 sur le pod, avec les dix connecteurs d'une vraie
conversation : un processus neuf met 3,8 s à rebrancher ses connecteurs et
6,6 s à dire son premier mot ; le même processus, 2,7 s. Chaque tour repayait
donc la moitié de son temps en démarrage. Sa file de messages, elle, marche :
deux messages écrits d'un coup sont servis dans l'ordre.

Ce que ce palier promet : le même processus sert les tours qui se suivent ;
il repart si ce qui le configure change ; il s'éteint après un silence, et on
n'en garde jamais plus que le plafond ; l'interrompre le tue ; sa sortie
d'erreur est lue sans jamais bloquer.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from mcp_gateway.atelier import harness as module
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.harness import ClaudeHarness

FAUX = Path(__file__).parent / "faux_claude.py"


@pytest.fixture()
def harnais(reglages: AtelierSettings, monkeypatch: pytest.MonkeyPatch) -> ClaudeHarness:
    """Un harnais dont le `claude` est notre faux, quel que soit le poste."""
    reglages.cli_inactivite_s = 600
    reglages.cli_processus_max = 3
    vrai_popen = subprocess.Popen

    def popen(cmd: list[str], **kw: object) -> subprocess.Popen:
        return vrai_popen([sys.executable, str(FAUX)], **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(module.subprocess, "Popen", popen)
    monkeypatch.setattr(ClaudeHarness, "_resolve_claude_bin", lambda self: FAUX)
    h = ClaudeHarness(reglages)
    yield h
    for sid in list(h.processus_vivants()):
        h.interrupt(sid)


def _tour(h: ClaudeHarness, sid: str, message: str, **kw: object):
    base = h.settings.work_dir
    return h.run_turn(
        sid,
        message,
        cwd=base / "projets" / sid,
        model=None,
        resume=False,
        transcript_path=base / "t" / f"{sid}.jsonl",
        log_path=base / "l" / f"{sid}.log",
        timeout_s=30,
        permission_mode=str(kw.pop("permission_mode", "acceptEdits")),
        **kw,  # type: ignore[arg-type]
    )


def _pid(resultat) -> str:
    return resultat.text.split("pid:")[1].split()[0]


def _attendre_la_mort(h: ClaudeHarness, sid: str, delai: float = 5.0) -> bool:
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if sid not in h.processus_vivants():
            return True
        time.sleep(0.05)
    return False


def test_deux_tours_partagent_le_processus(harnais: ClaudeHarness) -> None:
    un = _tour(harnais, "s1", "bonjour")
    assert un.exit_code == 0 and any(e.kind == "fin" for e in un.events)
    assert not harnais.tour_en_cours("s1"), "le tour est fini, le processus reste"
    assert harnais.processus_vivants() == ["s1"]
    deux = _tour(harnais, "s1", "encore")
    assert _pid(un) == _pid(deux), "même processus, pas de redémarrage"
    assert "echo:encore" in deux.text


def test_ce_qui_configure_le_processus_le_relance(harnais: ClaudeHarness) -> None:
    un = _tour(harnais, "s1", "a", permission_mode="acceptEdits")
    deux = _tour(harnais, "s1", "b", permission_mode="manual")
    assert _pid(un) != _pid(deux), "un autre mode se donne à la ligne de commande"
    assert harnais.processus_vivants() == ["s1"], "l'ancien est éteint, pas oublié"


def test_les_connecteurs_comptent_par_leur_contenu(harnais: ClaudeHarness, tmp_path: Path) -> None:
    cfg = tmp_path / "mcp.json"
    cfg.write_text('{"mcpServers":{}}', encoding="utf-8")
    un = _tour(harnais, "s1", "a", mcp_config_path=cfg)
    deux = _tour(harnais, "s1", "b", mcp_config_path=cfg)
    assert _pid(un) == _pid(deux)
    cfg.write_text('{"mcpServers":{"x":{"url":"http://x"}}}', encoding="utf-8")
    trois = _tour(harnais, "s1", "c", mcp_config_path=cfg)
    assert _pid(deux) != _pid(trois), "un connecteur branché, le processus repart"


def test_le_processus_s_eteint_apres_le_silence(harnais: ClaudeHarness) -> None:
    harnais.settings.cli_inactivite_s = 0
    _tour(harnais, "s1", "a")
    assert _attendre_la_mort(harnais, "s1"), "au premier passage de la veille, il est parti"


def test_jamais_plus_que_le_plafond(harnais: ClaudeHarness) -> None:
    harnais.settings.cli_processus_max = 1
    _tour(harnais, "s1", "a")
    _tour(harnais, "s2", "b")
    assert harnais.processus_vivants() == ["s2"], "le moins récent cède la place"


def test_interrompre_tue_le_processus_garde(harnais: ClaudeHarness) -> None:
    _tour(harnais, "s1", "a")
    assert harnais.interrupt("s1") is True
    assert _attendre_la_mort(harnais, "s1", 1.0)
    assert not harnais.tour_en_cours("s1")


def test_un_processus_mort_est_remplace(harnais: ClaudeHarness) -> None:
    un = _tour(harnais, "s1", "a")
    harnais._vivants["s1"].proc.kill()
    harnais._vivants["s1"].proc.wait(timeout=5)
    deux = _tour(harnais, "s1", "b")
    assert _pid(un) != _pid(deux) and "echo:b" in deux.text


def test_sans_processus_vivant_l_ancien_comportement(harnais: ClaudeHarness) -> None:
    harnais.settings.cli_processus_vivant = False
    un = _tour(harnais, "s1", "a")
    assert un.exit_code == 0
    assert harnais.processus_vivants() == [], "un processus par tour, comme avant"
    deux = _tour(harnais, "s1", "b")
    assert _pid(un) != _pid(deux)


def test_la_sortie_d_erreur_est_lue_sans_bloquer(harnais: ClaudeHarness) -> None:
    debut = time.monotonic()
    resultat = _tour(harnais, "s1", "crash")
    assert time.monotonic() - debut < 10, "on n'a pas attendu la fin d'un processus qui ne finit pas"
    erreurs = [e for e in resultat.events if e.kind == "erreur"]
    assert erreurs and "Error: boom" in erreurs[0].cause
    assert harnais.processus_vivants() == ["s1"], "une erreur dite n'est pas un processus mort"


def test_pendant_le_tour_le_processus_est_en_cours(harnais: ClaudeHarness) -> None:
    import threading

    vus: list[bool] = []

    def pendant(ev) -> None:
        if ev.kind == "texte" and not vus:
            vus.append(harnais.tour_en_cours("s1"))

    _tour(harnais, "s1", "a", on_event=pendant)
    assert vus == [True]
    assert not harnais.tour_en_cours("s1")
    assert threading.active_count() >= 1
