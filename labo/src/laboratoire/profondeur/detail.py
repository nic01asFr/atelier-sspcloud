"""Où un modèle se trompe : l'erreur de profondeur par tranche de distance et par couche de la maquette.

Les chiffres d'un essai (`resultats.json`) sont des médianes sur toutes les vues. Ici on reprend les cartes que l'essai a gardées (`profondeur/<panorama>.npz`)
et la référence du jeu, et on regroupe les **pixels** : un modèle qui voit bien le sol proche et se trompe sur les façades lointaines apparaît.

Même mesure que l'essai : une droite ajustée par vue entre le `q` du modèle et celui de la référence (les modèles relatifs n'ont pas d'échelle), puis
l'écart relatif sur la distance. On ajoute le **biais** (signé : < 0, le modèle voit trop près ; > 0, trop loin) et la part des pixels à 25 % près.
Les pixels sont ceux que la mesure d'un essai garde : ni ciel, ni hors emprise, ni au-delà de 100 m, ni au bord d'une carte.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from laboratoire.profondeur import geometrie as g
from laboratoire.profondeur import redresser, verite
from laboratoire.profondeur.mesures import MIN_POINTS, ajustement_affine

BORNES_M = (0.0, 5.0, 10.0, 20.0, 40.0, verite.PORTEE_MAX_M + 1e-6)


def _nom_tranche(i: int) -> str:
    return f"{BORNES_M[i]:g}–{min(BORNES_M[i + 1], verite.PORTEE_MAX_M):g} m"


def noms_des_couches(dossier_variante: Path, n: int = 64) -> list[str]:
    """Les noms des couches de la maquette (`couches.json` du jeu) ; à défaut, `c0`, `c1`…"""
    f = Path(dossier_variante) / "couches.json"
    if f.is_file():
        return list(json.loads(f.read_text(encoding="utf-8")))
    return [f"c{i}" for i in range(n)]


class _Cumul:
    def __init__(self, n: int) -> None:
        self.n = np.zeros(n)
        self.abs = np.zeros(n)
        self.signe = np.zeros(n)
        self.juste = np.zeros(n)

    def ajouter(self, cases: np.ndarray, erreur: np.ndarray, juste: np.ndarray) -> None:
        k = len(self.n)
        self.n += np.bincount(cases, minlength=k)[:k]
        self.abs += np.bincount(cases, weights=np.abs(erreur), minlength=k)[:k]
        self.signe += np.bincount(cases, weights=erreur, minlength=k)[:k]
        self.juste += np.bincount(cases, weights=juste.astype(float), minlength=k)[:k]

    def resume(self, i: int) -> dict[str, float] | None:
        if self.n[i] < MIN_POINTS:
            return None
        return {"pixels": int(self.n[i]), "absrel": round(float(self.abs[i] / self.n[i]), 4), "biais": round(float(self.signe[i] / self.n[i]), 4),
                "delta1": round(float(self.juste[i] / self.n[i]), 4)}


def detail(dossier_essai: Path, dossier_variante: Path, reglages: dict[str, Any]) -> dict[str, Any]:
    """Erreurs par tranche de distance et par couche pour un essai terminé dont le jeu porte une référence."""
    vues = g.grille_de_vues(float(reglages.get("fov", 90.0)), float(reglages.get("pas_cap", 45.0)), float(reglages.get("tangage_haut", 15.0)))
    inclinaison = redresser.inclinaisons(dossier_variante) if reglages.get("redresser") else {}
    couches = noms_des_couches(dossier_variante)
    par_tranche, par_couche = _Cumul(len(BORNES_M) - 1), _Cumul(len(couches))
    total, panoramas = _Cumul(1), 0
    for fichier in sorted((Path(dossier_essai) / "profondeur").glob("*.npz")):
        ref = Path(dossier_variante) / "val" / "verite" / fichier.name
        if not ref.is_file():
            continue
        with np.load(fichier) as f:
            qs, ms = f["q"].astype(np.float32), f["masque"]
        q_erp, valide_erp = verite.charger(ref)
        with np.load(ref) as f:
            couche_erp = f["couche"]
        tilt = inclinaison.get(fichier.stem, (0.0, 0.0))
        if tilt != (0.0, 0.0):
            q_erp, valide_erp, couche_erp = (redresser.redresser(c, *tilt, plus_proche=True) for c in (q_erp, valide_erp, couche_erp))
        hq, lq = qs.shape[1:]
        panoramas += 1
        for i, vue in enumerate(vues):
            rayons = g.rayons_monde(vue, lq, hq)
            q_ref = verite.echantillonner_plus_proche(q_erp, rayons)
            ok = verite.eroder(ms[i]) & verite.eroder(verite.echantillonner_plus_proche(valide_erp, rayons)) & (q_ref > 0) & np.isfinite(qs[i])
            if int(ok.sum()) < MIN_POINTS:
                continue
            x, y = qs[i][ok].astype(np.float64), q_ref[ok].astype(np.float64)
            r, a, b = ajustement_affine(x, y)
            if not math.isfinite(r):
                continue
            d_ref = 1.0 / y
            d_aj = 1.0 / np.maximum(a * x + b, verite.Q_PLANCHER)
            erreur = (d_aj - d_ref) / d_ref
            juste = np.maximum(d_aj / d_ref, d_ref / d_aj) < verite.SEUIL_DELTA
            tranche = np.clip(np.digitize(d_ref, BORNES_M) - 1, 0, len(BORNES_M) - 2)
            couche = np.clip(verite.echantillonner_plus_proche(couche_erp, rayons)[ok].astype(int), 0, len(couches) - 1)
            par_tranche.ajouter(tranche, erreur, juste)
            par_couche.ajouter(couche, erreur, juste)
            total.ajouter(np.zeros(len(erreur), int), erreur, juste)
    return {
        "panoramas": panoramas, "ensemble": total.resume(0),
        "tranches": {_nom_tranche(i): par_tranche.resume(i) for i in range(len(BORNES_M) - 1)},
        "couches": {couches[i]: par_couche.resume(i) for i in range(len(couches)) if par_couche.resume(i)},
    }


def _tableau(titre: str, par_essai: dict[str, dict[str, dict[str, float] | None]], cle: str = "absrel") -> list[str]:
    noms = sorted({n for d in par_essai.values() for n in d})
    lignes = [f"\n{titre}", "  " + " " * 14 + "".join(f"{e:>10}" for e in par_essai)]
    for n in noms:
        lignes.append(f"  {n:<14}" + "".join(f"{(d.get(n) or {}).get(cle, float('nan')):>10.3f}" for d in par_essai.values()))
    return lignes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--racine", required=True, type=Path, help="dossier de données du laboratoire (…/labo)")
    ap.add_argument("--jeu", required=True)
    ap.add_argument("--essais", nargs="+", required=True, metavar="ID=NOM", help="par exemple E0004=moge2 E0007=dap")
    ap.add_argument("--json", type=Path, help="écrire aussi le détail complet")
    args = ap.parse_args()
    from laboratoire.projet import Racine

    racine = Racine(args.racine)
    sorties: dict[str, dict[str, Any]] = {}
    for item in args.essais:
        ident, _, nom = item.partition("=")
        resultats = json.loads((racine.dossier_essai(ident) / "resultats.json").read_text(encoding="utf-8"))
        sorties[nom or ident] = detail(racine.dossier_essai(ident), racine.dossier_variante(args.jeu), resultats.get("reglages", {}))
    for cle, titre in (("absrel", "Erreur relative (plus bas = mieux)"), ("biais", "Biais (< 0 : trop près ; > 0 : trop loin)"), ("delta1", "Pixels à 25 % près")):
        print("\n".join(_tableau(f"{titre} — par tranche de distance", {k: v["tranches"] for k, v in sorties.items()}, cle)))
        print("\n".join(_tableau(f"{titre} — par couche", {k: v["couches"] for k, v in sorties.items()}, cle)))
    if args.json:
        args.json.write_text(json.dumps(sorties, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
