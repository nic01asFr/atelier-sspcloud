"""Un agent qui en lance un autre reçoit ses demandes : relancé s'il dort, mis en file s'il travaille."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from mcp_gateway.atelier.decisions import Demande
from mcp_gateway.atelier.lancements import Lancement
from mcp_gateway.atelier.relais_au_lanceur import (
    DELAI_LANCEUR_OCCUPE_S,
    RELAIS_MAX,
    RelaisAuLanceur,
    conversation_du_lanceur,
)


class _Decisions:
    def __init__(self) -> None:
        self.vivantes: dict[str, Demande] = {}

    def demande(self, rid: str) -> Demande | None:
        return self.vivantes.get(rid)


class _Store:
    def __init__(self, occupes: set[str] | None = None) -> None:
        self.envois: list[tuple[str, str, bool]] = []
        self.decisions = _Decisions()
        self.harness = SimpleNamespace(tour_en_cours=lambda sid: sid in (occupes or set()), decisions=self.decisions)
        self.connues = {"lanceur-1", "enfant-1"}

    def get(self, sid: str) -> Any | None:
        return object() if sid in self.connues else None

    def send(self, sid: str, texte: str, peut_attendre: bool = False, **_: Any) -> None:
        self.envois.append((sid, texte, peut_attendre))


class _Lanceur:
    def __init__(self, *lancements: Lancement) -> None:
        self.fiches = {l.id: l for l in lancements}

    def tous(self) -> list[Lancement]:
        return list(self.fiches.values())

    def lire(self, ident: str) -> Lancement | None:
        return self.fiches.get(ident)

    def _ecrire(self, l: Lancement) -> None:
        self.fiches[l.id] = l


def _lancement(**kw: Any) -> Lancement:
    base = dict(
        id="lc-1", origine="conversation:lanceur-1", acteur="conversation:lanceur-1", projet="demo",
        nom="verif", conversation="enfant-1", supervise=True,
    )
    base.update(kw)
    return Lancement(**base)


def _relais(tmp_path: Path, store: _Store, lanceur: _Lanceur, journal: list[float] | None = None) -> RelaisAuLanceur:
    (tmp_path / "demo").mkdir(exist_ok=True)
    return RelaisAuLanceur(
        store=store,
        lanceur=lanceur,
        projets=tmp_path,
        attendre=(journal.append if journal is not None else (lambda s: None)),
        en_fil=lambda travail: travail(),
    )


def _demande(tmp_path: Path, rid: str = "r1", outil: str = "Write", **kw: Any) -> Demande:
    args = kw.pop("arguments", {"file_path": str(tmp_path / "demo" / "a.txt"), "content": "x"})
    return Demande(request_id=rid, session_id="enfant-1", outil=outil, arguments=args, **kw)


def test_l_origine_dit_qui_est_le_lanceur() -> None:
    assert conversation_du_lanceur("conversation:abc") == "abc"
    for autre in ("wikichat:trigger", "gardien:sante", "", "modele"):
        assert conversation_du_lanceur(autre) == ""


def test_un_lanceur_inactif_est_relance_par_la_demande(tmp_path: Path) -> None:
    store, lanceur = _Store(), _Lanceur(_lancement())
    _relais(tmp_path, store, lanceur).demande("attendue", _demande(tmp_path))
    (sid, texte, peut_attendre), = store.envois
    assert sid == "lanceur-1" and peut_attendre
    assert texte.startswith("[Atelier]")  # un message de l'Atelier, jamais pris pour la personne
    assert 'demande="r1"' in texte and "Write" in texte and "lc-1" in texte


def test_une_demande_n_est_relayee_qu_une_fois_meme_apres_la_veille(tmp_path: Path) -> None:
    store, lanceur = _Store(), _Lanceur(_lancement())
    relais = _relais(tmp_path, store, lanceur)
    d = _demande(tmp_path)
    relais.demande("attendue", d)
    relais.demande("veille", d)
    assert len(store.envois) == 1
    assert lanceur.fiches["lc-1"].relayees == ["demande:r1"]
    # Un autre relais (redémarrage) lit la fiche et ne répète pas.
    _relais(tmp_path, store, lanceur).demande("veille", d)
    assert len(store.envois) == 1


def test_un_lanceur_occupe_a_le_temps_de_repondre_de_lui_meme(tmp_path: Path) -> None:
    store, lanceur, attentes = _Store(occupes={"lanceur-1"}), _Lanceur(_lancement()), []
    d = _demande(tmp_path)
    store.decisions.vivantes["r1"] = d
    relais = _relais(tmp_path, store, lanceur, attentes)

    store.decisions.vivantes.pop("r1")  # il a répondu pendant le délai
    relais.demande("attendue", d)
    assert attentes == [DELAI_LANCEUR_OCCUPE_S] and store.envois == []

    d2 = _demande(tmp_path, "r2")
    store.decisions.vivantes["r2"] = d2  # toujours en attente après le délai : mise en file
    relais.demande("attendue", d2)
    assert len(store.envois) == 1 and 'demande="r2"' in store.envois[0][1]


def test_ce_qui_depasse_le_perimetre_reste_a_la_personne(tmp_path: Path) -> None:
    store, lanceur = _Store(), _Lanceur(_lancement())
    hors = _demande(tmp_path, arguments={"file_path": "/etc/passwd", "content": "x"})
    _relais(tmp_path, store, lanceur).demande("attendue", hors)
    assert store.envois == [] and lanceur.fiches["lc-1"].relayees == []


def test_seuls_les_lancements_supervises_par_un_agent_sont_relayes(tmp_path: Path) -> None:
    d = _demande(tmp_path)
    for fiche in (
        _lancement(supervise=False),
        _lancement(origine="wikichat:trigger", acteur="wikichat"),
        _lancement(origine="gardien:sante"),
        _lancement(origine="conversation:disparue"),
    ):
        store = _Store()
        _relais(tmp_path, store, _Lanceur(fiche)).demande("attendue", d)
        assert store.envois == [], fiche.origine
    store = _Store()
    _relais(tmp_path, store, _Lanceur(_lancement())).demande("posee", d)
    assert store.envois == []  # un autre avis que « attendue » / « veille »


def test_le_nombre_de_messages_par_lancement_est_borne(tmp_path: Path) -> None:
    store = _Store()
    lanceur = _Lanceur(_lancement(relayees=[f"demande:x{i}" for i in range(RELAIS_MAX)]))
    _relais(tmp_path, store, lanceur).demande("attendue", _demande(tmp_path))
    assert store.envois == []


def test_une_question_posee_a_la_personne_reste_a_la_personne(tmp_path: Path) -> None:
    """AskUserQuestion s'adresse à la personne ; l'agent lancé interroge son lanceur autrement."""
    store, lanceur = _Store(), _Lanceur(_lancement())
    q = _demande(tmp_path, outil="AskUserQuestion", genre="question",
                 arguments={"questions": [{"question": "Quelle langue ?", "options": []}]})
    _relais(tmp_path, store, lanceur).demande("attendue", q)
    assert store.envois == []


def test_la_fin_reveille_un_lanceur_inactif_pas_un_lanceur_qui_travaille(tmp_path: Path) -> None:
    fini = _lancement(etat="fini", texte="J'ai terminé : 3 fichiers.")
    store = _Store()
    _relais(tmp_path, store, _Lanceur(fini)).fin(fini)
    (sid, texte, _), = store.envois
    assert sid == "lanceur-1" and "est fini" in texte and "3 fichiers" in texte
    assert 'atelier_transcript(conversation="enfant-1")' in texte

    occupe = _Store(occupes={"lanceur-1"})
    _relais(tmp_path, occupe, _Lanceur(fini)).fin(fini)
    assert occupe.envois == []
    # Pas supervisé : rien.
    libre = _lancement(supervise=False, etat="fini")
    s2 = _Store()
    _relais(tmp_path, s2, _Lanceur(libre)).fin(libre)
    assert s2.envois == []


def test_un_envoi_qui_echoue_ne_fait_jamais_echouer_le_tour(tmp_path: Path) -> None:
    store = _Store()

    def casse(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("boum")

    store.send = casse  # type: ignore[method-assign]
    _relais(tmp_path, store, _Lanceur(_lancement())).demande("attendue", _demande(tmp_path))


# ── l'agent lancé interroge son lanceur ─────────────────────────────────────


def test_la_question_de_l_agent_lance_part_au_lanceur_sans_bloquer(tmp_path: Path) -> None:
    store, lanceur = _Store(), _Lanceur(_lancement())
    relais = _relais(tmp_path, store, lanceur)
    rendu = relais.demander("enfant-1", "Quel format pour l'export ?")
    assert rendu["envoyee"] and rendu["a"] == "lanceur-1" and "Ne bloque pas" in rendu["suite"]
    (sid, texte, peut_attendre), = store.envois
    assert sid == "lanceur-1" and peut_attendre and texte.startswith("[Atelier]")
    assert "Quel format pour l'export ?" in texte
    assert 'atelier_envoyer(conversation="enfant-1"' in texte  # comment répondre, sans deviner


def test_la_meme_question_n_est_posee_qu_une_fois(tmp_path: Path) -> None:
    import pytest

    from mcp_gateway.atelier.commandes.modele import Refus

    store, lanceur = _Store(), _Lanceur(_lancement())
    relais = _relais(tmp_path, store, lanceur)
    relais.demander("enfant-1", "Quoi ?")
    with pytest.raises(Refus):
        relais.demander("enfant-1", "Quoi ?")
    relais.demander("enfant-1", "Et ça ?")
    assert len(store.envois) == 2


def test_sans_lanceur_agent_la_question_va_a_la_personne(tmp_path: Path) -> None:
    import pytest

    from mcp_gateway.atelier.commandes.modele import Refus

    for fiche in (_lancement(supervise=False), _lancement(origine="wikichat:trigger"), _lancement(origine="gardien:x")):
        store = _Store()
        with pytest.raises(Refus, match="pose ta question à la personne"):
            _relais(tmp_path, store, _Lanceur(fiche)).demander("enfant-1", "Quoi ?")
        assert store.envois == []
    with pytest.raises(Refus, match="vide"):
        _relais(tmp_path, _Store(), _Lanceur(_lancement())).demander("enfant-1", "  ")
    with pytest.raises(Refus):  # une conversation qui n'est pas un lancement
        _relais(tmp_path, _Store(), _Lanceur()).demander("enfant-1", "Quoi ?")
