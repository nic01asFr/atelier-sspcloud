"""Le service du laboratoire : une seule interface, pour la page, pour l'agent du projet et pour l'Assistant.

Sécurité :
- le service n'a pas d'authentification propre, il en reçoit une : si `LABO_JETON` est défini, **toute** requête (page comprise) doit le porter,
  en en-tête `Authorization: Bearer …` ou en cookie `labo_jeton` — c'est ce que pose le relais de l'Atelier ;
- hors boucle locale, le service refuse de démarrer sans jeton (voir `__main__`) : un pod du namespace ne l'atteint pas librement ;
- tout identifiant qui devient un nom de dossier passe par `identifiant_sur` ;
- l'ouverture du test est une action engageante : elle exige `{"confirmer": true}` et elle est comptée.
"""

from __future__ import annotations

import asyncio
import csv
import hmac
import json
import shutil
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from laboratoire.adaptateurs import adaptateur as obtenir_adaptateur
from laboratoire.api_commentaires import monter_commentaires
from laboratoire.api_donnees import monter_donnees
from laboratoire.api_profondeur import monter_profondeur
from laboratoire.api_validation import monter_validation
from laboratoire.commentaires.journal import Commentaires
from laboratoire.distant import monter_travail
from laboratoire.executeur import Executeur
from laboratoire.modeles import ConfigEssai
from laboratoire.profondeur.votes import Votes
from laboratoire.projet import Racine, identifiant_sur
from laboratoire.registre import EssaiInconnu, Registre, TransitionRefusee
from laboratoire.travailleur import Travailleur
from laboratoire.validation.journal import Journal
from laboratoire.variante import Variante, VarianteInvalide

WEB = Path(__file__).parent / "web"
MAX_ERREURS = 500
MAX_JOURNAL = 200_000  # octets rendus d'un coup
MAX_CORPS_CONNEXION = 4096
PAUSE_APRES_ECHEC_S = 1.0  # ralentit l'essai de jetons à la chaîne
DUREE_DU_COOKIE_S = 30 * 24 * 3600
# Deux rôles, en plus de l'administrateur (jeton du laboratoire), dans `valideurs.json` — {nom: jeton} ou {nom: {"jeton": …, "role": …}} :
#  - « valideur » (défaut) ne voit que l'écran de validation : pas les essais, ni les données, ni le lancement d'un entraînement ;
#  - « relecteur » lit tout (lecture seule), valide et commente ; il ne lance rien, ne change aucun statut, n'exporte rien.
ROUTES_VALIDEUR = ("/web/", "/api/validation/", "/api/brut/image", "/api/profondeur/paire", "/api/profondeur/votes/", "/api/tache")
ROUTES_RELECTEUR_EN_ECRITURE = ("/api/validation/", "/api/commentaires", "/api/profondeur/paire", "/api/profondeur/votes/")
ROUTES_TRAVAILLEUR = "/api/travail/"  # un travailleur (pod GPU) n'a que celles-ci, et elles ne sont qu'à lui
FENETRE_ACTIVITE_HUMAINE_S = 600  # une personne qui n'a rien fait depuis 10 minutes ne tient plus le pod éveillé

