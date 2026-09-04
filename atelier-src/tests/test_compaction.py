"""La conversation se fait compacter avant de dépasser la fenêtre du modèle.

Claude Code sait compacter, et son réglage est actif — mais sa bascule
automatique se décide sur les jetons consommés, que la passerelle de modèles
rapporte à zéro. Mesuré sur le pod : `input_tokens: 0` à chaque tour, et
`preTokens: 1` dans les métadonnées d'une compaction sur une conversation de
76 000 jetons. Le compteur ne monte jamais, le seuil n'est jamais franchi.

C'est donc à l'Atelier de mesurer et de décider. Ce que ces tests tiennent :
qu'il mesure, et qu'il ne demande la compaction que quand il le faut.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_gateway.atelier import sessions as module_sessions
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.harness import FakeHarness
from mcp_gateway.atelier.sessions import SessionStore


@pytest.fixture()
def transcripts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Un dossier de transcripts court et fixe.

    Le vrai chemin encode le répertoire de travail dans son nom ; sous pytest
    il dépasse la longueur maximale d'un chemin Windows. Ce que ces tests
    éprouvent ne dépend pas de cet encodage.
    """
    dossier = tmp_path / "t"
    dossier.mkdir()
    monkeypatch.setattr(module_sessions, "dossier_transcripts_claude", lambda cwd: dossier)
    return dossier


def _ecrire_transcript(dossier: Path, cli_id: str, caracteres: int) -> None:
    """Un transcript d'un poids voulu, dans la forme que lit le CLI."""
    lignes = [
        json.dumps({"type": "user", "message": {"content": "x" * caracteres}}),
        json.dumps({"type": "system", "message": {"content": "y" * caracteres}}),
    ]
    (dossier / f"{cli_id}.jsonl").write_text("\n".join(lignes) + "\n", encoding="utf-8")


def test_le_poids_ne_compte_que_la_conversation(
    reglages: AtelierSettings, transcripts: Path
) -> None:
    """Les enregistrements de service ne pèsent pas : seuls les tours comptent."""
    store = SessionStore(reglages, FakeHarness())
    rec = store.create(slug="essai", title="Poids")
    _ecrire_transcript(transcripts, store._claude_cli_id(rec), 4000)

    # 4000 caractères de tour utilisateur, divisés par quatre. La ligne
    # « system » de même taille ne doit pas être comptée.
    assert store.poids_de_la_conversation(rec) == 1000


def test_pas_de_compaction_sous_le_seuil(
    reglages: AtelierSettings, transcripts: Path
) -> None:
    reglages.compaction_seuil_jetons = 5000
    store = SessionStore(reglages, FakeHarness())
    rec = store.create(slug="essai", title="Léger")
    _ecrire_transcript(transcripts, store._claude_cli_id(rec), 4000)

    assert store._compacter_si_besoin(rec, store._claude_cli_id(rec)) is False


def test_compaction_au_dessus_du_seuil(
    reglages: AtelierSettings, transcripts: Path
) -> None:
    reglages.compaction_seuil_jetons = 500
    harnais = FakeHarness()
    store = SessionStore(reglages, harnais)
    rec = store.create(slug="essai", title="Lourd")
    _ecrire_transcript(transcripts, store._claude_cli_id(rec), 8000)

    envoyes: list[str] = []
    original = harnais.run_turn

    def espion(session_id, message, **kw):
        envoyes.append(message)
        return original(session_id, message, **kw)

    harnais.run_turn = espion  # type: ignore[method-assign]
    assert store._compacter_si_besoin(rec, store._claude_cli_id(rec)) is True
    # C'est bien la commande de compaction qui part, et rien d'autre.
    assert envoyes == ["/compact"]


def test_un_seuil_a_zero_desactive(reglages: AtelierSettings, transcripts: Path) -> None:
    """De quoi rendre la main si la passerelle se met un jour à compter."""
    reglages.compaction_seuil_jetons = 0
    store = SessionStore(reglages, FakeHarness())
    rec = store.create(slug="essai", title="Sans plafond")
    _ecrire_transcript(transcripts, store._claude_cli_id(rec), 40000)

    assert store._compacter_si_besoin(rec, store._claude_cli_id(rec)) is False


def test_un_transcript_absent_ne_leve_pas(
    reglages: AtelierSettings, transcripts: Path
) -> None:
    store = SessionStore(reglages, FakeHarness())
    rec = store.create(slug="essai", title="Neuve")
    assert store.poids_de_la_conversation(rec) == 0
