"""Constituer un jeu de panoramas à partir de Panoramax (catalogue ouvert d'imagerie de rue, API STAC).

    python -m laboratoire.profondeur.panoramax --racine <labo> --jeu grenoble-24 --bbox 5.70,45.15,5.76,45.21 --n 24

Un jeu est une « variante » comme celles de la classification : `manifeste.csv` (fichier, jeu, classe, groupe, source + licence, producteur, date,
position) et les images sous `val/panorama/`. Le groupe est la séquence de prise de vue : deux panoramas d'une même séquence se ressemblent, on ne
les compte pas comme indépendants. Seules des licences ouvertes sont gardées, et la licence de chaque image reste dans le manifeste.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from laboratoire.projet import Racine, identifiant_sur

API_PAR_DEFAUT = "https://panoramax.ign.fr/api"
LARGEUR_MAX = 4096
RATIO_ERP = (1.9, 2.1)  # un panorama 360° équirectangulaire est deux fois plus large que haut
COLONNES = ["fichier", "jeu", "classe", "groupe", "source", "licence", "producteur", "date", "lon", "lat", "item"]
LICENCES_OUVERTES = re.compile(r"^(etalab|cc|odbl|lov)", re.IGNORECASE)


@dataclass(frozen=True)
class Candidat:
    item: str
    collection: str
    url_image: str
    licence: str
    producteur: str
    date: str
    lon: float
    lat: float


Ouvrir = Callable[[str], bytes]


def ouvrir_http(url: str) -> bytes:
    requete = urllib.request.Request(url, headers={"User-Agent": "laboratoire-profondeur/0.1 (+https://github.com/nic01asFr/atelier-sspcloud)"})
    with urllib.request.urlopen(requete, timeout=120) as r:  # noqa: S310 - adresse d'API publique donnée par la personne
        return r.read()


def rechercher(api: str, bbox: str, limite: int = 200, ouvrir: Ouvrir = ouvrir_http) -> list[Candidat]:
    """Prises de vue d'une zone (STAC `search`), sans les filtrer sur la forme de l'image : on ne la connaît qu'une fois téléchargée."""
    q = urllib.parse.urlencode({"bbox": bbox, "limit": limite})
    reponse = json.loads(ouvrir(f"{api.rstrip('/')}/search?{q}"))
    sortie = []
    for f in reponse.get("features", []):
        p, actifs = f.get("properties", {}), f.get("assets", {})
        href = (actifs.get("hd") or actifs.get("sd") or {}).get("href")
        coords = (f.get("geometry") or {}).get("coordinates") or [0.0, 0.0]
        licence = p.get("license") or f.get("license") or ""
        if not href or not f.get("id"):
            continue
        sortie.append(Candidat(
            item=str(f["id"]), collection=str(f.get("collection", "")), url_image=href, licence=str(licence),
            producteur=str(p.get("geovisio:producer") or ((p.get("providers") or [{}])[0].get("name") if p.get("providers") else "") or ""),
            date=str(p.get("datetime", "")), lon=float(coords[0]), lat=float(coords[1]),
        ))
    return sortie


def une_par_sequence(candidats: list[Candidat]) -> list[Candidat]:
    """Un candidat par séquence, dans l'ordre de la réponse : la diversité avant la quantité."""
    vus, sortie = set(), []
    for c in candidats:
        if c.collection not in vus:
            vus.add(c.collection)
            sortie.append(c)
    return sortie


def _est_equirectangulaire(im: Image.Image) -> bool:
    return RATIO_ERP[0] <= im.width / im.height <= RATIO_ERP[1]


def construire_jeu(
    racine: Racine, ident: str, candidats: list[Candidat], n: int, ouvrir: Ouvrir = ouvrir_http, journal: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Télécharge jusqu'à `n` panoramas 360° de licence ouverte, écrit le jeu. Rend un résumé (gardés, écartés et pourquoi)."""
    dossier = racine.dossier_variante(identifiant_sur(ident))
    if (dossier / "manifeste.csv").exists():
        raise FileExistsError(f"le jeu {ident!r} existe déjà : un jeu ne se réécrit pas (son identifiant porte son contenu)")
    (dossier / "val" / "panorama").mkdir(parents=True, exist_ok=True)
    gardes, ecartes = [], {"licence": 0, "pas_360": 0, "illisible": 0}
    lignes = []
    for c in une_par_sequence(candidats):
        if len(gardes) >= n:
            break
        if not LICENCES_OUVERTES.match(c.licence or ""):
            ecartes["licence"] += 1
            continue
        try:
            im = Image.open(io.BytesIO(ouvrir(c.url_image)))
            im.load()
        except Exception as exc:  # noqa: BLE001 - une image qui ne vient pas n'arrête pas la constitution du jeu
            journal(f"illisible : {c.item} ({exc})")
            ecartes["illisible"] += 1
            continue
        if not _est_equirectangulaire(im):
            ecartes["pas_360"] += 1
            continue
        im = im.convert("RGB")
        if im.width > LARGEUR_MAX:
            im = im.resize((LARGEUR_MAX, round(im.height * LARGEUR_MAX / im.width)), Image.LANCZOS)
        nom = f"val/panorama/{identifiant_sur(c.item)}.jpg"
        im.save(dossier / nom, "JPEG", quality=92)
        lignes.append({
            "fichier": nom, "jeu": "val", "classe": "panorama", "groupe": identifiant_sur(c.collection or c.item), "source": c.url_image,
            "licence": c.licence, "producteur": c.producteur, "date": c.date, "lon": c.lon, "lat": c.lat, "item": c.item,
        })
        gardes.append(c.item)
        journal(f"gardé {len(gardes)}/{n} : {c.item} ({c.licence}, {c.producteur})")
    with (dossier / "manifeste.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLONNES)
        w.writeheader()
        w.writerows(lignes)
    return {"jeu": ident, "gardes": len(gardes), "ecartes": ecartes}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="laboratoire.profondeur.panoramax", description=__doc__)
    p.add_argument("--racine", required=True)
    p.add_argument("--jeu", required=True, help="identifiant du jeu (ex. grenoble-24)")
    p.add_argument("--bbox", required=True, help="ouest,sud,est,nord")
    p.add_argument("--n", type=int, default=24)
    p.add_argument("--api", default=API_PAR_DEFAUT)
    args = p.parse_args(argv)
    racine = Racine(Path(args.racine))
    racine.preparer()
    resume = construire_jeu(racine, args.jeu, rechercher(args.api, args.bbox), args.n)
    print(json.dumps(resume, ensure_ascii=False))
    return 0 if resume["gardes"] else 1


if __name__ == "__main__":
    sys.exit(main())
