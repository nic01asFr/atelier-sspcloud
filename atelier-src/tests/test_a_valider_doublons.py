"""La file « À valider » ne garde pas la même idée sous des mots voisins.

Registre D-34 : 49 propositions de mémoire en attente, dont des quasi-doublons
rédigés différemment par la routine de nuit. L'empreinte du texte exact ne les
rapprochait pas.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_gateway.atelier.commandes.a_valider import FileAValider, sont_proches


@pytest.mark.parametrize(
    "a, b",
    [
        ("Retenir (préférence) : Messages très courts et directs", "Retenir (préférence) : Travaille par messages courts et directs"),
        ("Retenir (préférence) : L'utilisateur refuse les placeholders", "Retenir (préférence) : Refuse les placeholders et les approximations"),
        ("Retenir (profil) : Gère plusieurs projets Atelier", "Retenir (profil) : Gère de nombreux projets de l'Atelier"),
    ],
)
def test_deux_formulations_de_la_meme_idee_sont_proches(a: str, b: str) -> None:
    assert sont_proches(a, b)


@pytest.mark.parametrize(
    "a, b",
    [
        ("Retenir (préférence) : Messages très courts et directs", "Retenir (préférence) : Attend des bilans condensés"),
        ("Retenir (profil) : Travaille sur les données territoriales", "Retenir (profil) : Travaille sur la visualisation de profondeur"),
        ("Retenir (préférence) : Exige OAuth", "Retenir (préférence) : Exige HTTPS"),
    ],
)
def test_deux_idees_distinctes_ne_se_confondent_pas(a: str, b: str) -> None:
    assert not sont_proches(a, b)


def test_le_prefixe_de_la_proposition_ne_rapproche_pas_deux_idees(tmp_path: Path) -> None:
    """« Retenir (préférence) : » est dans tous les titres : il ne doit pas compter."""
    assert not sont_proches("Retenir (préférence) : Exige OAuth", "Retenir (préférence) : Aime le bleu")


def _file(tmp_path: Path) -> FileAValider:
    return FileAValider(tmp_path / "a-valider")


def test_la_file_fusionne_les_quasi_doublons_de_la_memoire(tmp_path: Path) -> None:
    f = _file(tmp_path)
    p1 = f.deposer("memoire", "Retenir (préférence) : Messages très courts et directs", projet="snn")
    p2 = f.deposer("memoire", "Retenir (préférence) : Travaille par messages courts et directs", projet="snn")
    assert p2.id == p1.id and p2.occurrences == 2
    assert len(f.lister()) == 1, "une seule entrée, qui compte ses redites"


def test_pas_de_fusion_entre_projets_ni_entre_sources(tmp_path: Path) -> None:
    f = _file(tmp_path)
    f.deposer("memoire", "Retenir (préférence) : Messages très courts et directs", projet="snn")
    f.deposer("memoire", "Retenir (préférence) : Travaille par messages courts et directs", projet="atlas")
    f.deposer("agent", "Retenir (préférence) : Travaille par messages courts et directs", projet="snn")
    assert len(f.lister()) == 3


def test_une_proposition_deja_tranchee_n_absorbe_pas_la_suivante(tmp_path: Path) -> None:
    f = _file(tmp_path)
    p = f.deposer("memoire", "Retenir (préférence) : Messages très courts et directs", projet="snn")
    f.trancher(p.id, "refusee", par="personne")
    neuve = f.deposer("memoire", "Retenir (préférence) : Travaille par messages courts et directs", projet="snn")
    assert neuve.id != p.id, "ce qui a été refusé peut être reproposé : c'est à la personne d'y revenir"
