"""Un onglet ouvert doit voir arriver ce qu'on tape dans l'autre fenêtre.

La lecture fond désormais les deux registres, mais rien ne prévenait l'onglet :
il fallait actualiser à la main pour voir un message tapé dans VS Code. Le
canal de diffusion existait déjà — c'est par lui que passe un tour observé
depuis un second onglet — il n'y manquait qu'un guetteur sur le fichier que
l'autre fenêtre écrit.

On ne rejoue pas le flux de VS Code : on ne l'a pas. On dit que le journal a
changé, et l'onglet relit.
"""

from __future__ import annotations

import time
from pathlib import Path

from mcp_gateway.atelier.api import DiffusionDesTours, VeilleDesJournaux


def _veille(registres: list[Path]) -> tuple[VeilleDesJournaux, DiffusionDesTours]:
    diffusion = DiffusionDesTours()
    veille = VeilleDesJournaux(diffusion, lambda _sid: registres)
    veille.INTERVALLE_S = 0.05
    return veille, diffusion


def _attendre(file, delai: float = 3.0):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if not file.empty():
            return file.get_nowait()
        time.sleep(0.02)
    return None


def test_une_ecriture_ailleurs_reveille_l_onglet(tmp_path: Path) -> None:
    registre = tmp_path / "cli.jsonl"
    registre.write_text("depart\n", encoding="utf-8")
    veille, diffusion = _veille([registre])
    file = diffusion.souscrire("s1")
    veille.surveiller("s1")
    try:
        with registre.open("a", encoding="utf-8") as f:
            f.write("un message tape dans VS Code\n")
        ev = _attendre(file)
    finally:
        veille.relacher("s1")

    assert ev is not None, "l'onglet n'a jamais été prévenu"
    assert ev.kind == "systeme" and ev.cause == "journal_change"


def test_un_journal_qui_ne_bouge_pas_ne_reveille_personne(tmp_path: Path) -> None:
    """Sinon l'onglet relirait la conversation entière toutes les deux secondes."""
    registre = tmp_path / "cli.jsonl"
    registre.write_text("depart\n", encoding="utf-8")
    veille, diffusion = _veille([registre])
    file = diffusion.souscrire("s1")
    veille.surveiller("s1")
    try:
        time.sleep(0.4)
    finally:
        veille.relacher("s1")

    assert file.empty()


def test_un_registre_absent_ne_fait_pas_tomber_la_veille(tmp_path: Path) -> None:
    """Une conversation jamais ouverte dans VS Code n'a pas de transcript CLI."""
    absent = tmp_path / "jamais-ecrit.jsonl"
    present = tmp_path / "atelier.jsonl"
    present.write_text("a\n", encoding="utf-8")
    veille, diffusion = _veille([present, absent])
    file = diffusion.souscrire("s1")
    veille.surveiller("s1")
    try:
        with present.open("a", encoding="utf-8") as f:
            f.write("b\n")
        ev = _attendre(file)
    finally:
        veille.relacher("s1")

    assert ev is not None


def test_deux_onglets_ne_font_qu_une_veille(tmp_path: Path) -> None:
    """Et le départ du premier ne doit pas aveugler le second."""
    registre = tmp_path / "cli.jsonl"
    registre.write_text("a\n", encoding="utf-8")
    veille, diffusion = _veille([registre])
    un = diffusion.souscrire("s1")
    deux = diffusion.souscrire("s1")
    veille.surveiller("s1")
    veille.surveiller("s1")
    try:
        veille.relacher("s1")  # le premier onglet se ferme
        with registre.open("a", encoding="utf-8") as f:
            f.write("b\n")
        assert _attendre(deux) is not None, "le second onglet a cessé d'être prévenu"
    finally:
        veille.relacher("s1")


def test_la_veille_s_arrete_quand_plus_personne_ne_regarde(tmp_path: Path) -> None:
    """Un guetteur par conversation abandonnée finirait par en faire beaucoup."""
    registre = tmp_path / "cli.jsonl"
    registre.write_text("a\n", encoding="utf-8")
    veille, diffusion = _veille([registre])
    file = diffusion.souscrire("s1")
    veille.surveiller("s1")
    veille.relacher("s1")
    time.sleep(0.2)

    with registre.open("a", encoding="utf-8") as f:
        f.write("b\n")
    assert _attendre(file, delai=0.4) is None


def test_la_veille_absorbe_avant_de_prevenir(tmp_path: Path) -> None:
    """Sinon ce qui n'existe que dans le registre du CLI reste chez lui."""
    registre = tmp_path / "cli.jsonl"
    registre.write_text("a\n", encoding="utf-8")
    diffusion = DiffusionDesTours()
    absorbe: list[str] = []
    veille = VeilleDesJournaux(diffusion, lambda _s: [registre], absorbe.append)
    veille.INTERVALLE_S = 0.05
    file = diffusion.souscrire("s1")
    veille.surveiller("s1")
    try:
        with registre.open("a", encoding="utf-8") as f:
            f.write("b\n")
        ev = _attendre(file)
    finally:
        veille.relacher("s1")

    assert ev is not None
    assert absorbe == ["s1"], "l'absorption n'a pas eu lieu, ou pas une seule fois"


def test_notre_propre_ecriture_ne_relance_pas_la_veille(tmp_path: Path) -> None:
    """Absorber fait grossir notre journal.

    Sans reprendre l'empreinte après coup, la veille se réveillerait sur sa
    propre écriture, indéfiniment.
    """
    registre = tmp_path / "cli.jsonl"
    registre.write_text("a\n", encoding="utf-8")
    diffusion = DiffusionDesTours()

    def absorber(_sid: str) -> None:
        with registre.open("a", encoding="utf-8") as f:
            f.write("ce que l absorption ajoute\n")

    veille = VeilleDesJournaux(diffusion, lambda _s: [registre], absorber)
    veille.INTERVALLE_S = 0.05
    file = diffusion.souscrire("s1")
    veille.surveiller("s1")
    try:
        with registre.open("a", encoding="utf-8") as f:
            f.write("b\n")
        assert _attendre(file) is not None
        time.sleep(0.3)
        restants = 0
        while not file.empty():
            file.get_nowait()
            restants += 1
    finally:
        veille.relacher("s1")

    assert restants == 0, f"la veille s'est réveillée {restants} fois sur elle-même"
