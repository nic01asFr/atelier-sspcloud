"""La famille « profondeur » : pas d'entraînement ; on fait tourner un modèle de profondeur sur des panoramas (voir `laboratoire.profondeur`)."""

from __future__ import annotations

from laboratoire.adaptateurs.base import ContexteEssai
from laboratoire.modeles import Methode
from laboratoire.profondeur.executer import executer, reglages_complets
from laboratoire.profondeur.modeles_profondeur import MODELES


class Profondeur:
    famille = "profondeur"
    tache = "profondeur"

    def valider(self, methode: Methode) -> None:
        if methode.modele not in MODELES:
            raise ValueError(f"modèle de profondeur inconnu : {methode.modele!r} (connus : {sorted(MODELES)})")
        reglages_complets(dict(methode.reglages))

    def entrainer(self, ctx: ContexteEssai) -> None:  # pas d'entraînement
        return None

    def predire(self, ctx: ContexteEssai, jeu: str):  # la mesure de classification n'a pas de sens ici
        raise NotImplementedError("la profondeur se mesure par `executer`, pas par des classes")

    def executer(self, ctx: ContexteEssai) -> None:
        executer(ctx)
