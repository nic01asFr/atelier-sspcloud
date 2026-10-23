"""Les routes de la tâche « profondeur » : les jeux de panoramas, les cartes, les paires à juger à l'aveugle, les votes, la synthèse.

Qui voit quoi : un *valideur* (une personne qui vote) ne voit que des paires anonymes et les images de ces paires — jamais le nom d'un modèle, jamais
le classement, avant d'avoir voté. Un *relecteur* et l'administrateur voient tout. Les images d'une paire se demandent par un jeton opaque :
l'adresse ne dit pas de quel modèle vient chaque carte.
"""

from __future__ import annotations

import io
import json
import math
import random
import re
import secrets
import time
from collections import OrderedDict, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any, Callable

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel, ConfigDict

from laboratoire.profondeur import geometrie as g
from laboratoire.profondeur import mesures
from laboratoire.profondeur.carte import vers_jpeg
from laboratoire.profondeur.votes import CHOIX, VoteRefuse, Votes
from laboratoire.projet import Racine
from laboratoire.registre import Registre
from laboratoire.variante import Variante, VarianteInvalide

LARGEUR_VUE = 512
PAIRES_EN_MEMOIRE = 2000
_VUE = re.compile(r"^c(\d{3})_t(\d{2})$")


class NouveauVote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    choix: str
    duree_ms: int | None = None
    note: str = ""


def _vue_depuis_nom(nom: str, fov: float) -> g.Vue:
    m = _VUE.match(nom)
    if not m:
        raise HTTPException(400, f"nom de vue refusé : {nom!r}")
    return g.Vue(float(m.group(1)), float(m.group(2)), fov)


