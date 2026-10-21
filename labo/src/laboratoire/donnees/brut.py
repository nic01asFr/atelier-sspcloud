"""Lire les données brutes telles qu'elles sont rangées, sans rien deviner en silence.

Structure rencontrée (images annotées de stationnement) :

    <brut>/<ville>/<a>/<b>/<côté>/<N>/<image>              N places, pas de forme
    <brut>/<ville>/<a>/<b>/<côté>/<N>/<forme>/<image>      N places ET une forme (bataille, longitudinal)
    <brut>/<ville>/<a>/<b>/<côté>/<forme>/<image>          une forme seule

`a` et `b` sont l'identifiant de route (BDTOPO) et celui de la collection (Panoramax), **dans un ordre qui n'est pas le même partout** (le dossier
FONTAINE1 les a inversés) : on ne choisit pas lequel est la collection, on prend le couple, qui identifie la collection d'une manière ou de l'autre.

Un dossier ou un fichier qui ne rentre dans aucun de ces cas n'est ni ignoré ni classé au hasard : il est listé dans `anomalies`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

COTES = ("droite", "gauche")
FORMES = ("bataille", "longitudinal")
EXTENSIONS = {".jpg", ".jpeg", ".png"}
# Deux sortes d'images dans le brut (constatées sur les fichiers d'origine, voir docs/vision/validation-humaine.md §11) :
#  - la photo « plate » 2048×1536, prise vers l'avant (champ de 92°) : le même fichier est rangé sous droite/ et sous gauche/,
#    et le côté est la **moitié** de la photo ;
#  - le « recadrage » 768×512, extrait d'une vue panoramique à 360° : un fichier **différent** par côté, déjà tourné vers ce côté.
LARGEUR_PHOTO_PLATE = 1500


@dataclass(frozen=True)
class ImageBrute:
    chemin: str  # relatif au dossier brut, avec des « / »
    ville: str
    groupe: str  # « ville/a/b » : la collection
    cote: str
    n: int | None
    forme: str | None
    largeur: int | None
    hauteur: int | None

    @property
    def plate(self) -> bool:
        """Une photo prise vers l'avant, pleine résolution : le côté en est une moitié. Sinon c'est un recadrage déjà tourné vers son côté."""
        return bool(self.largeur and self.largeur >= LARGEUR_PHOTO_PLATE)


@dataclass
class RapportBrut:
    images: list[ImageBrute] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)

    def resume(self) -> dict[str, object]:
        def compte(cle) -> dict[str, int]:
            sortie: dict[str, int] = {}
            for i in self.images:
                k = str(cle(i))
                sortie[k] = sortie.get(k, 0) + 1
            return dict(sorted(sortie.items()))

        return {
            "images": len(self.images),
            "collections": len({i.groupe for i in self.images}),
            "par_cote": compte(lambda i: i.cote),
            "par_nombre": compte(lambda i: "—" if i.n is None else i.n),
            "par_forme": compte(lambda i: i.forme or "—"),
            "plates": sum(1 for i in self.images if i.plate),
            "recadrages": sum(1 for i in self.images if not i.plate),
            "taille_inconnue": sum(1 for i in self.images if i.largeur is None),
            "anomalies": len(self.anomalies),
        }


def _taille(chemin: Path) -> tuple[int | None, int | None]:
    try:
        with Image.open(chemin) as im:  # n'ouvre que l'en-tête
            return im.size
    except Exception:  # noqa: BLE001 - une image illisible est signalée, pas fatale
        return None, None


def scanner(dossier: Path, lire_taille: bool = True) -> RapportBrut:
    dossier = Path(dossier)
    rapport = RapportBrut()
    if not dossier.is_dir():
        rapport.anomalies.append(f"dossier brut introuvable : {dossier}")
        return rapport
    for chemin in sorted(dossier.rglob("*")):
        if not chemin.is_file() or chemin.suffix.lower() not in EXTENSIONS:
            continue
        relatif = chemin.relative_to(dossier).parts
        nom = "/".join(relatif)
        if len(relatif) < 6:
            rapport.anomalies.append(f"{nom} : trop peu de niveaux (attendu ville/a/b/côté/classe/image)")
            continue
        ville, a, b, cote, *reste = relatif
        if cote not in COTES:
            rapport.anomalies.append(f"{nom} : côté inconnu « {cote} » (attendu : {', '.join(COTES)})")
            continue
        n: int | None = None
        forme: str | None = None
        premiere = reste[0]
        if premiere.isdigit() and len(reste) in (2, 3):
            n = int(premiere)
            if len(reste) == 3:
                if reste[1] not in FORMES:
                    rapport.anomalies.append(f"{nom} : forme inconnue « {reste[1]} » (attendu : {', '.join(FORMES)})")
                    continue
                forme = reste[1]
        elif premiere in FORMES and len(reste) == 2:
            forme = premiere
        else:
            rapport.anomalies.append(f"{nom} : dossier de classe inconnu ou profondeur inattendue (« {'/'.join(reste[:-1])} »)")
            continue
        largeur, hauteur = _taille(chemin) if lire_taille else (None, None)
        rapport.images.append(ImageBrute(nom, ville, f"{ville}/{a}/{b}", cote, n, forme, largeur, hauteur))
    return rapport
