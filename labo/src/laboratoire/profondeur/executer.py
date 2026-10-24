"""Un essai « profondeur » : un modèle, un jeu de panoramas. Pour chaque panorama, des vues en perspective ; pour chaque vue, la carte du modèle.

Fichiers écrits dans le dossier de l'essai :
- `profondeur/<panorama>.npz` : `q` (vues, h, w) float16 et `masque` (vues, h, w) bool, à basse résolution (assez pour mesurer) ;
- `apercus/<panorama>/<vue>.jpg` : la carte en couleurs, pour les yeux ;
- `resultats.json` : mesures de cohérence, temps, mémoire, licences ;
- `metriques.csv` : une ligne par panorama (la progression, visible en direct).
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from laboratoire.adaptateurs.base import ContexteEssai
from laboratoire.profondeur import geometrie as g
from laboratoire.profondeur import mesures, redresser, verite
from laboratoire.profondeur.carte import colorier, vers_jpeg
from laboratoire.profondeur.modeles_profondeur import modele as obtenir_modele

LARGEUR_STOCKEE = 256  # résolution des cartes gardées pour les mesures
LARGEUR_APERCU = 512
LARGEUR_MAX_ERP = 4096
REGLAGES = {"fov": 90.0, "pas_cap": 45.0, "tangage_haut": 15.0, "largeur": 1024, "panoramas_max": 0}


def reglages_complets(reglages: dict[str, Any]) -> dict[str, Any]:
    inconnus = set(reglages) - set(REGLAGES) - {"moge_id", "fov_connu", "redresser"}
    if inconnus:
        raise ValueError(f"réglages inconnus pour la profondeur : {sorted(inconnus)} (connus : {sorted(REGLAGES)})")
    r = {**REGLAGES, **reglages}
    g.grille_de_vues(float(r["fov"]), float(r["pas_cap"]), float(r["tangage_haut"]))  # lève ValueError si hors bornes
    if float(r["pas_cap"]) > 0.75 * float(r["fov"]):
        raise ValueError("pas_cap trop grand pour fov : sans recouvrement entre vues voisines, la cohérence ne se mesure pas (pas_cap ≤ 0,75 × fov)")
    if not 128 <= int(r["largeur"]) <= 2048:
        raise ValueError("largeur : entre 128 et 2048 pixels")
    return r


def _reduire(a: np.ndarray, largeur: int) -> np.ndarray:
    im = Image.fromarray(a.astype(np.float32), mode="F")
    return np.asarray(im.resize((largeur, round(a.shape[0] * largeur / a.shape[1])), Image.BILINEAR), np.float32)


def _reduire_masque(m: np.ndarray, largeur: int) -> np.ndarray:
    im = Image.fromarray(m.astype(np.uint8) * 255)
    return np.asarray(im.resize((largeur, round(m.shape[0] * largeur / m.shape[1])), Image.BILINEAR)) > 127


def _charger_erp(chemin: Path) -> np.ndarray:
    with Image.open(chemin) as im:
        im = im.convert("RGB")
        if im.width > LARGEUR_MAX_ERP:
            im = im.resize((LARGEUR_MAX_ERP, round(im.height * LARGEUR_MAX_ERP / im.width)), Image.BILINEAR)
        return np.asarray(im)


def _vram_crete_mo() -> float | None:
    try:
        import torch

        return round(torch.cuda.max_memory_allocated() / 2**20) if torch.cuda.is_available() else None
    except ImportError:
        return None


def _appareil() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def executer(ctx: ContexteEssai) -> None:
    cfg = ctx.config
    r = reglages_complets(dict(cfg.methode.reglages))
    mod = obtenir_modele(cfg.methode.modele, r)
    vues = g.grille_de_vues(float(r["fov"]), float(r["pas_cap"]), float(r["tangage_haut"]))
    largeur = int(r["largeur"])
    hauteur = round(largeur * 3 / 4)
    panos = sorted(ctx.variante.echantillons("val"), key=lambda e: e.fichier.name)
    if int(r["panoramas_max"]):
        panos = panos[: int(r["panoramas_max"])]
    if not panos:
        raise RuntimeError("le jeu ne contient aucun panorama")
    print(f"[essai] profondeur/{cfg.methode.modele} : {len(panos)} panoramas × {len(vues)} vues ({largeur}×{hauteur})", flush=True)
    appareil = _appareil()
    t0 = time.time()
    mod.charger(appareil)
    print(f"[essai] modèle chargé sur {appareil} en {time.time() - t0:.1f} s", flush=True)
    dossier = ctx.dossier
    (dossier / "profondeur").mkdir(exist_ok=True)
    par_pano, temps_vues = [], []
    hq = round(LARGEUR_STOCKEE * 3 / 4)
    inclinaison = redresser.inclinaisons(ctx.variante.dossier) if r.get("redresser") else {}
    for k, echantillon in enumerate(panos, start=1):
        pano = echantillon.fichier.stem
        erp = _charger_erp(echantillon.fichier)
        tilt = inclinaison.get(pano, (0.0, 0.0))
        if tilt != (0.0, 0.0):  # la caméra était inclinée : on remet le panorama (et, plus bas, sa référence) d'aplomb
            erp = redresser.redresser(erp, *tilt)
        qs = np.zeros((len(vues), hq, LARGEUR_STOCKEE), np.float16)
        ms = np.zeros((len(vues), hq, LARGEUR_STOCKEE), bool)
        (dossier / "apercus" / pano).mkdir(parents=True, exist_ok=True)
        t_pano = time.time()
        q_erp = masque_erp = None
        if getattr(mod, "panorama", False):  # un modèle de panorama : une passe pour tout le panorama, les vues en sont tirées
            t1 = time.time()
            q_erp, masque_erp = mod.predire_panorama(erp)
            temps_pano = time.time() - t1
        for i, vue in enumerate(vues):
            if q_erp is not None:
                rayons = g.rayons_monde(vue, largeur, hauteur)
                q = g.echantillonner_erp(q_erp, rayons).astype(np.float32)
                masque = g.echantillonner_erp(masque_erp.astype(np.float32), rayons) > 0.5
                temps_vues.append(temps_pano / len(vues))  # le coût d'une passe se partage entre les vues qu'elle sert
            else:
                rgb = np.clip(g.extraire_vue(erp, vue, largeur, hauteur), 0, 255).astype(np.uint8)
                t1 = time.time()
                q, masque = mod.predire(rgb, vue.fov)
                temps_vues.append(time.time() - t1)
            qs[i] = _reduire(np.where(masque, q, 0.0), LARGEUR_STOCKEE)
            ms[i] = _reduire_masque(masque, LARGEUR_STOCKEE)
            (dossier / "apercus" / pano / f"{vue.nom}.jpg").write_bytes(vers_jpeg(colorier(q, masque), LARGEUR_APERCU))
        np.savez_compressed(dossier / "profondeur" / f"{pano}.npz", q=qs, masque=ms, vues=np.array([v.nom for v in vues]))
        c = mesures.coherence_recouvrement(qs.astype(np.float32), ms, vues, metrique=mod.metrique)
        par_pano.append({"panorama": pano, "groupe": echantillon.groupe, **c, **_erreurs_panorama(echantillon.fichier, vues, qs, ms, mod.metrique, tilt)})
        ctx.metrique(panorama=k, nom=pano, vues=len(vues), incoherence=_arrondi(c["incoherence"]), secondes=round(time.time() - t_pano, 1))
        print(f"[essai] {k}/{len(panos)} {pano} : incohérence {_arrondi(c['incoherence'])} ({c['paires']} paires de vues)", flush=True)
    inc = [p["incoherence"] for p in par_pano if math.isfinite(p["incoherence"])]
    der = [p["derive_echelle"] for p in par_pano if p["derive_echelle"] is not None and math.isfinite(p["derive_echelle"])]
    rapport = {
        "incoherence_mediane": _arrondi(float(np.median(inc))) if inc else None,
        "incoherence_moyenne": _arrondi(float(np.mean(inc))) if inc else None,
        "derive_echelle_mediane": _arrondi(float(np.median(der))) if der else None,
        "temps_par_vue_s": _arrondi(float(np.median(temps_vues))),
        "vram_crete_mo": _vram_crete_mo(),
        "panoramas": len(panos),
        "vues_par_panorama": len(vues),
        "metrique": mod.metrique,
        "mode": "panorama" if getattr(mod, "panorama", False) else "vues",  # un modèle de panorama est cohérent d'une vue à l'autre par construction
        **verite.resume_jeu(par_pano),
    }
    resultats = {
        "empreinte": cfg.empreinte(), "tache": "profondeur", "modele": cfg.methode.modele, "licence_modele": getattr(mod, "licence", ""),
        "reglages": r, "appareil": appareil, "rapport": rapport, "par_panorama": par_pano,
    }
    chemin = dossier / "resultats.json"
    chemin.with_name("resultats.json.tmp").write_text(json.dumps(resultats, ensure_ascii=False, indent=2), encoding="utf-8")
    chemin.with_name("resultats.json.tmp").replace(chemin)
    print(f"[essai] incohérence médiane {rapport['incoherence_mediane']} · {rapport['temps_par_vue_s']} s par vue · {rapport['vram_crete_mo']} Mo de mémoire GPU", flush=True)
    print("[essai] terminé", flush=True)


def _erreurs_panorama(fichier: Path, vues: list[g.Vue], qs: np.ndarray, ms: np.ndarray, metrique: bool, redresse: tuple[float, float] = (0.0, 0.0)) -> dict[str, Any]:
    """Les erreurs contre la profondeur de référence du panorama, si le jeu en porte une (jeu synthétique) ; sinon rien.

    La référence est dans le repère du panorama tel qu'il est stocké : si le panorama a été redressé, elle l'est de la même façon."""
    chemin = verite.chemin_verite(fichier)
    if not chemin.is_file():
        return {}
    q_erp, valide_erp = verite.charger(chemin)
    if redresse != (0.0, 0.0):
        q_erp, valide_erp = redresser.redresser(q_erp, *redresse, plus_proche=True), redresser.redresser(valide_erp, *redresse, plus_proche=True)
    hq, lq = qs.shape[1:]
    par_vue = []
    for i, vue in enumerate(vues):
        rayons = g.rayons_monde(vue, lq, hq)
        par_vue.append(verite.erreurs_vue(qs[i].astype(np.float32), verite.eroder(ms[i]), verite.echantillonner_plus_proche(q_erp, rayons),
                                          verite.eroder(verite.echantillonner_plus_proche(valide_erp, rayons)), metrique))
    return verite.resume_panorama(par_vue)


def _arrondi(x: float | None) -> float | None:
    return None if x is None or not math.isfinite(x) else round(float(x), 4)
