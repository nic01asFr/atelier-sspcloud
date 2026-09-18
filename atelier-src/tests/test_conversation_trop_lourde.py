"""Une conversation qui a franchi la fenêtre ne repart pas, et le dit.

Quatorze conversations du pod pesaient plus que ce que le modèle peut relire.
Chaque message qu'on leur adressait rejouait la même erreur 400 : le résumé
passe par le même modèle, qui ne peut pas les lire non plus. On brûlait donc
un tour pour rien, et l'écran montrait une erreur de passerelle au lieu de
dire ce qui se passe.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.harness import FakeHarness, TurnResult
from mcp_gateway.atelier.sessions import SessionStore
from mcp_gateway.atelier.vscode_handoff import dossier_transcripts_claude


class HarnaisCompteur(FakeHarness):
    def __init__(self) -> None:
        super().__init__()
        self.messages_recus: list[str] = []

    def run_turn(self, session_id: str, message: str, **kw: Any) -> TurnResult:  # type: ignore[override]
        self.messages_recus.append(message)
        return super().run_turn(session_id, message, **kw)


def _conversation_lourde(store: SessionStore, unites: int) -> Any:
    """Une fiche dont le transcript du CLI pèse le poids voulu."""
    rec = store.create(slug="essai")
    rec.claude_session_id = "cli-1"
    rec.turns = 12
    store.save(rec)
    dossier = dossier_transcripts_claude(Path(rec.cwd))
    dossier.mkdir(parents=True, exist_ok=True)
    ligne = json.dumps(
        {"type": "user", "message": {"role": "user", "content": "x" * (unites * 3)}},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    (dossier / "cli-1.jsonl").write_text(ligne + chr(10), encoding="utf-8")
    return rec


def test_une_conversation_qui_deborde_ne_lance_aucun_tour(reglages: AtelierSettings) -> None:
    reglages.contexte_plafond_jetons = 5000
    reglages.compaction_seuil_jetons = 0
    harnais = HarnaisCompteur()
    store = SessionStore(reglages, harnais)
    rec = _conversation_lourde(store, 9000)

    resultat = store.send(rec.session_id, "continue")

    assert harnais.messages_recus == [], "rien ne doit partir au modèle"
    causes = [e.cause for e in resultat.events if e.kind == "erreur"]
    assert causes == ["contexte_plafond"]
    assert "neuve" in resultat.events[0].text, "l'écran doit dire quoi faire"
    fiche = store.get(rec.session_id)
    assert fiche.state == "idle" and fiche.cause == "contexte_plafond"


def test_une_conversation_qui_tient_encore_part_normalement(reglages: AtelierSettings) -> None:
    reglages.contexte_plafond_jetons = 5000
    reglages.compaction_seuil_jetons = 0
    harnais = HarnaisCompteur()
    store = SessionStore(reglages, harnais)
    rec = _conversation_lourde(store, 1000)

    store.send(rec.session_id, "continue")

    assert harnais.messages_recus == ["continue"]
    assert store.get(rec.session_id).state == "idle"
