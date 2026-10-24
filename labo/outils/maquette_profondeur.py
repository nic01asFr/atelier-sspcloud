"""Jeu synthétique de profondeur : panoramas 360° de la maquette v9.3 et leur profondeur exacte.

Ce script tourne sur le pod de la fabrique world2pix (il importe son moteur de lancer de rayons, sans le modifier) :

    cd ~/work/projects/world2pix
    PIX2HDR_SITE_DIR=data/FXX_L93_200_E0894400_N6248000_1x1 PYTHONPATH=. ~/work/venv-pix2hdr/bin/python \\
        maquette_profondeur.py --sortie ~/work/profondeur-synthetique/essai1 --n 15

Un processus = une dalle (le site est fixé par la variable d'environnement) ; les sorties s'ajoutent à `--sortie`.

Pour chaque position tirée dans la voirie, à hauteur d'œil, il écrit :

    val/panorama/<id>.png       le rendu analytique de la maquette (2048 × 1024, équirectangulaire)
    val/verite/<id>.npz         profondeur (distance le long du rayon, en mètres, 0 = pas d'impact), ciel,
                                hors_emprise (à exclure de la vérité), couche
    manifeste.csv               même colonnes que les jeux Panoramax du laboratoire
    meta.jsonl                  une ligne par panorama : pose, dalle, soleil, empreinte de la maquette, commit

Conventions de la fabrique reprises telles quelles (réponse du 24/10, `world2pix-meta`, docs/reflexions) :
cap compté depuis le nord de grille, panorama équirectangulaire de `camera.directions_equirect`, profondeur =
distance euclidienne le long du rayon. La maquette garde le nom « v9.3 » quand son contenu change : le jeu est
épinglé sur l'empreinte de ses fichiers OBJ (`obj_sha1`) et sur le commit du dépôt.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, ".")
from experiments.bench.common import ZONES  # noqa: E402
from experiments.integration.assemble import GROUPES  # noqa: E402
from experiments.panoramax_toutes import maquette as mq  # noqa: E402
from experiments.paires import canaux as C  # noqa: E402

ZONE = "T1"
HAUTEUR_OEIL_M = 1.6
MARGE_BORD_M = 40.0  # la maquette couvre le carré de la dalle : on reste loin des bords (réponse de la fabrique)
ECART_MIN_M = 15.0
# Soleil fixe, noté dans les métadonnées : azimut de grille et élévation (été, milieu de journée).
SOLEIL_AZIMUT_DEG, SOLEIL_ELEVATION_DEG = 150.0, 55.0
COLONNES = ["fichier", "jeu", "classe", "groupe", "source", "licence", "producteur", "date", "lon", "lat", "item", "camera", "tangage", "roulis"]


def soleil() -> np.ndarray:
    az, el = math.radians(SOLEIL_AZIMUT_DEG), math.radians(SOLEIL_ELEVATION_DEG)
    return np.array([math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)])


def empreinte_obj(maq) -> str:
    h = hashlib.sha1()
    for f in sorted(Path(maq.dossier).glob("*.obj")):
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def commit_depot() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def sol_sous(maq, e: float, n: float) -> tuple[float, str] | None:
    """Altitude (repère local) et couche de la surface sous (e, n), par un lancer vers le bas."""
    haut = 800.0
    buf = C.lancer(maq, np.array([e, n, haut]), np.array([[[0.0, 0.0, -1.0]]]))
    if not buf["touche"][0, 0]:
        return None
    couche = int(maq.couche_de(buf["element"])[0, 0])
    return haut - float(buf["profondeur"][0, 0]), GROUPES[couche] if couche >= 0 else ""


def tirer_positions(maq, n: int, graine: int, marge: float = MARGE_BORD_M, ecart: float = ECART_MIN_M) -> list[tuple[float, float, float]]:
    demi = ZONES[ZONE].half - marge
    rng = np.random.default_rng(graine)
    prises: list[tuple[float, float, float]] = []
    for _ in range(20000):
        if len(prises) >= n:
            break
        e, nn = (float(x) for x in rng.uniform(-demi, demi, 2))
        if any(math.hypot(e - p[0], nn - p[1]) < ecart for p in prises):
            continue
        s = sol_sous(maq, e, nn)
        if s is not None and s[1] == "voirie":
            prises.append((e, nn, s[0]))
    return prises


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sortie", required=True, type=Path)
    ap.add_argument("--n", type=int, default=15, help="panoramas pour cette dalle")
    ap.add_argument("--graine", type=int, default=0)
    ap.add_argument("--largeur", type=int, default=2048)
    ap.add_argument("--marge", type=float, default=MARGE_BORD_M, help="distance minimale aux bords de la dalle, en mètres (la maquette s'arrête au bord)")
    ap.add_argument("--ecart", type=float, default=ECART_MIN_M, help="distance minimale entre deux positions, en mètres")
    args = ap.parse_args()
    largeur, hauteur = args.largeur, args.largeur // 2

    t0 = time.time()
    maq = mq.charger(ZONE)
    site = Path(maq.dossier).parent.name.removeprefix("out_")
    sha, commit = empreinte_obj(maq), commit_depot()
    print(f"maquette chargée en {time.time() - t0:.0f} s : {len(maq.elements)} éléments, obj_sha1 {sha[:12]}", flush=True)

    (args.sortie / "val/panorama").mkdir(parents=True, exist_ok=True)
    (args.sortie / "val/verite").mkdir(parents=True, exist_ok=True)
    manifeste = args.sortie / "manifeste.csv"
    neuf = not manifeste.exists()
    alb, sun = C.albedo(maq), soleil()
    positions = tirer_positions(maq, args.n, args.graine, args.marge, args.ecart)
    print(f"{len(positions)} positions dans la voirie", flush=True)

    with manifeste.open("a", newline="", encoding="utf-8") as f, (args.sortie / "meta.jsonl").open("a", encoding="utf-8") as meta:
        w = csv.DictWriter(f, COLONNES)
        if neuf:
            w.writeheader()
        for k, (e, n, sol) in enumerate(positions):
            ident = f"{site}-{args.graine:03d}-{k:03d}"
            pose = {"e": e, "n": n, "u_oeil": sol + HAUTEUR_OEIL_M, "type": "360", "champ_deg": 360,
                    "cap_grille_deg": 0.0, "inclinaison_deg": 0.0, "roulis_deg": 0.0}
            t1 = time.time()
            dirs = mq.rayons(pose, largeur, hauteur)[..., 3:]
            oeil = np.array([pose["e"], pose["n"], pose["u_oeil"]])
            buf = C.lancer(maq, oeil, dirs)
            hors = C.hors_emprise(maq, oeil, dirs, buf)
            image = C.rendu(buf, alb, C.eclairement(maq, buf, sun), sun)
            Image.fromarray(image).save(args.sortie / f"val/panorama/{ident}.png")
            couche = maq.couche_de(buf["element"]).astype(np.int8)
            ciel = ~buf["touche"] & ~hors
            np.savez_compressed(args.sortie / f"val/verite/{ident}.npz", profondeur=buf["profondeur"].astype(np.float32),
                                ciel=ciel, hors_emprise=hors, couche=couche)
            w.writerow({"fichier": f"val/panorama/{ident}.png", "jeu": "val", "classe": "panorama", "groupe": site,
                        "source": f"maquette v9.3 {sha[:12]}", "licence": "voir meta.jsonl", "producteur": "world2pix",
                        "date": "", "lon": "", "lat": "", "item": ident, "camera": "maquette", "tangage": 0.0, "roulis": 0.0})
            meta.write(json.dumps({"item": ident, "dalle": site, "pose": pose, "largeur": largeur, "hauteur": hauteur,
                                   "soleil": {"azimut_grille_deg": SOLEIL_AZIMUT_DEG, "elevation_deg": SOLEIL_ELEVATION_DEG},
                                   "obj_sha1": sha, "commit_depot": commit, "d_max_m": float(C.D_MAX),
                                   "part_hors_emprise": round(float(hors.mean()), 4), "part_ciel": round(float(ciel.mean()), 4),
                                   "part_touche": round(float(buf["touche"].mean()), 4)}) + "\n")
            meta.flush()
            print(f"{ident}  {time.time() - t1:.1f} s  touche {buf['touche'].mean():.2f}  hors_emprise {hors.mean():.2f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
