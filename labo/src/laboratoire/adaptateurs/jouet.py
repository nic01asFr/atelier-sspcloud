"""L'adaptateur « jouet » : un classifieur au plus proche centre, sur des images réduites en niveaux de gris.

Il n'est pas là pour classer des voitures, mais pour **éprouver toute la chaîne sans GPU** : configuration, file, sous-processus, journal,
métriques, évaluation, résultats scellés. Une chaîne qui marche avec le jouet marche avec n'importe quelle famille qui respecte `Adaptateur`.
"""

from __future__ import annotations

import json

import numpy as np
from PIL import Image

from laboratoire.adaptateurs.base import ContexteEssai, Prediction
from laboratoire.modeles import Methode

REGLAGES_CONNUS = {"echec": "fait échouer l'entraînement (pour éprouver les erreurs)", "lenteur_s": "attente avant d'entraîner"}


class Jouet:
    famille = "jouet"

    def valider(self, methode: Methode) -> None:
        inconnus = sorted(set(methode.reglages) - set(REGLAGES_CONNUS))
        if inconnus:
            raise ValueError(f"réglages inconnus pour « jouet » : {inconnus} (connus : {sorted(REGLAGES_CONNUS)})")

    @staticmethod
    def _vecteur(chemin, cote: int) -> np.ndarray:
        with Image.open(chemin) as im:
            return np.asarray(im.convert("L").resize((cote, cote)), dtype=np.float64).ravel() / 255.0

    def entrainer(self, ctx: ContexteEssai) -> None:
        reglages = ctx.config.methode.reglages
        if reglages.get("lenteur_s"):
            import time

            time.sleep(float(reglages["lenteur_s"]))
        if reglages.get("echec"):
            raise RuntimeError("échec demandé par le réglage « echec »")
        cote = max(2, min(ctx.config.methode.imgsz, 32))
        sommes: dict[str, np.ndarray] = {}
        comptes: dict[str, int] = {}
        for e in ctx.variante.echantillons("train"):
            v = self._vecteur(e.fichier, cote)
            sommes[e.classe] = sommes.get(e.classe, 0) + v
            comptes[e.classe] = comptes.get(e.classe, 0) + 1
        if not comptes:
            raise RuntimeError("le jeu d'entraînement est vide")
        centres = {c: (sommes[c] / comptes[c]).tolist() for c in sommes}
        (ctx.poids / "centres.json").write_text(json.dumps({"cote": cote, "centres": centres}), encoding="utf-8")
        ctx.metrique(epoque=1, images=sum(comptes.values()))

    def predire(self, ctx: ContexteEssai, jeu: str) -> list[Prediction]:
        modele = json.loads((ctx.poids / "centres.json").read_text(encoding="utf-8"))
        centres = {c: np.asarray(v) for c, v in modele["centres"].items()}
        sorties = []
        for e in ctx.variante.echantillons(jeu):
            v = self._vecteur(e.fichier, modele["cote"])
            sorties.append(Prediction(e, min(centres, key=lambda c: float(np.sum((centres[c] - v) ** 2)))))
        return sorties
