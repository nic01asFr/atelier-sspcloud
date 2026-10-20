"""Le service du laboratoire : une seule interface, pour la page, pour l'agent du projet et pour l'Assistant.

Sécurité :
- le service n'a pas d'authentification propre, il en reçoit une : si `LABO_JETON` est défini, **toute** requête (page comprise) doit le porter,
  en en-tête `Authorization: Bearer …` ou en cookie `labo_jeton` — c'est ce que pose le relais de l'Atelier ;
- hors boucle locale, le service refuse de démarrer sans jeton (voir `__main__`) : un pod du namespace ne l'atteint pas librement ;
- tout identifiant qui devient un nom de dossier passe par `identifiant_sur` ;
- l'ouverture du test est une action engageante : elle exige `{"confirmer": true}` et elle est comptée.
"""

from __future__ import annotations

import csv
import hmac
import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from laboratoire.adaptateurs import adaptateur as obtenir_adaptateur
from laboratoire.executeur import Executeur
from laboratoire.modeles import ConfigEssai
from laboratoire.projet import Racine, identifiant_sur
from laboratoire.registre import EssaiInconnu, Registre, TransitionRefusee
from laboratoire.travailleur import Travailleur
from laboratoire.variante import Variante, VarianteInvalide

WEB = Path(__file__).parent / "web"
MAX_ERREURS = 500
MAX_JOURNAL = 200_000  # octets rendus d'un coup


class Confirmation(BaseModel):
    confirmer: bool = False


def _metriques(dossier: Path) -> list[dict[str, Any]]:
    chemin = dossier / "metriques.csv"
    if not chemin.is_file():
        return []
    lignes = []
    with chemin.open(encoding="utf-8", newline="") as f:
        for ligne in csv.DictReader(f):
            sortie: dict[str, Any] = {}
            for k, v in ligne.items():
                try:
                    sortie[k] = float(v)
                except (TypeError, ValueError):
                    sortie[k] = v
            lignes.append(sortie)
    return lignes


def _etat_gpu() -> dict[str, Any] | None:
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        sortie = subprocess.run(  # noqa: S603,S607 - commande fixe
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4, check=False,
        ).stdout.strip().splitlines()
        if not sortie:
            return None
        nom, util, utilise, total = [x.strip() for x in sortie[0].split(",")]
        return {"nom": nom, "utilisation_pct": int(util), "memoire_utilisee_mo": int(utilise), "memoire_totale_mo": int(total)}
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


