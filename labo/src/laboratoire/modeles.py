"""Les objets du laboratoire, écrits en configuration : tout se rejoue, rien ne se devine.

Une configuration d'essai se compose de **quoi** (un jeu de données, par l'identifiant de sa variante) et de **comment** (une méthode et ses
réglages, une graine, un pli). Son empreinte ne dépend pas de la note qu'on y ajoute : deux essais de même empreinte sont le même essai.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from laboratoire.empreinte import empreinte

Etat = Literal["en_file", "en_cours", "termine", "echoue", "arrete", "interrompu"]

# Ce qu'un essai peut devenir. Un essai terminé, échoué ou arrêté ne repart pas : on en crée un autre (on rejoue), la trace reste.
TRANSITIONS: dict[str, frozenset[str]] = {
    "en_file": frozenset({"en_cours", "arrete"}),
    "en_cours": frozenset({"termine", "echoue", "arrete", "interrompu"}),
    "interrompu": frozenset({"en_file", "arrete"}),
    "termine": frozenset(),
    "echoue": frozenset(),
    "arrete": frozenset(),
}
ETATS_FINAUX = frozenset({"termine", "echoue", "arrete"})

Scalaire = str | int | float | bool | None


class Methode(BaseModel):
    """Une famille de modèle et ses réglages. Les réglages hors schéma de la famille sont refusés par son adaptateur, pas ignorés."""

    model_config = ConfigDict(extra="forbid")

    famille: str = Field(min_length=1)
    modele: str = Field(min_length=1)
    imgsz: int = Field(default=64, ge=8, le=2048)
    epochs: int = Field(default=40, ge=1, le=1000)
    batch: int = Field(default=32, ge=1, le=4096)
    reglages: dict[str, Scalaire] = Field(default_factory=dict)


class ConfigEssai(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jeu: str = Field(min_length=1, description="identifiant de la variante de jeu de données")
    methode: Methode
    graine: int = 0
    # Pli de la validation croisée par groupes ; None : le découpage unique du jeu.
    pli: int | None = Field(default=None, ge=0)
    note: str = ""

    @field_validator("note")
    @classmethod
    def _note_courte(cls, v: str) -> str:
        if len(v) > 2000:
            raise ValueError("la note dépasse 2000 caractères")
        return v

    def sans_note(self) -> dict[str, Any]:
        d = self.model_dump()
        d.pop("note", None)
        return d

    def empreinte(self) -> str:
        return empreinte(self.sans_note())
