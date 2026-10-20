"""YOLO classify (ultralytics) : la première famille réelle.

Réglages d'entraînement posés **par le laboratoire** et non laissés aux défauts, après les deux essais du 19/10 qui ne valaient rien :
- pas de miroir (`fliplr=0`, `flipud=0`) : retourner l'image d'un modèle « côté droit » change le côté de la rue ;
- pas d'arrêt anticipé (`patience` = nombre d'époques) et **on évalue le dernier poids**, pas `best.pt` : le « meilleur » poids est choisi par
  ultralytics sur l'exactitude de validation, que gonfle la classe majoritaire ;
- décroissance cosinus du taux d'apprentissage, graine fixée par la configuration.

L'import d'ultralytics se fait à l'usage : le laboratoire se teste sans lui.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path
from typing import Any

from laboratoire.adaptateurs.base import ContexteEssai, Prediction
from laboratoire.modeles import Methode

# Réglages que la personne ou l'agent peuvent poser, avec leur type. Tout autre réglage est refusé : une faute de frappe ne se perd pas.
REGLAGES_AUTORISES: dict[str, type | tuple[type, ...]] = {
    "fliplr": (int, float), "flipud": (int, float), "degrees": (int, float), "translate": (int, float), "scale": (int, float),
    "hsv_h": (int, float), "hsv_s": (int, float), "hsv_v": (int, float), "erasing": (int, float), "auto_augment": str,
    "lr0": (int, float), "lrf": (int, float), "momentum": (int, float), "weight_decay": (int, float), "dropout": (int, float),
    "label_smoothing": (int, float), "optimizer": str, "cos_lr": bool, "amp": bool, "pretrained": bool, "freeze": int,
    "workers": int, "patience": int, "warmup_epochs": (int, float),
}

# Posés par le laboratoire ; la configuration peut les changer par `reglages`, mais ils partent avec ces valeurs.
DEFAUTS_DU_LABORATOIRE: dict[str, Any] = {"fliplr": 0.0, "flipud": 0.0, "cos_lr": True}

COLONNES_RESULTATS = {"train/loss": "perte_train", "val/loss": "perte_val", "metrics/accuracy_top1": "exactitude_val_ultralytics"}


def arguments_d_entrainement(methode: Methode, graine: int, donnees: Path, projet: Path, appareil: str) -> dict[str, Any]:
    """Les arguments de `YOLO.train`, tels que le laboratoire les pose. Fonction pure : testée sans ultralytics."""
    args: dict[str, Any] = {
        **DEFAUTS_DU_LABORATOIRE,
        "data": str(donnees),
        "epochs": methode.epochs,
        "imgsz": methode.imgsz,
        "batch": methode.batch,
        "seed": graine,
        "device": appareil,
        "project": str(projet),
        "name": "run",
        "exist_ok": True,
        "patience": methode.epochs,  # pas d'arrêt anticipé : on mesure le dernier poids
        "plots": False,
        "verbose": False,
    }
    args.update(methode.reglages)
    return args


class YoloClassify:
    famille = "yolo_cls"

    def valider(self, methode: Methode) -> None:
        if not methode.modele.endswith("-cls"):
            raise ValueError(f"« {methode.modele} » n'est pas un modèle de classification (attendu : yolo26n-cls, yolo26s-cls…)")
        for nom, valeur in methode.reglages.items():
            if nom not in REGLAGES_AUTORISES:
                raise ValueError(f"réglage inconnu pour yolo_cls : {nom!r} (connus : {sorted(REGLAGES_AUTORISES)})")
            attendu = REGLAGES_AUTORISES[nom]
            if isinstance(valeur, bool) and attendu not in (bool,):
                raise ValueError(f"réglage {nom!r} : un nombre est attendu, pas un booléen")
            if not isinstance(valeur, attendu):  # type: ignore[arg-type]
                raise ValueError(f"réglage {nom!r} : type attendu {attendu}, reçu {type(valeur).__name__}")

    @staticmethod
    def _appareil() -> str:
        try:
            import torch

            return "0" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def entrainer(self, ctx: ContexteEssai) -> None:
        from ultralytics import YOLO  # noqa: PLC0415 - à l'usage seulement

        m = ctx.config.methode
        modele = YOLO(f"{m.modele}.pt")
        args = arguments_d_entrainement(m, ctx.config.graine, ctx.variante.dossier, ctx.dossier / "yolo", self._appareil())
        print(f"[yolo_cls] arguments : { {k: v for k, v in args.items() if k not in ('data', 'project')} }", flush=True)
        modele.train(**args)
        dernier = ctx.dossier / "yolo" / "run" / "weights" / "last.pt"
        if not dernier.is_file():
            raise RuntimeError(f"ultralytics n'a pas laissé de last.pt ({dernier})")
        shutil.copy2(dernier, ctx.poids / "last.pt")
        self._reprendre_les_metriques(ctx, ctx.dossier / "yolo" / "run" / "results.csv")

    @staticmethod
    def _reprendre_les_metriques(ctx: ContexteEssai, resultats: Path) -> None:
        if not resultats.is_file():
            return
        with resultats.open(encoding="utf-8", newline="") as f:
            for ligne in csv.DictReader(f):
                ligne = {k.strip(): v.strip() for k, v in ligne.items()}
                sortie: dict[str, Any] = {"epoque": int(float(ligne.get("epoch", 0)))}
                for source, cible in COLONNES_RESULTATS.items():
                    if source in ligne:
                        sortie[cible] = float(ligne[source])
                ctx.metrique(**sortie)

    def predire(self, ctx: ContexteEssai, jeu: str) -> list[Prediction]:
        from ultralytics import YOLO  # noqa: PLC0415

        echantillons = ctx.variante.echantillons(jeu)
        if not echantillons:
            return []
        modele = YOLO(str(ctx.poids / "last.pt"))
        sorties: list[Prediction] = []
        for e in echantillons:
            r = modele.predict(source=str(e.fichier), imgsz=ctx.config.methode.imgsz, device=self._appareil(), verbose=False)[0]
            sorties.append(Prediction(e, r.names[r.probs.top1]))
        return sorties
