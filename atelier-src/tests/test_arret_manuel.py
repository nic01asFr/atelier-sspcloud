"""Une conversation qu'on arrête soi-même n'est pas en erreur.

Mesuré sur le pod : le bouton Arrêter posait « interrupted », puis la fin du
tour, voyant le processus tué rendre un code non nul, réécrivait « failed ».
La liste affichait « en erreur » une conversation arrêtée à la main.
"""

from __future__ import annotations

from pathlib import Path

from mcp_gateway.atelier.harness import FakeHarness, TurnResult
from mcp_gateway.atelier.events import AtelierEvent
from mcp_gateway.atelier.sessions import SessionStore


class HarnaisInterrompu(FakeHarness):
    """Un tour pendant lequel on appuie sur Arrêter."""

    def __init__(self) -> None:
        super().__init__()
        self.store: SessionStore | None = None

    def run_turn(self, session_id: str, message: str, **kwargs) -> TurnResult:  # type: ignore[override]
        assert self.store is not None
        self.store.interrupt(session_id)
        erreur = AtelierEvent(kind="erreur", session_id=session_id, cause="exit_-15", raw_type="x")
        return TurnResult(
            session_id=session_id,
            exit_code=-15,
            events=[erreur],
            log_path=str(kwargs["log_path"]),
            transcript_path=str(kwargs["transcript_path"]),
            text="",
        )


def test_un_tour_arrete_reste_interrompu(reglages) -> None:
    harnais = HarnaisInterrompu()
    store = SessionStore(reglages, harnais)
    harnais.store = store
    rec = store.create(slug="essai")

    store.send(rec.session_id, "travaille longtemps")

    assert store.get(rec.session_id).state == "interrupted"


def test_un_tour_en_echec_sans_arret_reste_en_erreur(reglages) -> None:
    """La correction ne doit pas maquiller une vraie erreur."""

    class HarnaisEnEchec(FakeHarness):
        def run_turn(self, session_id: str, message: str, **kwargs) -> TurnResult:  # type: ignore[override]
            erreur = AtelierEvent(kind="erreur", session_id=session_id, cause="exit_1", raw_type="x")
            return TurnResult(
                session_id=session_id,
                exit_code=1,
                events=[erreur],
                log_path=str(kwargs["log_path"]),
                transcript_path=str(kwargs["transcript_path"]),
                text="",
            )

    store = SessionStore(reglages, HarnaisEnEchec())
    rec = store.create(slug="essai")
    store.send(rec.session_id, "échoue")
    assert store.get(rec.session_id).state == "failed"
