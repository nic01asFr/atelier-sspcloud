"""Le bloc `deploiement` de `.atelier/projet.json` : optionnel, strict.

Il borne ce qu'Onyxia donne aux agents code du projet (`docs/onyxia-projet.md`) :
un champ inconnu, un pod mal nommé ou un déploiement qui vise à la fois un pod
et un service sont refusés, pas ignorés.
"""

from __future__ import annotations

from typing import Any

import pytest

from mcp_gateway.atelier.commandes import structure


def _projet(deploiement: Any) -> dict[str, Any]:
    return {"slug": "carte", "titre": "Carte", "deploiement": deploiement}


def test_sans_deploiement_le_projet_reste_valide() -> None:
    p = structure.valider({"slug": "carte", "titre": "Carte"})
    assert p.deploiement is None
    assert "deploiement" not in p.en_json()


@pytest.mark.parametrize(
    "deploiement",
    [
        {"pod": "proj-carte-jupyter-python-0"},
        {"pod": "proj-carte-jupyter-python-0", "namespace": "user-nic01asfr", "gpu": True,
         "commande": "uvicorn app:app --port 8000", "port": 8000},
        {"service": "carte.service.yml"},
        {"service": "services/carte.service.yaml", "gpu": True},
    ],
)
def test_deploiement_valide(deploiement: dict[str, Any]) -> None:
    p = structure.valider(_projet(deploiement))
    assert p.deploiement is not None
    assert p.en_json()["deploiement"] == {**{"gpu": False}, **deploiement}


@pytest.mark.parametrize(
    "deploiement",
    [
        {},
        {"pod": "a", "service": "a.service.yml"},
        {"pod": "Pod_Majuscule"},
        {"pod": "a", "namespace": "Espace Nom"},
        {"pod": "a", "gpu": "oui"},
        {"pod": "a", "port": 0},
        {"pod": "a", "port": 70000},
        {"pod": "a", "port": "8000"},
        {"pod": "a", "inconnu": 1},
        {"service": "carte.yml"},
        {"pod": "a", "commande": ""},
        "proj-carte",
    ],
)
def test_deploiement_hors_schema_est_refuse(deploiement: Any) -> None:
    with pytest.raises(structure.ErreurProjetJson):
        structure.valider(_projet(deploiement))
