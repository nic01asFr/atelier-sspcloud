"""Deux gestes sur la même conversation ne se marchent pas dessus.

Relecture du 03/10 (noyau) :
- entre la fiche posée « en cours » et l'entrée du tour dans le harnais, un
  second envoi voyait « en cours » sans tour réel, prenait la fiche pour périmée
  et lançait un second processus sur le même identifiant ;
- la fin du tour réécrivait la fiche lue au début : un renommage, un archivage
  fait pendant le tour se perdait, et une conversation supprimée ressuscitait.
"""

from __future__ import annotations

import threading

from mcp_gateway.atelier.events import AtelierEvent
from mcp_gateway.atelier.harness import FakeHarness, TurnResult
from mcp_gateway.atelier.sessions import SessionStore


class HarnaisCompte(FakeHarness):
    """Compte les tours lancés ; `pendant_le_tour` simule ce que fait la personne."""

    def __init__(self) -> None:
        super().__init__()
        self.lances = 0
        self.pendant_le_tour = lambda sid: None

    def tour_en_cours(self, session_id: str) -> bool:  # comme le vrai : faux avant `run_turn`
        return False

    def run_turn(self, session_id: str, message: str, **kwargs) -> TurnResult:  # type: ignore[override]
        self.lances += 1
        self.pendant_le_tour(session_id)
        return TurnResult(
            session_id=session_id,
            exit_code=0,
            events=[],
            log_path=str(kwargs["log_path"]),
            transcript_path=str(kwargs["transcript_path"]),
            text="réponse",
        )


def test_un_second_envoi_pendant_le_demarrage_va_en_file(reglages, monkeypatch) -> None:
    import mcp_gateway.atelier.mcp_sync as mcp_sync

    harnais = HarnaisCompte()
    store = SessionStore(reglages, harnais)
    rec = store.create(slug="essai")

    entre = threading.Event()
    libere = threading.Event()
    reel = mcp_sync.materialize_session_mcp

    def lent(*args, **kwargs):
        entre.set()
        assert libere.wait(5)
        return reel(*args, **kwargs)

    monkeypatch.setattr(mcp_sync, "materialize_session_mcp", lent)
    premier: dict = {}
    fil = threading.Thread(target=lambda: premier.setdefault("r", store.send(rec.session_id, "un")))
    fil.start()
    assert entre.wait(5)  # le premier envoi est dans la fenêtre, avant `run_turn`

    second = store.send(rec.session_id, "deux")
    libere.set()
    fil.join(5)

    assert harnais.lances == 1, "un seul processus pour une conversation"
    assert [e.cause for e in second.events] == ["message_en_file"]
    assert premier["r"].text == "réponse"
    assert store.get(rec.session_id).state == "idle"


def test_la_conversation_se_libere_apres_le_tour(reglages) -> None:
    harnais = HarnaisCompte()
    store = SessionStore(reglages, harnais)
    rec = store.create(slug="essai")
    store.send(rec.session_id, "un")
    store.send(rec.session_id, "deux")
    assert harnais.lances == 2


def test_la_conversation_se_libere_apres_un_echec(reglages) -> None:
    class Casse(HarnaisCompte):
        def run_turn(self, session_id, message, **kwargs):  # type: ignore[override]
            self.lances += 1
            raise RuntimeError("boum")

    harnais = Casse()
    store = SessionStore(reglages, harnais)
    rec = store.create(slug="essai")
    for _ in range(2):
        try:
            store.send(rec.session_id, "x")
        except RuntimeError:
            pass
    assert harnais.lances == 2, "un échec ne garde pas la conversation réservée"


def test_un_renommage_pendant_le_tour_survit(reglages) -> None:
    harnais = HarnaisCompte()
    store = SessionStore(reglages, harnais)
    rec = store.create(slug="essai")
    harnais.pendant_le_tour = lambda sid: store.patch(sid, title="Mon titre", model="qwen3-6-35b-moe")
    store.send(rec.session_id, "travaille")
    fiche = store.get(rec.session_id)
    assert fiche.title == "Mon titre"
    assert fiche.state == "idle" and fiche.turns == 1 and fiche.last_text == "réponse"


def test_un_archivage_pendant_le_tour_survit(reglages) -> None:
    harnais = HarnaisCompte()
    store = SessionStore(reglages, harnais)
    rec = store.create(slug="essai")
    harnais.pendant_le_tour = lambda sid: store.patch(sid, archived=True)
    store.send(rec.session_id, "travaille")
    assert store.get(rec.session_id).state == "archived"


def test_une_conversation_supprimee_pendant_le_tour_ne_ressuscite_pas(reglages) -> None:
    harnais = HarnaisCompte()
    store = SessionStore(reglages, harnais)
    rec = store.create(slug="essai")
    harnais.pendant_le_tour = lambda sid: store.delete(sid)
    store.send(rec.session_id, "travaille")
    assert store.get(rec.session_id) is None


def test_supprimer_une_conversation_en_cours_arrete_son_tour(reglages) -> None:
    arretes: list[str] = []

    class Suivi(HarnaisCompte):
        def interrupt(self, session_id: str):  # type: ignore[override]
            arretes.append(session_id)
            return True

    store = SessionStore(reglages, Suivi())
    rec = store.create(slug="essai")
    rec.state = "running"
    store.save(rec)
    store.delete(rec.session_id)
    assert arretes == [rec.session_id]
