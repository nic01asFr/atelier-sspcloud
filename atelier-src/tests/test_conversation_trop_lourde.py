"""Une conversation lourde n'est plus jamais déclarée perdue.

Quatorze conversations du pod pesaient plus que ce que le modèle peut relire,
et l'Atelier finissait par refuser de les relancer. Avec le relais LLM, une
conversation trop lourde reçoit « prompt is too long » et le CLI la compacte
de lui-même ; sans lui, l'Atelier la fait résumer avant de l'envoyer. Dans les
deux cas, le message part.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp_gateway.atelier import relais_llm
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


def test_avec_le_relais_une_conversation_lourde_part_telle_quelle(
    reglages: AtelierSettings, monkeypatch
) -> None:
    """Le CLI compacte de lui-même : l'Atelier ne s'en mêle pas."""
    monkeypatch.setattr(relais_llm, "relais_en_service", lambda s, **k: True)
    reglages.contexte_plafond_jetons = 5000
    reglages.compaction_seuil_jetons = 1000
    harnais = HarnaisCompteur()
    store = SessionStore(reglages, harnais)
    rec = _conversation_lourde(store, 9000)

    resultat = store.send(rec.session_id, "continue")

    assert harnais.messages_recus == ["continue"], "ni /compact de l'Atelier, ni refus"
    assert not [e for e in resultat.events if e.kind == "erreur"]
    assert store.get(rec.session_id).state == "idle"


def test_sans_relais_elle_est_resumee_puis_part(reglages: AtelierSettings) -> None:
    reglages.contexte_plafond_jetons = 5000
    reglages.compaction_seuil_jetons = 1000
    harnais = HarnaisCompteur()
    store = SessionStore(reglages, harnais)
    rec = _conversation_lourde(store, 9000)

    store.send(rec.session_id, "continue")

    assert harnais.messages_recus == ["/compact", "continue"]
    assert store.get(rec.session_id).cause != "contexte_plafond"


def test_une_conversation_qui_tient_encore_part_normalement(reglages: AtelierSettings) -> None:
    reglages.contexte_plafond_jetons = 5000
    reglages.compaction_seuil_jetons = 0
    harnais = HarnaisCompteur()
    store = SessionStore(reglages, harnais)
    rec = _conversation_lourde(store, 1000)

    store.send(rec.session_id, "continue")

    assert harnais.messages_recus == ["continue"]
    assert store.get(rec.session_id).state == "idle"
