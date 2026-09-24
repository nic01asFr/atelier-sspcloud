"""Les applications des projets : ce qu'un projet sert derrière l'Atelier.

Un artefact est un dossier `artifacts/<nom>/` d'un projet, servi à une
adresse de l'hôte des applications : en bac à sable s'il ne contient que des
fichiers, relayé vers un processus s'il porte un `artefact.json` de service
(voir `manifeste`). L'Atelier lance et surveille ces processus (voir
`superviseur`) ; rien n'est jamais servi sur l'origine de l'Atelier.
Conception : `docs/atelier-applications.md`.
"""

from __future__ import annotations

from .manifeste import (
    Manifeste,
    ManifesteInvalide,
    charger_manifeste,
    lister_artefacts,
    nom_valide,
)

__all__ = [
    "Manifeste",
    "ManifesteInvalide",
    "charger_manifeste",
    "lister_artefacts",
    "nom_valide",
]