def creer_app(
    racine: Racine,
    *,
    jeton: str | None = None,
    demarrer_travailleur: bool = True,
    battement: Callable[[], Any] | None = None,
) -> FastAPI:
    registre = Registre(racine.base)
    executeur = Executeur(racine, registre)
    travailleur = Travailleur(registre, executeur, battement=battement)

    @asynccontextmanager
    async def cycle(_: FastAPI):
        if demarrer_travailleur:
            travailleur.demarrer()
        try:
            yield
        finally:
            if demarrer_travailleur:
                travailleur.arreter()
            registre.fermer()

    app = FastAPI(title="Laboratoire d'essais", lifespan=cycle, docs_url="/api/docs" if jeton is None else None, redoc_url=None, openapi_url=None if jeton else "/api/openapi.json")
    app.state.registre, app.state.executeur, app.state.travailleur, app.state.racine = registre, executeur, travailleur, racine

    @app.middleware("http")
    async def verifier_le_jeton(request: Request, suite):
        if jeton and request.url.path != "/sante":
            presente = request.headers.get("authorization", "")
            fourni = presente[7:] if presente.lower().startswith("bearer ") else request.cookies.get("labo_jeton", "")
            if not fourni or not hmac.compare_digest(fourni.encode(), jeton.encode()):
                return JSONResponse({"erreur": "jeton absent ou faux"}, status_code=401)
        return await suite(request)

    @app.exception_handler(EssaiInconnu)
    async def _inconnu(_: Request, exc: EssaiInconnu):
        return JSONResponse({"erreur": f"essai inconnu : {exc.args[0]}"}, status_code=404)

    @app.exception_handler(TransitionRefusee)
    async def _transition(_: Request, exc: TransitionRefusee):
        return JSONResponse({"erreur": str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def _valeur(_: Request, exc: ValueError):
        return JSONResponse({"erreur": str(exc)}, status_code=422)

    def ident(valeur: str) -> str:
        try:
            return identifiant_sur(valeur)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    # -- état ------------------------------------------------------------

    @app.get("/sante")
    def sante() -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.get("/api/pod")
    def pod() -> dict[str, Any]:
        usage = shutil.disk_usage(racine.chemin if racine.chemin.exists() else racine.chemin.parent)
        return {
            "gpu": _etat_gpu(),
            "disque": {"libre_go": round(usage.free / 1e9, 1), "total_go": round(usage.total / 1e9, 1)},
            "essais_en_cours": len(registre.en_cours()),
            "essais_en_file": len(registre.lister(etat="en_file")),
            "battement_actif": battement is not None,
        }

    # -- essais ----------------------------------------------------------

    @app.get("/api/essais")
    def lister(etat: str | None = None, jeu: str | None = None, limite: int = Query(200, ge=1, le=2000)) -> list[dict[str, Any]]:
        return registre.lister(etat=etat, jeu=jeu, limite=limite)

    @app.post("/api/essais", status_code=201)
    def creer(config: ConfigEssai) -> dict[str, str]:
        adapt = obtenir_adaptateur(config.methode.famille)  # famille inconnue : ValueError → 422
        adapt.valider(config.methode)  # réglage inconnu : ValueError → 422
        try:
            Variante(racine.dossier_variante(ident(config.jeu)))
        except VarianteInvalide as exc:
            raise HTTPException(422, f"jeu de données inutilisable : {exc}") from exc
        return {"id": registre.creer_essai(config)}

    @app.get("/api/essais/{essai_id}")
    def detail(essai_id: str) -> dict[str, Any]:
        i = ident(essai_id)
        essai = registre.essai(i)
        dossier = racine.dossier_essai(i)
        erreurs: list[Any] = []
        if (dossier / "erreurs.json").is_file():
            import json

            erreurs = json.loads((dossier / "erreurs.json").read_text(encoding="utf-8"))[:MAX_ERREURS]
        return {
            "essai": essai,
            "resultats": executeur.resultats(i),
            "metriques": _metriques(dossier),
            "erreurs": erreurs,
            "test": {
                "scelle": (dossier / "test_scelle.json").is_file(),
                "consultations": essai["consultations_test"],
            },
        }

    @app.get("/api/essais/{essai_id}/journal")
    def journal(essai_id: str, depuis: int = Query(0, ge=0)) -> dict[str, Any]:
        i = ident(essai_id)
        registre.essai(i)
        texte, suivant = executeur.journal(i, depuis)
        if len(texte) > MAX_JOURNAL:
            texte, suivant = texte[-MAX_JOURNAL:], depuis + len(texte.encode("utf-8", errors="replace"))
        return {"texte": texte, "suivant": suivant}

    @app.get("/api/essais/{essai_id}/evenements")
    def evenements(essai_id: str, depuis: int = 0) -> list[dict[str, Any]]:
        i = ident(essai_id)
        registre.essai(i)
        return registre.evenements(i, depuis)

    @app.post("/api/essais/{essai_id}/arreter")
    def arreter(essai_id: str) -> dict[str, Any]:
        return executeur.arreter(ident(essai_id))

    @app.post("/api/essais/{essai_id}/ouvrir-test")
    def ouvrir_test(essai_id: str, corps: Confirmation = Body(default_factory=Confirmation)) -> dict[str, Any]:
        i = ident(essai_id)
        if not corps.confirmer:
            raise HTTPException(
                428, "Ouvrir le test est une action engageante : il ne sert pas à choisir, et chaque ouverture est comptée. "
                "Rappelez avec {\"confirmer\": true}."
            )
        try:
            return executeur.ouvrir_test(i)
        except FileNotFoundError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/comparer")
    def comparer(ids: str = Query(..., description="identifiants séparés par des virgules (2 à 6)")) -> list[dict[str, Any]]:
        liste = [ident(x.strip()) for x in ids.split(",") if x.strip()]
        if not 2 <= len(liste) <= 6:
            raise HTTPException(422, "comparer 2 à 6 essais")
        sortie = []
        for i in liste:
            essai = registre.essai(i)
            sortie.append({"essai": essai, "resultats": executeur.resultats(i)})
        return sortie

    # -- jeux de données -------------------------------------------------

    @app.get("/api/variantes")
    def variantes() -> list[dict[str, Any]]:
        sortie = []
        if racine.variantes.is_dir():
            for d in sorted(p for p in racine.variantes.iterdir() if p.is_dir()):
                try:
                    v = Variante(d)
                    sortie.append({"id": d.name, "classes": v.classes(), "effectifs": v.effectifs(),
                                   "groupes": {j: len(v.groupes(j)) for j in ("train", "val", "test")}})
                except VarianteInvalide as exc:
                    sortie.append({"id": d.name, "invalide": str(exc)})
        return sortie

    # -- la page ---------------------------------------------------------

    @app.get("/")
    def accueil() -> FileResponse:
        return FileResponse(WEB / "index.html")

    app.mount("/web", StaticFiles(directory=WEB), name="web")
    return app
