"""Un jeu synthétique de profondeur, mais pris avec une caméra penchée : de quoi mesurer combien chaque modèle supporte une inclinaison.

    PYTHONPATH=<labo>/src python3 incliner_jeu.py --source <jeu> --sortie <nouveau jeu> [--tangage-max 6] [--roulis-max 4] [--graine 0]

Pour chaque panorama du jeu `source` (images + `val/verite/<id>.npz`), on tire un tangage et un roulis, on incline l'image **et** sa profondeur de
référence de la même façon (la distance le long d'un rayon ne change pas quand on tourne le repère : seules les cartes se déplacent), et on écrit
les angles dans le manifeste (`tangage`, `roulis`), comme le ferait un jeu de vraies prises dont la caméra a enregistré son inclinaison.
Avec le réglage `redresser`, le laboratoire remet alors chaque panorama d'aplomb avant de le donner au modèle.
"""

from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

from laboratoire.profondeur import redresser


def incliner_verite(chemin_entree: Path, chemin_sortie: Path, tangage: float, roulis: float) -> None:
    with np.load(chemin_entree) as f:
        champs = {k: f[k] for k in f.files}
    sortie = {k: redresser.incliner(v, tangage, roulis, plus_proche=True) for k, v in champs.items()}
    chemin_sortie.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(chemin_sortie, **sortie)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--sortie", required=True, type=Path)
    ap.add_argument("--tangage-max", type=float, default=6.0, help="le tangage est tiré dans [−max, +max], en degrés")
    ap.add_argument("--roulis-max", type=float, default=4.0)
    ap.add_argument("--graine", type=int, default=0)
    args = ap.parse_args()
    if args.sortie.exists():
        raise SystemExit(f"{args.sortie} existe déjà")
    rng = np.random.default_rng(args.graine)
    with (args.source / "manifeste.csv").open(encoding="utf-8", newline="") as f:
        lecteur = csv.DictReader(f)
        colonnes, lignes = list(lecteur.fieldnames or []), list(lecteur)
    for c in ("tangage", "roulis"):
        if c not in colonnes:
            colonnes.append(c)
    for n, ligne in enumerate(lignes, start=1):
        tangage, roulis = (round(float(x), 2) for x in (rng.uniform(-args.tangage_max, args.tangage_max), rng.uniform(-args.roulis_max, args.roulis_max)))
        entree = args.source / ligne["fichier"]
        sortie = args.sortie / ligne["fichier"]
        sortie.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(entree) as im:
            Image.fromarray(redresser.incliner(np.asarray(im.convert("RGB")), tangage, roulis)).save(sortie)
        verite_in = entree.parent.parent / "verite" / f"{entree.stem}.npz"
        if verite_in.is_file():
            incliner_verite(verite_in, sortie.parent.parent / "verite" / f"{entree.stem}.npz", tangage, roulis)
        ligne["tangage"], ligne["roulis"] = tangage, roulis
        if n % 10 == 0:
            print(f"{n}/{len(lignes)}", flush=True)
    with (args.sortie / "manifeste.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, colonnes)
        w.writeheader()
        w.writerows(lignes)
    if (args.source / "meta.jsonl").is_file():
        shutil.copy(args.source / "meta.jsonl", args.sortie / "meta.jsonl")
    print(f"{len(lignes)} panoramas inclinés dans {args.sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
