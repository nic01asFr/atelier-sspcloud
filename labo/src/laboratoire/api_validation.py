"""Les routes de la validation humaine : les files, les décisions, les statistiques, l'image du brut (sans jamais sortir du brut)."""

from __future__ import annotations

import csv
import io
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import PlainTextResponse
from PIL import Image
from pydantic import BaseModel, ConfigDict

from laboratoire.donnees.brut import RapportBrut
from laboratoire.donnees.construction import preparer
from laboratoire.projet import Racine
from laboratoire.validation.files import FILES, file_d_images, voisins
from laboratoire.validation.journal import DecisionRefusee, Journal, nom_valide

LARGEUR_MAX = 1400


class NouvelleDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image: str
    validateur: str
    nombre: int | None = None
    forme: str | None = None
    douteuse: bool = False
    fichier: str
    aveugle: bool = True
    duree_ms: int | None = None
    note: str = ""


class Annulation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    validateur: str


def monter_validation(app: FastAPI, racine: Racine, ident: Callable[[str], str], journal: Journal, brut: Callable[[], RapportBrut]) -> None:
    def images():
        return brut().images

    def par_chemin() -> dict[str, Any]:
        return {i.chemin: i for i in images()}

    @app.exception_handler(DecisionRefusee)
    async def _refusee(_, exc: DecisionRefusee):
        from fastapi.responses import JSONResponse

        return JSONResponse({"erreur": str(exc)}, status_code=422)

    @app.get("/api/validation/files")
    def lister_les_files() -> list[dict[str, Any]]:
        return [{"nom": nom, "description": d, "taille": len(file_d_images(nom, images()))} for nom, d in FILES.items()]

    @app.get("/api/validation/file")
    def suivant(
        type: str = Query("audit_classe_1"), validateur: str = Query(...), limite: int = Query(1, ge=1, le=20), image: str | None = None,
    ) -> dict[str, Any]:
        """Les prochaines images **non encore validées par ce valideur**. L'ancienne étiquette est rendue : l'écran décide de la montrer ou non."""
        nom = nom_valide(validateur)
        try:
            file = file_d_images(type, images())
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        faites = journal.deja_faites(nom, type)
        restantes = [c for c in file if c not in faites]
        index = par_chemin()
        if image is not None:  # une image précise (revoir celle qu'on vient d'annuler), à condition qu'elle soit dans la file
            if image not in file:
                raise HTTPException(404, "cette image n'est pas dans la file")
            restantes = [image] + [c for c in restantes if c != image]
        items = []
        for chemin in restantes[:limite]:
            i = index[chemin]
            avant, apres = voisins(images(), chemin)
            items.append({
                "image": chemin, "cote": i.cote, "groupe": i.groupe, "largeur": i.largeur, "hauteur": i.hauteur,
                "ancien": {"nombre": i.n, "forme": i.forme or "aucune"}, "avant": avant, "apres": apres,
            })
        return {"file": type, "total": len(file), "faites": len(file) - len(restantes), "restantes": len(restantes), "items": items}

    @app.post("/api/validation/decisions", status_code=201)
    def decider(d: NouvelleDecision) -> dict[str, Any]:
        i = par_chemin().get(d.image)
        if i is None:
            raise HTTPException(404, "image inconnue du brut")
        if d.fichier not in FILES:
            raise HTTPException(422, f"file inconnue : {d.fichier!r}")
        identifiant = journal.enregistrer(
            image=d.image, validateur=d.validateur, nombre=d.nombre, forme=d.forme, douteuse=d.douteuse, fichier=d.fichier,
            ancien_nombre=i.n, ancienne_forme=i.forme or "aucune", aveugle=d.aveugle, duree_ms=d.duree_ms, note=d.note,
        )
        return {"id": identifiant}

    @app.post("/api/validation/decisions/{decision_id}/annuler", status_code=201)
    def annuler(decision_id: int, a: Annulation) -> dict[str, Any]:
        return {"id": journal.annuler(decision_id, a.validateur)}

    @app.get("/api/validation/derniere")
    def derniere(validateur: str = Query(...)) -> dict[str, Any]:
        d = journal.derniere(nom_valide(validateur))
        return {"decision": {k: d[k] for k in ("id", "image", "nombre", "forme", "douteuse", "fichier")} if d else None}

    @app.get("/api/validation/stats")
    def stats(fichier: str | None = None) -> dict[str, Any]:
        return journal.statistiques(fichier)

    @app.get("/api/validation/export")
    def exporter() -> PlainTextResponse:
        """Les décisions retenues, en CSV (nombre, forme, douteuse). Les désaccords n'y sont pas : ils attendent un arbitre."""
        sortie = io.StringIO()
        w = csv.writer(sortie, lineterminator="\n")
        w.writerow(["chemin", "nombre", "forme", "douteuse"])
        for chemin, d in sorted(journal.retenues().items()):
            w.writerow([chemin, "" if d.nombre is None else d.nombre, d.forme or "", int(d.douteuse)])
        return PlainTextResponse(sortie.getvalue(), media_type="text/csv; charset=utf-8")

    @app.get("/api/brut/image")
    def image_du_brut(chemin: str, largeur: int = Query(0, ge=0, le=LARGEUR_MAX), rognage: bool = False) -> Response:
        """Une image du brut, par son chemin tel que le scan le donne : un chemin qui n'est pas dans le scan n'ouvre rien."""
        i = par_chemin().get(chemin)
        if i is None:
            raise HTTPException(404, "image introuvable")
        fichier = racine.brut / i.chemin
        if not fichier.is_file():
            raise HTTPException(404, "image introuvable")
        with Image.open(fichier) as im:
            im = preparer(im, i.cote, "rognage") if rognage else im.convert("RGB")
            if largeur:
                im.thumbnail((largeur, largeur * 2))
            tampon = io.BytesIO()
            im.save(tampon, "JPEG", quality=85)
        return Response(tampon.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})
