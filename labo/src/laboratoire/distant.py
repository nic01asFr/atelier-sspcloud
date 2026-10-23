"""Le laboratoire (CPU, toujours allumé) et le travailleur (GPU, allumé à la demande) : ce que le premier offre au second.

Le laboratoire garde tout ce qui doit rester disponible quand le GPU est éteint : la file, les essais, les images, la validation, les commentaires.
Le travailleur ne garde rien d'essentiel. Il **appelle** le laboratoire (jamais l'inverse : un pod éteint ne reçoit rien) :

    POST /api/travail/prendre            prend le plus ancien essai en file, avec son jeu de données (empreinte)
    GET  /api/travail/variante/{id}      le jeu de données, en archive tar
    POST /api/travail/{id}/signe         « je suis là » ; répond si la personne a demandé l'arrêt
    POST /api/travail/{id}/journal       la suite du journal (reprise par décalage : un envoi perdu ne crée ni trou ni doublon)
    POST /api/travail/{id}/terminer      les fichiers de l'essai, en archive tar

Seul le jeton d'un travailleur ouvre ces routes (`valideurs.json`, rôle « travailleur »). Une archive reçue n'écrit que dans le dossier de
l'essai concerné, ne crée que des fichiers ordinaires et a une taille bornée.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from laboratoire.executeur import Executeur
from laboratoire.projet import Racine
from laboratoire.registre import Registre
from laboratoire.variante import Variante, VarianteInvalide

MAX_ARCHIVE = 2 * 1024**3  # octets reçus pour les fichiers d'un essai
MAX_FICHIERS = 5000
MAX_METRIQUES = 200_000
MAX_MORCEAU_JOURNAL = 1_000_000
PRESENT_S = 60.0  # un travailleur est « connecté » s'il a appelé il y a moins que cela


class Appel(BaseModel):
    travailleur: str
    gpu: dict[str, Any] | None = None


class Signe(BaseModel):
    travailleur: str
    metriques: str | None = None


def empreinte_variante(dossier: Path) -> str:
    """Identifie le contenu d'une variante par son manifeste (l'identifiant d'une variante porte déjà la recette, ceci détecte une reconstruction)."""
    manifeste = dossier / "manifeste.csv"
    return hashlib.sha256(manifeste.read_bytes()).hexdigest()[:16] if manifeste.is_file() else ""


def _nom_sur(nom: str) -> PurePosixPath | None:
    chemin = PurePosixPath(nom)
    if chemin.is_absolute() or ".." in chemin.parts or not chemin.parts:
        return None
    return chemin


def extraire_sur(archive: Path, destination: Path) -> int:
    """Extrait `archive` dans `destination` : fichiers ordinaires seulement, chemins relatifs sans `..`. Rend le nombre de fichiers."""
    destination.mkdir(parents=True, exist_ok=True)
    racine = destination.resolve()
    n = 0
    with tarfile.open(archive, "r:*") as t:
        for m in t:
            chemin = _nom_sur(m.name)
            if chemin is None:
                raise ValueError(f"archive refusée : chemin {m.name!r}")
            if m.isdir():
                continue
            if not m.isreg():
                raise ValueError(f"archive refusée : {m.name!r} n'est pas un fichier ordinaire")
            n += 1
            if n > MAX_FICHIERS:
                raise ValueError("archive refusée : trop de fichiers")
            cible = (racine / chemin).resolve()
            if racine not in cible.parents:
                raise ValueError(f"archive refusée : {m.name!r} sort du dossier")
            cible.parent.mkdir(parents=True, exist_ok=True)
            source = t.extractfile(m)
            if source is None:
                continue
            with source, open(cible, "wb") as f:
                shutil.copyfileobj(source, f)
    return n


