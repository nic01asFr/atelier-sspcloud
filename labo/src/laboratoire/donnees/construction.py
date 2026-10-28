"""Construire une variante sur disque à partir d'un plan : images préparées, manifeste, recette et contrôles.

    <variante>/manifeste.csv   <variante>/recette.json   <variante>/controles.json   <variante>/<jeu>/<classe>/<groupe>__<nom>-<h>[__dupN].jpg

La construction est atomique : tout est écrit dans un dossier voisin puis renommé, une variante à moitié écrite n'existe jamais.
Le brut n'est jamais modifié. Une variante déjà construite pour la même recette (même empreinte) est réutilisée, pas refaite.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Callable

from PIL import Image

from laboratoire.donnees.brut import ImageBrute
from laboratoire.donnees.controles import Ligne, bloquants, controler
from laboratoire.donnees.recette import Plan, Recette
from laboratoire.variante import COLONNES

QUALITE_JPEG = 95
_SUR = re.compile(r"[^A-Za-z0-9._-]+")


class ConstructionRefusee(Exception):
    pass


def nom_sur(texte: str) -> str:
    return _SUR.sub("_", texte).strip("._") or "x"


def preparer(image: Image.Image, cote: str, preparation: str) -> Image.Image:
    """`rognage` : ne garde que la moitié du côté étudié. `masque` : même moitié, l'autre est noircie (la taille ne change pas)."""
    image = image.convert("RGB")
    if preparation == "aucune":
        return image
    l, h = image.size
    milieu = l // 2
    moitie = (milieu, 0, l, h) if cote == "droite" else (0, 0, milieu, h)
    if preparation == "rognage":
        return image.crop(moitie)
    sortie = Image.new("RGB", (l, h), (0, 0, 0))
    sortie.paste(image.crop(moitie), moitie[:2])
    return sortie


def _nom_fichier(i: ImageBrute, copie: int) -> str:
    stem = nom_sur(Path(i.chemin).stem)
    h = hashlib.sha1(i.chemin.encode()).hexdigest()[:8]
    return f"{nom_sur(i.groupe)}__{stem}-{h}" + (f"__dup{copie}" if copie else "") + ".jpg"


def lignes_de_controle(plan: Plan) -> list[Ligne]:
    return [
        Ligne(l.jeu, l.etiquetee.classe, l.groupe or l.etiquetee.image.groupe, l.etiquetee.image.chemin, l.copie > 0, l.etiquetee.image.contenu, l.etiquetee.image.enregistrement)
        for l in plan.lignes
    ]


def construire(
    brut: Path,
    plan: Plan,
    recette: Recette,
    destination: Path,
    progression: Callable[[int, int], None] | None = None,
) -> dict:
    """Écrit la variante dans `destination` (qui ne doit pas exister). Rend `{effectifs, controles}`."""
    brut, destination = Path(brut), Path(destination)
    if destination.exists():
        raise ConstructionRefusee(f"la variante existe déjà : {destination.name}")
    constats = controler(lignes_de_controle(plan))
    if bloquants(constats):
        raise ConstructionRefusee("contrôles bloquants : " + " ; ".join(c["message"] for c in bloquants(constats)))
    if not plan.lignes:
        raise ConstructionRefusee("la recette ne retient aucune image")

    provisoire = destination.with_name(destination.name + ".encours")
    if provisoire.exists():
        shutil.rmtree(provisoire)
    provisoire.mkdir(parents=True)
    try:
        lignes = []
        total = len(plan.lignes)
        for n, l in enumerate(plan.lignes, start=1):
            i = l.etiquetee.image
            relatif = f"{l.jeu}/{nom_sur(l.etiquetee.classe)}/{_nom_fichier(i, l.copie)}"
            cible = provisoire / relatif
            cible.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(brut / i.chemin) as im:
                prete = preparer(im, i.cote, recette.preparation) if i.plate else im.convert("RGB")
                if recette.taille:  # réduction explicite : toute l'image, sans le recadrage central que ferait le modèle
                    prete = prete.resize((recette.taille, recette.taille), Image.LANCZOS)
                prete.save(cible, "JPEG", quality=QUALITE_JPEG)
            lignes.append({"fichier": relatif, "jeu": l.jeu, "classe": l.etiquetee.classe, "groupe": l.groupe or i.groupe, "source": i.chemin})
            if progression and (n % 25 == 0 or n == total):
                progression(n, total)
        with (provisoire / "manifeste.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(COLONNES))
            w.writeheader()
            w.writerows(lignes)
        (provisoire / "recette.json").write_text(json.dumps(recette.model_dump(), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        resultat = {"effectifs": plan.effectifs(), "ecartes": plan.ecartes, "controles": constats}
        (provisoire / "controles.json").write_text(json.dumps(resultat, ensure_ascii=False, indent=2), encoding="utf-8")
        provisoire.rename(destination)
    except BaseException:
        shutil.rmtree(provisoire, ignore_errors=True)
        raise
    return resultat
