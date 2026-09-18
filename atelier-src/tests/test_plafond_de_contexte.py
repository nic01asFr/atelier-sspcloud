"""Un tour qui grossit trop s'arrête, se fait résumer, et reprend.

Mesuré le 17 septembre 2026 sur le pod : la passerelle de modèles rapporte
zéro jeton consommé, si bien que la compaction automatique du CLI ne se
déclenche jamais. L'Atelier compactait entre deux tours ; mais un seul tour
qui enchaîne les outils suffit à franchir la fenêtre. Un agent parti pour un
lot de travail a ainsi inventé une revue qu'on ne lui avait pas faite, réécrit
dix fois le même fichier, puis fini au-delà de ce que le modèle peut relire :
la conversation était perdue, la compaction elle-même n'y tenant plus.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from mcp_gateway.atelier import harness as module
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.events import AtelierEvent
from mcp_gateway.atelier.harness import ClaudeHarness, FakeHarness, TurnResult
from mcp_gateway.atelier.sessions import MESSAGE_DE_REPRISE, SessionStore

FAUX = Path(__file__).parent / "faux_claude.py"


@pytest.fixture()
def harnais(reglages: AtelierSettings, monkeypatch: pytest.MonkeyPatch) -> ClaudeHarness:
    reglages.contexte_plafond_jetons = 2000
    vrai_popen = subprocess.Popen

    def popen(cmd: list[str], **kw: Any) -> subprocess.Popen:
        return vrai_popen([sys.executable, str(FAUX)], **kw)

    monkeypatch.setattr(module.subprocess, "Popen", popen)
    monkeypatch.setattr(ClaudeHarness, "_resolve_claude_bin", lambda self: FAUX)
    h = ClaudeHarness(reglages)
    yield h
    for sid in list(h.processus_vivants()):
        h.interrupt(sid)


def _tour(h: ClaudeHarness, sid: str, message: str, **kw: Any) -> TurnResult:
    base = h.settings.work_dir
    return h.run_turn(
        sid,
        message,
        cwd=base / "projets" / sid,
        model=None,
        resume=False,
        transcript_path=base / "t" / (sid + ".jsonl"),
        log_path=base / "l" / (sid + ".log"),
        timeout_s=30,
        permission_mode="acceptEdits",
        **kw,
    )


def test_un_tour_trop_lourd_s_arrete(harnais: ClaudeHarness) -> None:
    resultat = _tour(harnais, "lourd", "bavard 200")
    causes = [e.cause for e in resultat.events if e.kind == "erreur"]
    assert "contexte_plafond" in causes
    fin = time.monotonic() + 5
    while time.monotonic() < fin and "lourd" in harnais.processus_vivants():
        time.sleep(0.05)
    assert "lourd" not in harnais.processus_vivants(), "le processus doit être éteint"


def test_un_tour_raisonnable_va_jusqu_au_bout(harnais: ClaudeHarness) -> None:
    """Le plafond ne doit pas couper un tour ordinaire."""
    resultat = _tour(harnais, "leger", "bonjour")
    assert not [e for e in resultat.events if e.kind == "erreur"]
    assert any(e.kind == "fin" for e in resultat.events)


def test_le_poids_deja_accumule_compte(harnais: ClaudeHarness) -> None:
    """Le plafond porte sur la conversation entière, pas sur le seul tour."""
    resultat = _tour(harnais, "deja-lourde", "bonjour", poids_initial=1999)
    assert "contexte_plafond" in [e.cause for e in resultat.events if e.kind == "erreur"]


class HarnaisQuiDeborde(FakeHarness):
    """Un harnais dont le premier tour bute sur le plafond, et lui seul."""

    def __init__(self) -> None:
        super().__init__()
        self.messages_recus: list[str] = []
        self.deborde_encore = True

    def run_turn(self, session_id: str, message: str, **kw: Any) -> TurnResult:  # type: ignore[override]
        self.messages_recus.append(message)
        if message.startswith("/compact") or not self.deborde_encore:
            return super().run_turn(session_id, message, **kw)
        self.deborde_encore = False
        return TurnResult(
            session_id=session_id,
            exit_code=-15,
            events=[
                AtelierEvent(
                    kind="erreur",
                    session_id=session_id,
                    cause="contexte_plafond",
                    text="40000",
                )
            ],
            log_path=str(kw["log_path"]),
            transcript_path=str(kw["transcript_path"]),
            text="",
        )


def test_l_atelier_compacte_puis_fait_reprendre(reglages: AtelierSettings) -> None:
    harnais = HarnaisQuiDeborde()
    store = SessionStore(reglages, harnais)
    rec = store.create(slug="essai")

    store.send(rec.session_id, "fais le lot L7")

    assert "/compact" in harnais.messages_recus, "la conversation doit être résumée"
    assert MESSAGE_DE_REPRISE in harnais.messages_recus, "puis reprise là où elle en était"
    assert harnais.messages_recus.index("/compact") < harnais.messages_recus.index(
        MESSAGE_DE_REPRISE
    ), "résumer d'abord, reprendre ensuite"
    assert store.get(rec.session_id).state == "idle"


class HarnaisQuiDebordeToujours(FakeHarness):
    def __init__(self) -> None:
        super().__init__()
        self.tours = 0

    def run_turn(self, session_id: str, message: str, **kw: Any) -> TurnResult:  # type: ignore[override]
        if message.startswith("/compact"):
            return super().run_turn(session_id, message, **kw)
        self.tours += 1
        return TurnResult(
            session_id=session_id,
            exit_code=-15,
            events=[
                AtelierEvent(
                    kind="erreur",
                    session_id=session_id,
                    cause="contexte_plafond",
                    text="40000",
                )
            ],
            log_path=str(kw["log_path"]),
            transcript_path=str(kw["transcript_path"]),
            text="",
        )


def test_les_reprises_ont_une_fin(reglages: AtelierSettings) -> None:
    """Sinon deux tours trop lourds se relanceraient l'un l'autre sans fin."""
    reglages.contexte_reprises_max = 3
    harnais = HarnaisQuiDebordeToujours()
    store = SessionStore(reglages, harnais)
    rec = store.create(slug="essai")

    store.send(rec.session_id, "fais le lot L7")

    assert harnais.tours == 4, "le tour, puis trois reprises, et l'on s'arrête"
    fiche = store.get(rec.session_id)
    assert fiche.state == "timeout" and fiche.cause == "contexte_plafond"


class HarnaisDontLeResumeEchoue(HarnaisQuiDebordeToujours):
    """Le cas qui rend la reprise vaine : la conversation ne se résume plus."""

    def run_turn(self, session_id: str, message: str, **kw: Any) -> TurnResult:  # type: ignore[override]
        if message.startswith("/compact"):
            raise RuntimeError("API Error: 400 ContextWindowExceeded")
        return super().run_turn(session_id, message, **kw)


def test_sans_resume_on_ne_reprend_pas(reglages: AtelierSettings) -> None:
    """Reprendre sans avoir résumé buterait au même endroit, une fois de plus."""
    reglages.contexte_reprises_max = 3
    harnais = HarnaisDontLeResumeEchoue()
    store = SessionStore(reglages, harnais)
    rec = store.create(slug="essai")

    store.send(rec.session_id, "fais le lot L7")

    assert harnais.tours == 1, "un seul tour : le résumé n'ayant pas abouti, on s'arrête"
    fiche = store.get(rec.session_id)
    assert fiche.state == "timeout" and fiche.cause == "contexte_plafond"
