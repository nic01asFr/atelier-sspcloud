"""Les routes des données : le brut, les recettes (aperçu sans rien écrire), les variantes, l'explorateur d'images, les corrections."""

from __future__ import annotations

import csv
import io
import json
import threading
from pathlib import Path
from typing import Any, Callable

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel

from laboratoire.donnees.brut import RapportBrut, scanner
from laboratoire.donnees.construction import ConstructionRefusee, construire, lignes_de_controle, nom_sur
from laboratoire.donnees.controles import bloquants, controler
from laboratoire.donnees.recette import Recette, lire_corrections, planifier
from laboratoire.empreinte import empreinte
from laboratoire.projet import Racine
from laboratoire.validation.journal import Journal
from laboratoire.variante import JEUX, Variante, VarianteInvalide

MAX_IMAGES = 200
LARGEUR_MAX = 1024


class Correction(BaseModel):
    chemin: str
    decision: str  # une classe, ou « douteuse »
    note: str = ""


def monter_donnees(app: FastAPI, racine: Racine, ident: Callable[[str], str], journal: Journal) -> Callable[[], RapportBrut]:
    verrou = threading.Lock()
    cache: dict[str, Any] = {}
    constructions: dict[str, dict[str, Any]] = {}  # id → {fait, total, erreur}

    def brut() -> RapportBrut:
        with verrou:
            marque = racine.brut.stat().st_mtime if racine.brut.exists() else None
            if cache.get("marque") != marque or "rapport" not in cache:
                cache["rapport"], cache["marque"] = scanner(racine.brut), marque
            return cache["rapport"]

    @app.get("/api/brut")
    def lire_brut(rafraichir: bool = False) -> dict[str, Any]:
        if rafraichir:
            cache.clear()
        r = brut()
        return {"resume": r.resume(), "anomalies": r.anomalies[:200], "dossier": str(racine.brut)}

    def plan_de(recette: Recette):
        return planifier(brut().images, recette, lire_corrections(racine.corrections), journal.retenues())

    def id_de(recette: Recette) -> str:
        """Même recette, mêmes corrections et mêmes décisions → même variante. Une décision nouvelle donne une variante nouvelle (suffixe)."""
        base = f"{nom_sur(recette.nom)[:30] + '-' if recette.nom else 'v-'}{recette.empreinte()[:8]}"
        if not recette.corrections:
            return base
        etat = {
            "corrections": sorted((k, v) for k, v in lire_corrections(racine.corrections).items()),
            "validations": sorted((k, d.nombre, d.forme, d.douteuse) for k, d in journal.retenues().items()),
        }
        if not etat["corrections"] and not etat["validations"]:
            return base
        return f"{base}-c{empreinte(etat)[:6]}"

    @app.post("/api/variantes/apercu")
    def apercu(recette: Recette) -> dict[str, Any]:
        """Tout ce que ferait la recette, sans écrire une image."""
        plan = plan_de(recette)
        constats = controler(lignes_de_controle(plan), plan.classes())
        ident_variante = id_de(recette)
        return {
            "id": ident_variante,
            "empreinte": recette.empreinte(),
            "existe": racine.dossier_variante(ident_variante).is_dir(),
            "classes": plan.classes(),
            "effectifs": plan.effectifs(),
            "effectifs_sans_copies": plan.effectifs_sans_copies(),
            "groupes": plan.groupes_par_jeu(),
            "ecartes": plan.ecartes,
            "controles": constats,
            "constructible": bool(plan.lignes) and not bloquants(constats),
        }

    def travail(ident_variante: str, recette: Recette) -> None:
        etat = constructions[ident_variante]
        try:
            plan = plan_de(recette)

            def progression(fait: int, total: int) -> None:
                etat["fait"], etat["total"] = fait, total

            construire(racine.brut, plan, recette, racine.dossier_variante(ident_variante), progression)
            etat["termine"] = True
        except (ConstructionRefusee, OSError, ValueError) as exc:
            etat["erreur"] = str(exc)
        finally:
            etat["fini"] = True

    @app.post("/api/variantes", status_code=202)
    def construire_variante(recette: Recette) -> dict[str, Any]:
        ident_variante = id_de(recette)
        with verrou:
            if racine.dossier_variante(ident_variante).is_dir():
                return {"id": ident_variante, "deja_construite": True}
            if ident_variante in constructions and not constructions[ident_variante].get("fini"):
                return {"id": ident_variante, "en_cours": True}
            constructions[ident_variante] = {"fait": 0, "total": 0}
        threading.Thread(target=travail, args=(ident_variante, recette), name=f"construction-{ident_variante}", daemon=True).start()
        return {"id": ident_variante, "en_cours": True}

    @app.get("/api/variantes/{ident_variante}")
    def variante(ident_variante: str) -> dict[str, Any]:
        i = ident(ident_variante)
        dossier = racine.dossier_variante(i)
        if not dossier.is_dir():
            etat = constructions.get(i)
            if etat is None:
                raise HTTPException(404, f"variante inconnue : {i}")
            return {"id": i, "construction": etat}
        try:
            v = Variante(dossier)
        except VarianteInvalide as exc:
            raise HTTPException(422, str(exc)) from exc

        def lire(nom: str) -> Any:
            f = dossier / nom
            return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None

        return {
            "id": i, "classes": v.classes(), "effectifs": v.effectifs(), "groupes": {j: sorted(v.groupes(j)) for j in JEUX},
            "recette": lire("recette.json"), "controles": (lire("controles.json") or {}).get("controles"),
            "ecartes": (lire("controles.json") or {}).get("ecartes"),
        }

    @app.get("/api/variantes/{ident_variante}/images")
    def images(
        ident_variante: str, jeu: str = Query("train"), classe: str | None = None, groupe: str | None = None,
        decalage: int = Query(0, ge=0), limite: int = Query(48, ge=1, le=MAX_IMAGES),
    ) -> dict[str, Any]:
        if jeu not in JEUX:
            raise HTTPException(422, f"jeu inconnu : {jeu}")
        v = _ouvrir(ident_variante)
        choisies = [e for e in v.echantillons(jeu) if (classe is None or e.classe == classe) and (groupe is None or e.groupe == groupe)]
        return {
            "total": len(choisies),
            "images": [
                {"fichier": e.fichier.relative_to(v.dossier.resolve()).as_posix(), "classe": e.classe, "groupe": e.groupe, "jeu": e.jeu}
                for e in choisies[decalage:decalage + limite]
            ],
        }

    def _ouvrir(ident_variante: str) -> Variante:
        dossier = racine.dossier_variante(ident(ident_variante))
        if not dossier.is_dir():
            raise HTTPException(404, f"variante inconnue : {ident_variante}")
        try:
            return Variante(dossier)
        except VarianteInvalide as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/variantes/{ident_variante}/image")
    def une_image(ident_variante: str, fichier: str, largeur: int = Query(0, ge=0, le=LARGEUR_MAX)) -> Response:
        v = _ouvrir(ident_variante)
        base = v.dossier.resolve()
        chemin = (base / fichier).resolve()
        if base not in chemin.parents or not chemin.is_file() or chemin.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            raise HTTPException(404, "image introuvable")
        if not largeur:
            return Response(chemin.read_bytes(), media_type="image/jpeg" if chemin.suffix.lower() != ".png" else "image/png", headers={"Cache-Control": "private, max-age=3600"})
        with Image.open(chemin) as im:
            im = im.convert("RGB")
            im.thumbnail((largeur, largeur * 2))
            tampon = io.BytesIO()
            im.save(tampon, "JPEG", quality=80)
        return Response(tampon.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/api/comparer-variantes")
    def comparer_variantes(a: str, b: str) -> dict[str, Any]:
        sortie = {}
        for cle, i in (("a", a), ("b", b)):
            v = _ouvrir(i)
            f = v.dossier / "recette.json"
            sortie[cle] = {"id": i, "effectifs": v.effectifs(), "classes": v.classes(), "recette": json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None}
        ra, rb = sortie["a"]["recette"] or {}, sortie["b"]["recette"] or {}
        sortie["differences"] = {k: [ra.get(k), rb.get(k)] for k in sorted(set(ra) | set(rb)) if ra.get(k) != rb.get(k) and k != "nom"}
        return sortie

    # -- corrections d'étiquettes : le brut n'est jamais modifié ----------------

    @app.get("/api/corrections")
    def corrections() -> list[dict[str, str]]:
        if not racine.corrections.is_file():
            return []
        with racine.corrections.open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    @app.post("/api/corrections", status_code=201)
    def corriger(c: Correction = Body(...)) -> dict[str, Any]:
        if c.decision != "douteuse" and not c.decision.strip():
            raise HTTPException(422, "décision vide")
        if "\n" in c.note or "\n" in c.chemin or "\n" in c.decision:
            raise HTTPException(422, "pas de saut de ligne")
        connu = {i.chemin for i in brut().images}
        if c.chemin not in connu:
            raise HTTPException(404, "image inconnue du brut")
        with verrou:
            existe = racine.corrections.is_file()
            racine.corrections.parent.mkdir(parents=True, exist_ok=True)
            with racine.corrections.open("a", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["chemin", "decision", "note"])
                if not existe:
                    w.writeheader()
                w.writerow({"chemin": c.chemin, "decision": c.decision.strip(), "note": c.note})
        return {"enregistre": True, "effet": "pris en compte par les prochaines variantes dont la recette garde « corrections »"}

    return brut
