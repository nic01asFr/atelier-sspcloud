"""Les familles de modèle. Un adaptateur s'ajoute ici ; le reste du laboratoire n'a pas à changer."""

from __future__ import annotations

from collections.abc import Callable

from laboratoire.adaptateurs.base import Adaptateur


def _jouet() -> Adaptateur:
    from laboratoire.adaptateurs.jouet import Jouet

    return Jouet()


def _yolo_cls() -> Adaptateur:
    from laboratoire.adaptateurs.yolo_cls import YoloClassify  # importe ultralytics : seulement quand on l'utilise

    return YoloClassify()


FAMILLES: dict[str, Callable[[], Adaptateur]] = {"jouet": _jouet, "yolo_cls": _yolo_cls}


def adaptateur(famille: str) -> Adaptateur:
    if famille not in FAMILLES:
        raise ValueError(f"famille inconnue : {famille!r} (connues : {sorted(FAMILLES)})")
    return FAMILLES[famille]()