def monter_profondeur(app: FastAPI, racine: Racine, registre: Registre, votes: Votes, ident: Callable[[str], str]) -> None:
    paires: OrderedDict[str, dict[str, Any]] = OrderedDict()
    accords: dict[tuple[str, str], dict[str, float]] = {}

    def qui(request: Request) -> tuple[str, str]:
        return getattr(request.state, "auteur", "admin"), getattr(request.state, "role", "admin")

    def lecture_complete(request: Request) -> None:
        if qui(request)[1] == "valideur":
            raise HTTPException(403, "réservé aux relecteurs : une personne qui vote ne voit pas les modèles avant d'avoir jugé")

    # -- les jeux et les essais -------------------------------------------

    def jeu_panoramas(jeu: str) -> Variante:
        try:
            v = Variante(racine.dossier_variante(ident(jeu)))
        except VarianteInvalide as exc:
            raise HTTPException(404, f"jeu inconnu ou invalide : {exc}") from exc
        return v

    def lignes_manifeste(jeu: str) -> list[dict[str, str]]:
        import csv

        with (racine.dossier_variante(ident(jeu)) / "manifeste.csv").open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    def essais_profondeur(jeu: str) -> dict[str, dict[str, Any]]:
        """Le dernier essai terminé de chaque modèle pour ce jeu."""
        par_modele: dict[str, dict[str, Any]] = {}
        for e in sorted(registre.lister(etat="termine", jeu=jeu, limite=2000), key=lambda e: e["id"]):
            if e["famille"] == "profondeur":
                par_modele[e["modele"]] = e
        return par_modele

    def vues_de(essai_id: str, pano: str) -> set[str]:
        d = racine.dossier_essai(essai_id) / "apercus" / pano
        return {p.stem for p in d.glob("*.jpg")} if d.is_dir() else set()

    def fov_de(essai: dict[str, Any]) -> float:
        return float((essai["config"]["methode"].get("reglages") or {}).get("fov", 90.0))

    # -- images ------------------------------------------------------------

    def jpeg(octets: bytes) -> Response:
        return Response(octets, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

    def vue_source(jeu: str, pano: str, vue_nom: str, fov: float) -> bytes:
        cache = racine.chemin / "cache" / ident(jeu) / f"{ident(pano)}_{vue_nom}_{int(fov)}.jpg"
        if cache.is_file():
            return cache.read_bytes()
        fichier = racine.dossier_variante(ident(jeu)) / "val" / "panorama" / f"{ident(pano)}.jpg"
        if not fichier.is_file():
            raise HTTPException(404, "panorama inconnu")
        with Image.open(fichier) as im:
            erp = np.asarray(im.convert("RGB"))
        v = _vue_depuis_nom(vue_nom, fov)
        octets = vers_jpeg(np.clip(g.extraire_vue(erp, v, LARGEUR_VUE, round(LARGEUR_VUE * 3 / 4)), 0, 255).astype(np.uint8), qualite=88)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(octets)
        return octets

    # -- consultation (relecteur et administrateur) ------------------------

    @app.get("/api/tache")
    def tache(request: Request) -> dict[str, str]:
        auteur, role = qui(request)
        return {"tache": app.state.tache, "auteur": auteur, "role": role}

    @app.get("/api/profondeur/jeux")
    def jeux(request: Request) -> list[dict[str, Any]]:
        lecture_complete(request)
        sortie = []
        if racine.variantes.is_dir():
            for d in sorted(p for p in racine.variantes.iterdir() if p.is_dir()):
                try:
                    lignes = lignes_manifeste(d.name)
                except OSError:
                    continue
                if lignes and all(l.get("classe") == "panorama" for l in lignes):
                    sortie.append({"id": d.name, "panoramas": len(lignes), "sequences": len({l["groupe"] for l in lignes}),
                                   "essais": sorted(essais_profondeur(d.name))})
        return sortie

    @app.get("/api/profondeur/jeu/{jeu}/panoramas")
    def panoramas(jeu: str, request: Request) -> list[dict[str, Any]]:
        lecture_complete(request)
        return [{"item": l["item"], "groupe": l["groupe"], "licence": l["licence"], "producteur": l["producteur"], "date": l["date"],
                 "lon": float(l["lon"]), "lat": float(l["lat"])} for l in lignes_manifeste(jeu)]

    @app.get("/api/profondeur/jeu/{jeu}/panorama/{item}.jpg")
    def panorama(jeu: str, item: str, request: Request, largeur: int = Query(1024, ge=128, le=2048)) -> Response:
        lecture_complete(request)
        fichier = racine.dossier_variante(ident(jeu)) / "val" / "panorama" / f"{ident(item)}.jpg"
        if not fichier.is_file():
            raise HTTPException(404, "panorama inconnu")
        with Image.open(fichier) as im:
            im = im.convert("RGB")
            im = im.resize((largeur, round(im.height * largeur / im.width)), Image.BILINEAR)
            t = io.BytesIO()
            im.save(t, "JPEG", quality=85)
        return jpeg(t.getvalue())

    @app.get("/api/profondeur/jeu/{jeu}/vue/{item}/{vue}.jpg")
    def vue(jeu: str, item: str, vue: str, request: Request, fov: float = Query(90.0, ge=20, le=140)) -> Response:
        lecture_complete(request)
        return jpeg(vue_source(jeu, item, vue, fov))

    @app.get("/api/profondeur/essai/{essai}/apercu/{item}/{vue}.jpg")
    def apercu(essai: str, item: str, vue: str, request: Request) -> Response:
        lecture_complete(request)
        chemin = racine.dossier_essai(ident(essai)) / "apercus" / ident(item) / f"{ident(vue)}.jpg"
        if not chemin.is_file():
            raise HTTPException(404, "aperçu inconnu")
        return jpeg(chemin.read_bytes())

    # -- le vote à l'aveugle ----------------------------------------------

    def comptes(jeu: str) -> tuple[dict[tuple, int], set[tuple]]:
        total: dict[tuple, int] = defaultdict(int)
        for v in votes.valides(jeu):
            total[(v["panorama"], v["vue"], frozenset((v["modele_gauche"], v["modele_droite"])))] += 1
        return total, set()

    @app.get("/api/profondeur/paire")
    def paire(request: Request, jeu: str | None = Query(None)) -> dict[str, Any]:
        """La paire suivante à juger : la moins jugée, jamais deux fois la même pour la même personne, côtés tirés au hasard.

        Sans `jeu`, on prend le premier jeu où deux modèles au moins sont terminés (une personne qui vote n'a pas la liste des jeux).
        """
        votant, _ = qui(request)
        if jeu is None:
            comparables = [d.name for d in sorted(racine.variantes.iterdir()) if d.is_dir() and len(essais_profondeur(d.name)) >= 2] if racine.variantes.is_dir() else []
            if not comparables:
                raise HTTPException(409, "aucun jeu n'a encore deux modèles terminés à comparer")
            jeu = comparables[0]
        ident(jeu)
        essais = essais_profondeur(jeu)
        if len(essais) < 2:
            raise HTTPException(409, "il faut au moins deux modèles terminés sur ce jeu pour comparer")
        total, _ = comptes(jeu)
        deja = {(v["panorama"], v["vue"], frozenset((v["modele_gauche"], v["modele_droite"]))) for v in votes.valides(jeu) if v["votant"] == votant}
        candidats = []
        for a, b in combinations(sorted(essais), 2):
            for pano in {p.name for p in (racine.dossier_essai(essais[a]["id"]) / "apercus").glob("*")}:
                for vue_nom in sorted(vues_de(essais[a]["id"], pano) & vues_de(essais[b]["id"], pano)):
                    cle = (pano, vue_nom, frozenset((a, b)))
                    if cle not in deja:
                        candidats.append((total.get(cle, 0), a, b, pano, vue_nom))
        if not candidats:
            raise HTTPException(404, "plus aucune paire à juger : vous avez tout vu")
        mini = min(c[0] for c in candidats)
        _, a, b, pano, vue_nom = random.choice([c for c in candidats if c[0] == mini])
        if random.random() < 0.5:
            a, b = b, a
        jeton = secrets.token_urlsafe(9)
        paires[jeton] = {"jeu": jeu, "panorama": pano, "vue": vue_nom, "gauche": (a, essais[a]["id"]), "droite": (b, essais[b]["id"]),
                         "votant": votant, "t0": time.monotonic(), "fov": fov_de(essais[a])}
        while len(paires) > PAIRES_EN_MEMOIRE:
            paires.popitem(last=False)
        restantes = len(candidats) - 1
        return {"jeton": jeton, "jeu": jeu, "panorama": pano, "vue": vue_nom, "restantes": restantes, "deja_juge": len(deja),
                "choix": list(CHOIX), "cible": {"jeu": jeu, "panorama": pano, "vue": vue_nom}}

    def _paire(jeton: str, request: Request) -> dict[str, Any]:
        p = paires.get(jeton)
        if p is None:
            raise HTTPException(404, "paire inconnue ou trop ancienne : redemandez-en une")
        if p["votant"] != qui(request)[0]:
            raise HTTPException(403, "cette paire a été donnée à quelqu'un d'autre")
        return p

    @app.get("/api/profondeur/paire/{jeton}/{cote}.jpg")
    def image_de_paire(jeton: str, cote: str, request: Request) -> Response:
        p = _paire(jeton, request)
        if cote == "source":
            return jpeg(vue_source(p["jeu"], p["panorama"], p["vue"], p["fov"]))
        if cote not in ("gauche", "droite"):
            raise HTTPException(404, "côté inconnu")
        chemin = racine.dossier_essai(p[cote][1]) / "apercus" / p["panorama"] / f"{p['vue']}.jpg"
        if not chemin.is_file():
            raise HTTPException(404, "aperçu absent")
        return jpeg(chemin.read_bytes())

    @app.post("/api/profondeur/paire/{jeton}/vote", status_code=201)
    def voter(jeton: str, corps: NouveauVote, request: Request) -> dict[str, Any]:
        p = _paire(jeton, request)
        vote_id = votes.voter(
            jeu=p["jeu"], panorama=p["panorama"], vue=p["vue"], modele_gauche=p["gauche"][0], modele_droite=p["droite"][0],
            essai_gauche=p["gauche"][1], essai_droite=p["droite"][1], choix=corps.choix, votant=p["votant"],
            duree_ms=corps.duree_ms if corps.duree_ms is not None else round((time.monotonic() - p["t0"]) * 1000), note=corps.note,
        )
        paires.pop(jeton, None)
        return {"vote": vote_id}

    @app.post("/api/profondeur/votes/{vote_id}/annuler")
    def annuler(vote_id: int, request: Request) -> dict[str, int]:
        return {"annulation": votes.annuler(vote_id, qui(request)[0])}

    @app.get("/api/profondeur/votes/moi")
    def mes_votes(request: Request, jeu: str = Query(...)) -> dict[str, Any]:
        votant, _ = qui(request)
        mes = [v for v in votes.valides(jeu) if v["votant"] == votant]
        return {"votant": votant, "total": len(mes), "dernier": mes[-1]["id"] if mes else None}

    @app.exception_handler(VoteRefuse)
    async def _refuse(_: Request, exc: VoteRefuse):
        return JSONResponse({"erreur": str(exc)}, status_code=422)

    # -- la synthèse -------------------------------------------------------

    fichier_accords = racine.chemin / "cache" / "accords.json"

    def lire_cache() -> None:
        try:
            for k, v in json.loads(fichier_accords.read_text(encoding="utf-8")).items():
                x, y = k.split("|")
                accords.setdefault((x, y), {n: (math.nan if c is None else c) for n, c in v.items()})
        except (OSError, ValueError):
            pass

    def ecrire_cache() -> None:
        try:
            fichier_accords.parent.mkdir(parents=True, exist_ok=True)
            fichier_accords.write_text(json.dumps({f"{x}|{y}": {n: (None if not math.isfinite(c) else c) for n, c in v.items()} for (x, y), v in accords.items()}), encoding="utf-8")
        except OSError:
            pass  # le cache n'est qu'une commodité : sans lui, on recalcule

    lire_cache()

    def accord_entre(a: dict[str, Any], b: dict[str, Any]) -> dict[str, float]:
        """Accord de deux essais terminés (un essai terminé ne change plus : le résultat se garde, en mémoire et sur le volume)."""
        cle = (a["id"], b["id"])
        if cle in accords:
            return accords[cle]
        valeurs: dict[str, list[float]] = {"detail": [], "global": []}
        da, db = racine.dossier_essai(a["id"]) / "profondeur", racine.dossier_essai(b["id"]) / "profondeur"
        for fichier in sorted(da.glob("*.npz")):
            if not (db / fichier.name).is_file():
                continue
            with np.load(fichier) as x, np.load(db / fichier.name) as y:
                if list(x["vues"]) != list(y["vues"]):
                    continue
                for nom, detail in (("detail", True), ("global", False)):
                    r = mesures.accord(x["q"].astype(np.float32), x["masque"], y["q"].astype(np.float32), y["masque"], detail=detail)
                    if math.isfinite(r):
                        valeurs[nom].append(r)
        accords[cle] = {nom: (float(np.median(v)) if v else math.nan) for nom, v in valeurs.items()}
        ecrire_cache()
        return accords[cle]

    @app.get("/api/profondeur/synthese")
    def synthese(request: Request, jeu: str = Query(...)) -> dict[str, Any]:
        lecture_complete(request)
        essais = essais_profondeur(jeu)
        modeles = []
        for nom, e in sorted(essais.items()):
            res = (racine.dossier_essai(e["id"]) / "resultats.json")
            r = json.loads(res.read_text(encoding="utf-8")) if res.is_file() else {}
            modeles.append({"modele": nom, "essai": e["id"], "licence": r.get("licence_modele"), "appareil": r.get("appareil"), **r.get("rapport", {})})
        paires_accord = {(a, b): accord_entre(essais[a], essais[b]) for (a, b) in combinations(sorted(essais), 2)}
        def _arrondi(v: float) -> float | None:
            return None if not math.isfinite(v) else round(v, 4)

        accord = {f"{a}|{b}": _arrondi(v["detail"]) for (a, b), v in paires_accord.items()}
        accord_global = {f"{a}|{b}": _arrondi(v["global"]) for (a, b), v in paires_accord.items()}
        vv = votes.valides(jeu)
        juges = []
        for v in vv:
            if v["choix"] == "indecidable":
                continue
            if v["choix"] == "egal":
                juges.append(mesures.Jugement(None, None, v["modele_gauche"], v["modele_droite"], v["panorama"]))
            else:
                gagnant, perdant = (v["modele_gauche"], v["modele_droite"]) if v["choix"] == "gauche" else (v["modele_droite"], v["modele_gauche"])
                juges.append(mesures.Jugement(gagnant, perdant, v["modele_gauche"], v["modele_droite"], v["panorama"]))
        par_votant: dict[str, int] = defaultdict(int)
        for v in vv:
            par_votant[v["votant"]] += 1
        return {
            "jeu": jeu, "modeles": modeles, "accord": accord, "accord_global": accord_global, "classement": mesures.classement(sorted(essais), juges) if len(essais) >= 2 else None,
            "votes": {"total": len(vv), "indecidables": sum(1 for v in vv if v["choix"] == "indecidable"), "par_votant": dict(par_votant)},
        }

    @app.get("/api/profondeur/votes/export")
    def export(request: Request, jeu: str = Query(...)) -> Response:
        if qui(request)[1] != "admin":
            raise HTTPException(403, "réservé à l'administrateur")
        import csv

        t = io.StringIO()
        champs = ["id", "jeu", "panorama", "vue", "modele_gauche", "modele_droite", "choix", "votant", "duree_ms", "note", "cree_le"]
        w = csv.DictWriter(t, fieldnames=champs, extrasaction="ignore")
        w.writeheader()
        w.writerows(votes.valides(jeu))
        return Response(t.getvalue(), media_type="text/csv; charset=utf-8")
