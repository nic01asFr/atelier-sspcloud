"""Le livrable : les modèles retenus, leurs listes d'images et leurs mesures, à télécharger depuis l'interface.

Le dossier `<racine>/livrable/` est constitué par `outils/constituer_livrable.py` (des fichiers à plat). Ces routes ne servent que ce qu'il contient :
un nom demandé doit être exactement celui d'un fichier de ce dossier, rien d'autre (ni sous-dossier, ni `..`, ni lien symbolique).
Elles sont en lecture : l'administrateur et le relecteur y accèdent, le valideur non (la règle générale des rôles s'applique).
"""

from __future__ import annotations

import csv
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from laboratoire.projet import Racine

DOSSIER = "livrable"


def monter_livrable(app: FastAPI, racine: Racine) -> None:
    def fichiers() -> list[Path]:
        d = racine.chemin / DOSSIER
        if not d.is_dir():
            return []
        return sorted((f for f in d.iterdir() if f.is_file() and not f.is_symlink() and not f.name.startswith(".")), key=lambda f: f.name)

    @app.get("/api/livrable")
    def lister() -> dict[str, Any]:
        """Les fichiers du livrable et son tableau de synthèse (une ligne par groupe), ou `existe: false` s'il n'a pas été constitué."""
        liste = fichiers()
        synthese: list[dict[str, str]] = []
        fichier_synthese = racine.chemin / DOSSIER / "synthese.csv"
        if fichier_synthese.is_file() and not fichier_synthese.is_symlink():
            with fichier_synthese.open(encoding="utf-8", newline="") as f:
                synthese = list(csv.DictReader(f))
        return {
            "existe": bool(liste),
            "fichiers": [{"nom": f.name, "taille": f.stat().st_size} for f in liste],
            "taille_totale": sum(f.stat().st_size for f in liste),
            "synthese": synthese,
        }

    @app.get("/api/livrable/fichier")
    def fichier(nom: str = Query(..., max_length=200)) -> FileResponse:
        for f in fichiers():
            if f.name == nom:  # le nom doit être celui d'un fichier listé : pas de chemin construit à partir de la requête
                return FileResponse(f, filename=f.name)
        raise HTTPException(404, "fichier inconnu du livrable")

    @app.get("/api/livrable/archive")
    def archive() -> FileResponse:
        """Tout le livrable en une archive zip (sans compression : les modèles ne se compressent presque pas)."""
        liste = fichiers()
        if not liste:
            raise HTTPException(404, "le livrable n'a pas été constitué")
        temporaire = tempfile.NamedTemporaryFile(prefix="livrable-", suffix=".zip", delete=False)
        temporaire.close()
        try:
            with zipfile.ZipFile(temporaire.name, "w", zipfile.ZIP_STORED) as z:
                for f in liste:
                    z.write(f, f"{DOSSIER}/{f.name}")
        except BaseException:
            os.unlink(temporaire.name)
            raise
        return FileResponse(temporaire.name, filename="livrable.zip", media_type="application/zip", background=BackgroundTask(os.unlink, temporaire.name))