PAGE_DE_CONNEXION = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Laboratoire d'essais — connexion</title>
<style>
:root{color-scheme:light dark;--fond:#f6f7f9;--carte:#fff;--bord:#d9dde3;--texte:#1c2330;--accent:#2354d6;--mal:#b3261e}
@media(prefers-color-scheme:dark){:root{--fond:#11151c;--carte:#1a202a;--bord:#2f3846;--texte:#e6eaf0;--accent:#7ba2ff;--mal:#ff8a80}}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--fond);color:var(--texte);font:15px/1.5 system-ui,sans-serif}
form{background:var(--carte);border:1px solid var(--bord);border-radius:8px;padding:1.5rem;width:min(22rem,90vw)}
h1{font-size:1.2rem;margin:0 0 .75rem}label{font-weight:600}
input{width:100%;box-sizing:border-box;margin:.35rem 0 1rem;padding:.5rem;border:1px solid var(--bord);border-radius:6px;background:var(--fond);color:var(--texte);font:inherit}
button{font:inherit;padding:.5rem 1rem;border-radius:6px;border:0;background:var(--accent);color:#fff;cursor:pointer}
.erreur{color:var(--mal);margin:0 0 .75rem}
</style></head><body>
<form method="post" action="connexion">
<h1>Laboratoire d'essais</h1>
{erreur}<label for="jeton">Jeton d'accès</label>
<input id="jeton" name="jeton" type="password" autocomplete="current-password" required autofocus>
<button type="submit">Entrer</button>
</form></body></html>"""


def _page_de_connexion(erreur: bool = False) -> HTMLResponse:
    message = '<p class="erreur" role="alert">Jeton refusé.</p>' if erreur else ""
    return HTMLResponse(PAGE_DE_CONNEXION.replace("{erreur}", message), status_code=401 if erreur else 200)


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
    battement_humain: Callable[[], Any] | None = None,
    maitre: bool = False,
    tache: str = "classification",
) -> FastAPI:
    """`maitre` : ce laboratoire (pod CPU) ne lance aucun essai, un travailleur distant (pod GPU) prend la file — voir `distant`."""
    registre = Registre(racine.base)
    commentaires = Commentaires(racine.chemin / "donnees" / "commentaires.db")
    votes = Votes(racine.chemin / "donnees" / "votes.db")
    decisions = Journal(racine.chemin / "donnees" / "validation.db")  # (pas « journal » : une route d'essai porte ce nom)
    executeur = Executeur(racine, registre)
    activite = {"derniere": float("-inf")}

    def humain_present() -> bool:
        return time.monotonic() - activite["derniere"] < FENETRE_ACTIVITE_HUMAINE_S

    travailleur = Travailleur(registre, executeur, battement=battement, activite_humaine=humain_present, battement_humain=battement_humain, lancer=not maitre)

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
            decisions.fermer()
            votes.fermer()
            commentaires.fermer()

    app = FastAPI(title="Laboratoire d'essais", lifespan=cycle, docs_url="/api/docs" if jeton is None else None, redoc_url=None, openapi_url=None if jeton else "/api/openapi.json")
    app.state.registre, app.state.executeur, app.state.travailleur, app.state.racine = registre, executeur, travailleur, racine
    app.state.activite_humaine = humain_present
    app.state.tache = tache
    app.state.votes = votes

    def porteurs() -> list[tuple[str, str, str]]:
        """(nom, jeton, rôle) de `valideurs.json`, relu à chaque requête : ajouter ou retirer un porteur ne demande pas de redémarrer."""
        try:
            brut = json.loads((racine.chemin / "valideurs.json").read_text(encoding="utf-8"))
            sortie = []
            for nom, v in brut.items():
                jeton_porteur, role_porteur = (v.get("jeton"), v.get("role", "valideur")) if isinstance(v, dict) else (v, "valideur")
                if jeton_porteur and role_porteur in ("valideur", "relecteur", "travailleur"):
                    sortie.append((str(nom), str(jeton_porteur), role_porteur))
            return sortie
        except (OSError, ValueError, AttributeError):
            return []

    def identifier(fourni: str) -> tuple[str, str] | None:
        """(auteur, rôle) du jeton présenté, ou None."""
        if not fourni:
            return None
        if hmac.compare_digest(fourni.encode(), (jeton or "").encode()):
            return "admin", "admin"
        trouve = [(nom, role_porteur) for nom, j, role_porteur in porteurs() if hmac.compare_digest(fourni.encode(), j.encode())]
        return trouve[0] if trouve else None

    def jeton_valide(fourni: str) -> bool:
        return identifier(fourni) is not None

    @app.middleware("http")
    async def verifier_le_jeton(request: Request, suite):
        chemin = request.url.path
        if jeton and chemin not in ("/sante", "/connexion"):
            presente = request.headers.get("authorization", "")
            fourni = presente[7:] if presente.lower().startswith("bearer ") else request.cookies.get("labo_jeton", "")
            qui = identifier(fourni)
            if qui is None:
                if request.method == "GET" and chemin == "/":
                    return _page_de_connexion()  # un navigateur sans cookie : on lui demande le jeton
                return JSONResponse({"erreur": "jeton absent ou faux"}, status_code=401)
            request.state.auteur, request.state.role = qui
            if qui[1] == "travailleur" and not chemin.startswith(ROUTES_TRAVAILLEUR):
                return JSONResponse({"erreur": "ce jeton ne sert qu'à un travailleur"}, status_code=403)
            if qui[1] in ("valideur", "relecteur") and chemin.startswith(ROUTES_TRAVAILLEUR):
                return JSONResponse({"erreur": "route réservée à un travailleur"}, status_code=403)
            lecture = request.method == "GET" and chemin in ("/", "/api/pod")
            if qui[1] == "valideur" and not lecture and not chemin.startswith(ROUTES_VALIDEUR):
                return JSONResponse({"erreur": "ce jeton ne donne accès qu'à la validation"}, status_code=403)
            if qui[1] == "relecteur" and request.method not in ("GET", "HEAD") and not chemin.startswith(ROUTES_RELECTEUR_EN_ECRITURE):
                return JSONResponse({"erreur": "ce jeton est en lecture seule : il peut commenter et valider, rien d'autre"}, status_code=403)
        else:
            request.state.auteur, request.state.role = "admin", "admin"
        if chemin.startswith(("/api/validation/", "/api/commentaires", "/api/profondeur/paire", "/api/profondeur/votes/")) or chemin == "/api/brut/image":
            activite["derniere"] = time.monotonic()  # quelqu'un valide : le pod doit rester éveillé (voir Travailleur)
        return await suite(request)

    @app.post("/connexion")
    async def connexion(request: Request):
        """Le jeton saisi devient un cookie (HttpOnly, SameSite strict, Secure derrière https) : la page s'ouvre ensuite sans en-tête."""
        if not jeton:
            return RedirectResponse("./", status_code=303)
        corps = (await request.body())[:MAX_CORPS_CONNEXION].decode("utf-8", errors="replace")
        fourni = (parse_qs(corps).get("jeton") or [""])[0]
        if not jeton_valide(fourni):
            await asyncio.sleep(PAUSE_APRES_ECHEC_S)
            return _page_de_connexion(erreur=True)
        https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"
        reponse = RedirectResponse("./#/valider" if (identifier(fourni) or ("", ""))[1] == "valideur" else "./", status_code=303)  # un valideur n'a que cet écran
        reponse.set_cookie("labo_jeton", fourni, max_age=DUREE_DU_COOKIE_S, httponly=True, samesite="strict", secure=https, path="/")
        return reponse

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
        distant = presence["connecte"]()
        return {
            "gpu": presence["gpu"] if (maitre and distant) else (None if maitre else _etat_gpu()),
            "maitre": maitre,
            "travailleur": {"connecte": distant, "nom": presence["nom"], "vu_il_y_a_s": None if presence["vu"] == float("-inf") else round(time.monotonic() - presence["vu"])} if maitre else None,
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

    presence = monter_travail(app, racine, registre, executeur, ident)
    monter_commentaires(app, commentaires)
    monter_profondeur(app, racine, registre, votes, ident)
    brut = monter_donnees(app, racine, ident, decisions)
    monter_validation(app, racine, ident, decisions, brut)

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