def monter_travail(
    app: FastAPI, racine: Racine, registre: Registre, executeur: Executeur, ident: Callable[[str], str],
) -> dict[str, Any]:
    """Monte les routes du travailleur. Rend l'état de présence (lu par `/api/pod`)."""
    presence: dict[str, Any] = {"nom": None, "vu": float("-inf"), "gpu": None}

    def retenir(appel: Appel) -> None:
        presence.update(nom=appel.travailleur, vu=time.monotonic(), gpu=appel.gpu)

    def connecte() -> bool:
        return time.monotonic() - presence["vu"] < PRESENT_S

    presence["connecte"] = connecte

    def confie_a(essai_id: str, travailleur: str) -> dict[str, Any]:
        essai = registre.essai(essai_id)
        if essai["etat"] != "en_cours" or essai.get("travailleur") != travailleur:
            raise HTTPException(409, f"{essai_id} n'est plus confié à {travailleur} (état « {essai['etat']} »)")
        return essai

    @app.post("/api/travail/prendre")
    def prendre(appel: Appel) -> dict[str, Any]:
        retenir(appel)
        while True:
            essai = registre.prendre_pour(appel.travailleur)
            if essai is None:
                return {"essai": None}
            dossier = racine.dossier_variante(essai["config"]["jeu"])
            try:
                Variante(dossier)
            except VarianteInvalide as exc:  # un jeu absent n'occupe ni la file ni le GPU : l'essai échoue, on passe au suivant
                registre.changer_etat(essai["id"], "echoue", fin=time.time(), erreur=f"jeu de données inutilisable : {exc}")
                continue
            dossier_essai = racine.dossier_essai(essai["id"])
            dossier_essai.mkdir(parents=True, exist_ok=True)
            ancien = dossier_essai / "journal.log"
            if ancien.is_file():  # nouvelle tentative (essai interrompu puis repris) : l'ancien journal est gardé à part, le nouveau repart de zéro
                os.replace(ancien, dossier_essai / f"journal.{int(time.time())}.log")
            return {"essai": {"id": essai["id"], "config": essai["config"], "variante": essai["config"]["jeu"],
                              "empreinte_variante": empreinte_variante(dossier)}}

    @app.get("/api/travail/variante/{variante_id}")
    def variante(variante_id: str) -> FileResponse:
        dossier = racine.dossier_variante(ident(variante_id))
        if not dossier.is_dir():
            raise HTTPException(404, f"jeu inconnu : {variante_id}")
        fd, nom = tempfile.mkstemp(prefix="variante-", suffix=".tar", dir=racine.chemin)
        os.close(fd)
        with tarfile.open(nom, "w") as t:  # non compressé : les images le sont déjà
            for fichier in sorted(dossier.rglob("*")):
                if fichier.is_file() and not fichier.is_symlink():
                    t.add(fichier, arcname=str(fichier.relative_to(dossier)), recursive=False)
        return FileResponse(nom, media_type="application/x-tar", background=BackgroundTask(os.unlink, nom),
                            headers={"X-Empreinte": empreinte_variante(dossier)})

    @app.post("/api/travail/{essai_id}/signe")
    def signe(essai_id: str, corps: Signe) -> dict[str, Any]:
        i = ident(essai_id)
        confie_a(i, corps.travailleur)
        reponse = registre.signe(i, corps.travailleur)
        if corps.metriques is not None and len(corps.metriques) <= MAX_METRIQUES:
            (racine.dossier_essai(i) / "metriques.csv").write_text(corps.metriques, encoding="utf-8")
        return reponse

    @app.post("/api/travail/{essai_id}/journal")
    async def journal(essai_id: str, request: Request, travailleur: str = Query(...), debut: int = Query(0, ge=0)) -> dict[str, int]:
        i = ident(essai_id)
        confie_a(i, travailleur)
        chemin = racine.dossier_essai(i) / "journal.log"
        taille = chemin.stat().st_size if chemin.is_file() else 0
        if debut != taille:
            return {"suivant": taille}  # envoi décalé : on dit où l'on en est, le travailleur reprend de là
        morceau = b""
        async for part in request.stream():
            morceau += part
            if len(morceau) > MAX_MORCEAU_JOURNAL:
                raise HTTPException(413, "morceau de journal trop gros")
        with chemin.open("ab") as f:
            f.write(morceau)
        registre.signe(i, travailleur)
        return {"suivant": taille + len(morceau)}

    @app.post("/api/travail/{essai_id}/terminer")
    async def terminer(
        essai_id: str, request: Request, travailleur: str = Query(...), code: int | None = Query(None), arrete: bool = Query(False),
    ) -> dict[str, Any]:
        i = ident(essai_id)
        confie_a(i, travailleur)
        fd, nom = tempfile.mkstemp(prefix="essai-", suffix=".tar", dir=racine.chemin)
        os.close(fd)
        try:
            total = 0
            with open(nom, "wb") as f:
                async for part in request.stream():
                    total += len(part)
                    if total > MAX_ARCHIVE:
                        raise HTTPException(413, "archive trop grosse")
                    f.write(part)
            if total:  # le journal arrive au fil de l'eau (route ci-dessus) : l'archive n'en contient pas et n'écrase rien
                try:
                    extraire_sur(Path(nom), racine.dossier_essai(i))
                except (ValueError, tarfile.TarError) as exc:
                    raise HTTPException(422, str(exc)) from exc
            return executeur.conclure_distant(i, code, arrete)
        finally:
            Path(nom).unlink(missing_ok=True)

    return presence
