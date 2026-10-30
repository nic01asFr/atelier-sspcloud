"""Constitue le dossier `livrable/` d'un projet de classification : pour chaque groupe, le modèle retenu, la liste de ses images, ses mesures.

    PYTHONPATH=<labo>/src python3 constituer_livrable.py --racine <dossier du laboratoire> --depuis E0030 --motif "réduction"

Le dossier est lu par l'onglet « Livrable » du laboratoire (`/api/livrable`) : fichiers à plat, un jeu par groupe :

    <groupe>.pt                          le modèle (celui de la graine 0)
    <groupe>_lots.csv                    une ligne par image : fichier, lot (train/val/test), classe, collection, chemin d'origine
    <groupe>_mesures.json                essai, jeu de données, empreinte du modèle, rappel/précision par classe, confusion, 3 graines, règle de choix
    <groupe>_confusion_validation.csv    la matrice de confusion
    synthese.csv                         une ligne par groupe
    lire_le_livrable.ipynb               le carnet qui explique et rejoue les mesures (outils/lire_le_livrable.ipynb)

Ne lit que les mesures de **validation** (`resultats.json`) : jamais `test_scelle.json`. Un essai dont le résultat porte sur un autre lot est refusé.

Les essais sont reconnus à leur note, au format posé par le lot de relance du 28/10 :
    « v2 28/10 : <type> <côté> <tâche> · <description> · <modèle> · graine <n> »
où <type> est `recadrage` (panoramique) ou `plate` (non panoramique). Seuls les essais dont la description commence par `--motif` sont retenus.
Règle de choix du modèle de chaque groupe : meilleur rappel moyen en validation (moyenne des graines) ; `yolo26n` si l'écart est inférieur à 0,02.
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import re
import shutil
import sqlite3
import statistics as st
from pathlib import Path

NOTE = re.compile(r"v2 \d+/\d+ : (\w+) (\w+) (\w+) · (.+?) · (yolo26[ns]-cls) · graine (\d)")
NOM_DU_TYPE = {"recadrage": "panoramique", "plate": "non_panoramique"}
ECART_MINIMAL = 0.02
COLONNES = ["groupe", "modele", "essai_livre", "jeu_de_donnees", "train", "val", "test", "images_validation", "exactitude", "reponse_triviale",
            "rappel_moyen", "hasard", "rappel_moyen_3_graines", "ecart_3_graines", "poids_sha256_12"]


def constituer(racine: Path, depuis: str, motif: str) -> list[list]:
    sortie = racine / "livrable"
    if sortie.exists():
        shutil.rmtree(sortie)
    sortie.mkdir()
    base = sqlite3.connect(f"file:{racine / 'labo.db'}?mode=ro", uri=True)
    base.row_factory = sqlite3.Row
    essais: dict[tuple[str, str, str, str], list[tuple[int, str, str, dict]]] = collections.defaultdict(list)
    for r in base.execute("SELECT id, jeu, note FROM essais WHERE id >= ? AND etat = 'termine' ORDER BY id", (depuis,)):
        m = NOTE.match(r["note"] or "")
        if not m or not m.group(4).startswith(motif):
            continue
        type_image, cote, tache, _, modele, graine = m.groups()
        resultats = json.loads((racine / "essais" / r["id"] / "resultats.json").read_text(encoding="utf-8"))
        if resultats.get("jeu") != "val":
            raise SystemExit(f"{r['id']} : le résultat ne porte pas sur la validation ({resultats.get('jeu')!r}) : refusé")
        essais[(type_image, cote, tache, modele)].append((int(graine), r["id"], r["jeu"], resultats))
    if not essais:
        raise SystemExit("aucun essai ne correspond (vérifier --depuis et --motif)")
    synthese: list[list] = []
    for tache in ("nombre", "forme"):
        for type_image in ("recadrage", "plate"):
            for cote in ("droite", "gauche"):
                par_modele = {m: sorted(essais[(type_image, cote, tache, m)]) for m in ("yolo26n-cls", "yolo26s-cls")}
                if not all(par_modele.values()):
                    continue
                moyennes = {m: st.mean(x[3]["rapport"]["rappel_moyen"] for x in v) for m, v in par_modele.items()}
                retenu = "yolo26s-cls" if moyennes["yolo26s-cls"] - moyennes["yolo26n-cls"] >= ECART_MINIMAL else "yolo26n-cls"
                graines = par_modele[retenu]
                _, ident, jeu, resultat = next(x for x in graines if x[0] == 0)
                rapport = resultat["rapport"]
                groupe = f"{NOM_DU_TYPE[type_image]}_{cote}_{tache}"
                shutil.copy2(racine / "essais" / ident / "poids" / "last.pt", sortie / f"{groupe}.pt")
                shutil.copy2(racine / "donnees" / "variantes" / jeu / "manifeste.csv", sortie / f"{groupe}_lots.csv")
                empreinte = hashlib.sha256((sortie / f"{groupe}.pt").read_bytes()).hexdigest()
                with (sortie / f"{groupe}_lots.csv").open(encoding="utf-8", newline="") as f:
                    lots = collections.Counter(ligne["jeu"] for ligne in csv.DictReader(f))
                classes = rapport["classes"]
                with (sortie / f"{groupe}_confusion_validation.csv").open("w", encoding="utf-8", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["vrai \\ prédit", *classes])
                    for i, c in enumerate(classes):
                        w.writerow([c, *rapport["confusion"][i]])
                rappels = [x[3]["rapport"]["rappel_moyen"] for x in graines]
                mesures = {
                    "groupe": groupe, "modele": retenu, "essai_livre": ident, "graine": 0, "jeu_de_donnees": jeu, "poids_sha256": empreinte, "lots": dict(lots),
                    "validation": {
                        "images": rapport["total"], "exactitude": rapport["exactitude"], "rappel_moyen": rapport["rappel_moyen"], "classes": classes,
                        "par_classe": rapport["par_classe"], "confusion": rapport["confusion"],
                        "reponse_triviale_exactitude": resultat["triviales"]["majoritaire"]["exactitude"], "hasard_rappel_moyen": 1 / len(classes),
                    },
                    "trois_graines": {
                        "essais": [x[1] for x in graines], "rappel_moyen_moyenne": st.mean(rappels), "rappel_moyen_ecart": st.pstdev(rappels),
                        "exactitude_moyenne": st.mean(x[3]["rapport"]["exactitude"] for x in graines),
                    },
                    "regle_de_choix": "meilleur rappel moyen en validation (moyenne des graines) ; yolo26n si écart < 0,02", "test": "scellé, non ouvert",
                }
                (sortie / f"{groupe}_mesures.json").write_text(json.dumps(mesures, ensure_ascii=False, indent=2), encoding="utf-8")
                synthese.append([
                    groupe, retenu, ident, jeu, lots["train"], lots["val"], lots["test"], rapport["total"], round(rapport["exactitude"], 3),
                    round(resultat["triviales"]["majoritaire"]["exactitude"], 3), round(rapport["rappel_moyen"], 3), round(1 / len(classes), 2),
                    round(st.mean(rappels), 3), round(st.pstdev(rappels), 3), empreinte[:12],
                ])
    with (sortie / "synthese.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLONNES)
        w.writerows(synthese)
    shutil.copy2(Path(__file__).with_name("lire_le_livrable.ipynb"), sortie / "lire_le_livrable.ipynb")
    return synthese


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--racine", required=True, type=Path, help="dossier de données du laboratoire (…/labo)")
    ap.add_argument("--depuis", default="E0030", help="premier essai à considérer")
    ap.add_argument("--motif", default="réduction", help="début de la description des essais retenus")
    args = ap.parse_args()
    for ligne in constituer(args.racine, args.depuis, args.motif):
        print(" | ".join(map(str, ligne)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
