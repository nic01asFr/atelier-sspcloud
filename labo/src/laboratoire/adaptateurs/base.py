"""Ce qu'une famille de modèle doit savoir faire. Le reste du laboratoire n'en sait pas davantage."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from laboratoire.modeles import ConfigEssai, Methode
from laboratoire.variante import Echantillon, Variante


@dataclass
class ContexteEssai:
    config: ConfigEssai
    variante: Variante
    dossier: Path  # essais/<id>/
    metriques_ecrites: int = field(default=0, init=False)

    @property
    def poids(self) -> Path:
        d = self.dossier / "poids"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def metrique(self, **colonnes: Any) -> None:
        """Ajoute une ligne à metriques.csv (une par époque). Les colonnes sont celles de la première ligne."""
        chemin = self.dossier / "metriques.csv"
        nouveau = not chemin.exists()
        with chemin.open("a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(colonnes))
            if nouveau:
                w.writeheader()
            w.writerow(colonnes)
        self.metriques_ecrites += 1


@dataclass(frozen=True)
class Prediction:
    echantillon: Echantillon
    predit: str


class Adaptateur(Protocol):
    famille: str

    def valider(self, methode: Methode) -> None:
        """Refuse un réglage que la famille ne connaît pas (ValueError). Une faute de frappe ne doit pas être ignorée."""

    def entrainer(self, ctx: ContexteEssai) -> None:
        """Entraîne et range les poids dans ctx.poids ; une ligne de ctx.metrique par époque."""

    def predire(self, ctx: ContexteEssai, jeu: str) -> list[Prediction]:
        """Prédit tout le jeu demandé (val ou test), avec les poids de ctx.poids."""
