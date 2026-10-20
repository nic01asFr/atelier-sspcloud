"""L'adaptateur YOLO, éprouvé sans ultralytics : les arguments qu'il pose et les réglages qu'il refuse."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from conftest import faire_variante
from laboratoire.adaptateurs.base import ContexteEssai
from laboratoire.adaptateurs.yolo_cls import DEFAUTS_DU_LABORATOIRE, YoloClassify, arguments_d_entrainement
from laboratoire.modeles import ConfigEssai, Methode
from laboratoire.projet import Racine
from laboratoire.variante import Variante


def _m(**kw) -> Methode:
    base = dict(famille="yolo_cls", modele="yolo26n-cls", imgsz=224, epochs=40, batch=32)
    base.update(kw)
    return Methode(**base)


def test_le_laboratoire_pose_des_reglages_qui_evitent_les_erreurs_du_19_octobre(tmp_path: Path) -> None:
    a = arguments_d_entrainement(_m(), graine=7, donnees=tmp_path / "v", projet=tmp_path / "p", appareil="0")
    assert a["fliplr"] == 0.0 and a["flipud"] == 0.0  # pas de miroir sur un modèle de côté
    assert a["patience"] == a["epochs"] == 40  # pas d'arrêt anticipé sur un critère faussé
    assert a["cos_lr"] is True and a["seed"] == 7 and a["imgsz"] == 224 and a["device"] == "0"
    assert a["exist_ok"] is True and a["name"] == "run"  # le dossier de l'essai est à lui seul


def test_les_reglages_de_la_configuration_l_emportent_sur_les_defauts_du_laboratoire(tmp_path: Path) -> None:
    a = arguments_d_entrainement(_m(reglages={"fliplr": 0.5, "lr0": 0.001}), 0, tmp_path, tmp_path, "cpu")
    assert a["fliplr"] == 0.5 and a["lr0"] == 0.001 and a["flipud"] == DEFAUTS_DU_LABORATOIRE["flipud"]


@pytest.mark.parametrize(
    "reglages, message",
    [
        ({"fliplr_typo": 0.5}, "réglage inconnu"),
        ({"cos_lr": 1}, "type attendu"),
        ({"lr0": True}, "pas un booléen"),
        ({"workers": 2.5}, "type attendu"),
        ({"optimizer": 3}, "type attendu"),
    ],
)
def test_les_reglages_mal_ecrits_sont_refuses(reglages: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        YoloClassify().valider(_m(reglages=reglages))


def test_un_modele_de_detection_est_refuse() -> None:
    with pytest.raises(ValueError, match="classification"):
        YoloClassify().valider(_m(modele="yolo26n"))


def test_un_bon_jeu_de_reglages_passe() -> None:
    YoloClassify().valider(_m(reglages={"fliplr": 0.0, "cos_lr": True, "lr0": 0.01, "optimizer": "AdamW", "workers": 4}))


def test_entrainer_et_predire_avec_un_ultralytics_factice(racine: Racine, monkeypatch: pytest.MonkeyPatch) -> None:
    """On remplace ultralytics : l'adaptateur doit passer les bons arguments, garder last.pt, relire results.csv et nommer les classes prédites."""
    vues: dict = {}

    class FauxProbs:
        top1 = 1

    class FauxResultat:
        names = {0: "clair", 1: "sombre"}
        probs = FauxProbs()

    class FauxYOLO:
        def __init__(self, chemin: str) -> None:
            vues["chemin"] = chemin

        def train(self, **args):
            vues["args"] = args
            poids = Path(args["project"]) / "run" / "weights"
            poids.mkdir(parents=True)
            (poids / "last.pt").write_bytes(b"poids")
            (poids / "best.pt").write_bytes(b"meilleur")
            (Path(args["project"]) / "run" / "results.csv").write_text(
                "epoch,train/loss,val/loss,metrics/accuracy_top1\n 1, 0.9, 0.8, 0.5\n 2, 0.5, 0.6, 0.7\n", encoding="utf-8"
            )

        def predict(self, source, **kw):
            return [FauxResultat()]

    monkeypatch.setitem(sys.modules, "ultralytics", types.SimpleNamespace(YOLO=FauxYOLO))
    d = faire_variante(racine)
    dossier = racine.dossier_essai("E0001")
    dossier.mkdir(parents=True)
    config = ConfigEssai(jeu="v1", methode=_m(epochs=2), graine=3)
    ctx = ContexteEssai(config=config, variante=Variante(d), dossier=dossier)
    yolo = YoloClassify()
    yolo.entrainer(ctx)
    assert vues["chemin"] == "yolo26n-cls.pt" and vues["args"]["data"] == str(d) and vues["args"]["seed"] == 3
    assert (ctx.poids / "last.pt").read_bytes() == b"poids"  # le dernier poids, pas best.pt
    lignes = (dossier / "metriques.csv").read_text(encoding="utf-8").splitlines()
    assert lignes[0] == "epoque,perte_train,perte_val,exactitude_val_ultralytics" and len(lignes) == 3
    predictions = yolo.predire(ctx, "val")
    assert len(predictions) == 8 and {p.predit for p in predictions} == {"sombre"}
