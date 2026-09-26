"""Ce qui agit seul, vu et piloté depuis la vue Agents (vague 2, équipe V).

Décision J-i (Nicolas, 26/09) : pas de page Gardiens. Les gardiens sont des
agents spécifiques, montrés dans la vue Agents à côté des agents planifiés.
Ce module agrège, côté serveur, ce que la vue affiche :

- `GET /v1/gardiens` : un agent par gardien (santé, sécurité, entretien…),
  avec ses contrôles, ses alertes ouvertes, ses derniers constats, sa
  prochaine échéance et ses gestes récents. Lu à l'API locale de l'exécuteur
  des gardiens (`127.0.0.1:8791`), jamais par le navigateur ; les gestes
  viennent du journal unique, qui survit aux redémarrages de l'exécuteur.
- `GET /v1/automates` : toutes les tâches automatiques dans une seule liste —
  triggers et routines de wikichat, créations servies, gardiens — avec
  dernière exécution, prochaine, plafond et état.
- `POST /v1/automates/action` `{id, geste}` : lancer maintenant, couper,
  réactiver ou activer. Les règles :
  - activer un trigger est réservé à la personne (J-b2) ; un agent peut le
    couper, jamais l'activer ;
  - couper un gardien est réservé à la personne : c'est retirer un filet ;
    le réactiver ou le lancer, non ;
  - chaque geste va au journal unique (`source: automate`), avec son acteur.

Le pilotage des gardiens passe par `POST /pilotage` de leur API locale, avec
le jeton que l'exécuteur écrit à son démarrage
(`~/work/.atelier-etat/gardiens/pilotage.jeton`). Le navigateur ne le voit
jamais : c'est ce module qui relaie.

`enregistrer_les_automates(app)` est la ligne à appeler depuis `api.py`.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from mcp_gateway.atelier.auth import ENTETE_INTERFACE
from mcp_gateway.atelier.vscode_bridge import COOKIE_NAME
from mcp_gateway.auth import bearer_from_header

log = logging.getLogger("atelier.automates")

PORT_DES_GARDIENS = 8791
FICHIER_DU_JETON = "pilotage.jeton"
# L'ordre d'affichage ; un gardien sans contrôle déclaré n'apparaît pas.
ORDRE_DES_GARDIENS = ("sante", "securite", "coherence", "entretien")
_GRAVITE = {"ok": 0, "attention": 1, "alerte": 2}

GESTES_GARDIEN = ("lancer", "couper", "reactiver")
GESTES_TRIGGER = ("lancer", "couper", "activer")


class ErreurDePilotage(Exception):
    def __init__(self, statut: int, message: str) -> None:
        super().__init__(message)
        self.statut = statut
        self.message = message


class LecteurGardiens:
    """L'API locale de l'exécuteur des gardiens : lecture, et pilotage par jeton."""

    def __init__(self, base: str, dossier_du_jeton: Path, *, delai: float = 3.0) -> None:
        self.base = base.rstrip("/")
        self.dossier_du_jeton = Path(dossier_du_jeton)
        self.delai = delai

    @classmethod
    def depuis_reglages(cls, settings: Any) -> "LecteurGardiens":
        port = int(os.environ.get("ATELIER_GARDIENS_PORT") or PORT_DES_GARDIENS)
        return cls(
            f"http://127.0.0.1:{port}",
            Path(settings.work_dir) / ".atelier-etat" / "gardiens",
        )

    def _client(self) -> httpx.AsyncClient:
        # Boucle locale, en clair : ni certificats à charger (une demi-seconde
        # par client), ni mandataire de l'environnement à traverser.
        return httpx.AsyncClient(timeout=self.delai, verify=False, trust_env=False)

    async def lire(self, chemin: str) -> dict[str, Any] | None:
        """Le JSON d'une route de lecture, ou None si l'exécuteur ne répond pas."""
        try:
            async with self._client() as client:
                r = await client.get(self.base + chemin)
        except httpx.HTTPError:
            return None
        if r.status_code != 200:
            return None
        try:
            corps = r.json()
        except ValueError:
            return None
        return corps if isinstance(corps, dict) else None

    def jeton(self) -> str:
        try:
            return (self.dossier_du_jeton / FICHIER_DU_JETON).read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    async def piloter(
        self, action: str, *, gardien: str | None = None, controle: str | None = None, par: str = ""
    ) -> dict[str, Any]:
        jeton = self.jeton()
        if not jeton:
            raise ErreurDePilotage(503, "l'exécuteur des gardiens n'a pas ouvert son pilotage")
        corps: dict[str, Any] = {"action": action, "par": par}
        if controle:
            corps["controle"] = controle
        elif gardien:
            corps["gardien"] = gardien
        try:
            async with self._client() as client:
                r = await client.post(
                    self.base + "/pilotage", json=corps, headers={"Authorization": f"Bearer {jeton}"}
                )
        except httpx.HTTPError as exc:
            raise ErreurDePilotage(503, f"l'exécuteur des gardiens ne répond pas ({type(exc).__name__})") from None
        try:
            reponse = r.json()
        except ValueError:
            reponse = {}
        if r.status_code != 200:
            raise ErreurDePilotage(r.status_code if r.status_code in (400, 404) else 502,
                                   str((reponse or {}).get("erreur") or f"refus {r.status_code}"))
        return reponse


# ── Les gardiens, un agent chacun ─────────────────────────────────────────


def _pire(etats: list[str]) -> str:
    connus = [e for e in etats if e in _GRAVITE]
    if not connus:
        return "inconnu"
    return max(connus, key=lambda e: _GRAVITE[e])


def _gestes_des_gardiens(journal: Any, limite: int = 200) -> list[dict[str, Any]]:
    """Les gestes des gardiens, du journal unique : ils survivent à un redémarrage."""
    if journal is None:
        return []
    try:
        evenements = journal.lire(source="geste", acteur="gardiens", limite=limite)
    except Exception:  # noqa: BLE001 — un journal illisible ne doit pas vider la vue
        return []
    sortie = []
    for e in evenements:
        action = e.get("action") if isinstance(e.get("action"), dict) else {}
        sortie.append(
            {
                "quand": e.get("quand"),
                "gardien": action.get("origine"),
                "nom": action.get("commande"),
                "avant": action.get("avant"),
                "apres": action.get("apres"),
                "resultat": e.get("resultat"),
            }
        )
    return sortie


def assembler_les_gardiens(
    etat: dict[str, Any], lignes: list[dict[str, Any]], gestes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Regroupe contrôles, alertes, constats et gestes par gardien.

    `etat` est la réponse de `/etat`, `lignes` celle de `/resultats` (de la plus
    ancienne à la plus récente), `gestes` ceux du journal unique.
    """
    controles = [c for c in etat.get("controles") or [] if isinstance(c, dict)]
    alertes = [a for a in etat.get("alertes_ouvertes") or [] if isinstance(a, dict)]
    derniere_ligne: dict[str, dict[str, Any]] = {}
    for ligne in lignes:
        if isinstance(ligne, dict) and ligne.get("controle"):
            derniere_ligne[str(ligne["controle"])] = ligne

    par_gardien: dict[str, list[dict[str, Any]]] = {}
    for c in controles:
        par_gardien.setdefault(str(c.get("gardien") or "?"), []).append(c)
    noms = [g for g in ORDRE_DES_GARDIENS if g in par_gardien] + sorted(
        g for g in par_gardien if g not in ORDRE_DES_GARDIENS
    )

    sortie = []
    for g in noms:
        liste = par_gardien[g]
        actifs = [c for c in liste if c.get("actif", True)]
        coupes = [c for c in liste if c.get("coupe")]
        ouvertes = [a for a in alertes if a.get("gardien") == g]
        constats = []
        for c in liste:
            ligne = derniere_ligne.get(str(c.get("id")))
            if not ligne:
                continue
            for x in ligne.get("constats") or []:
                if isinstance(x, dict):
                    constats.append({**x, "controle": c.get("id"), "quand": ligne.get("quand")})
        prochaines = sorted(str(c["prochaine"]) for c in actifs if c.get("prochaine"))
        dernieres = sorted(str(c["derniere"]) for c in liste if c.get("derniere"))
        if liste and not actifs:
            etat_gardien = "coupe"
        else:
            etat_gardien = _pire([str(c.get("etat")) for c in actifs if c.get("etat")])
            if ouvertes:
                etat_gardien = _pire([etat_gardien, *[str(a.get("niveau")) for a in ouvertes]])
        sortie.append(
            {
                "id": g,
                "etat": etat_gardien,
                "controles": [
                    {
                        "id": c.get("id"),
                        "quand": c.get("quand"),
                        "derniere": c.get("derniere"),
                        "prochaine": c.get("prochaine"),
                        "etat": c.get("etat"),
                        "actif": c.get("actif", True),
                        "actif_declare": c.get("actif_declare", c.get("actif", True)),
                        "coupe": c.get("coupe"),
                        "en_cours": bool(c.get("en_cours")),
                        "echecs_consecutifs": c.get("echecs_consecutifs") or 0,
                        "geste": c.get("geste"),
                    }
                    for c in liste
                ],
                "alertes": ouvertes,
                "constats": constats,
                "derniere": dernieres[-1] if dernieres else None,
                "prochaine": prochaines[0] if prochaines else None,
                "gestes": [x for x in gestes if x.get("gardien") == g][:10],
                "actions": {
                    "lancer": bool(actifs),
                    "couper": bool(actifs),
                    "reactiver": bool(coupes),
                },
            }
        )
    return sortie


async def vue_des_gardiens(lecteur: LecteurGardiens, journal: Any) -> dict[str, Any]:
    etat = await lecteur.lire("/etat")
    if etat is None:
        return {
            "joignable": False,
            "gardiens": [],
            "note": "Les gardiens ne répondent pas : leur exécuteur est arrêté ou pas encore démarré.",
        }
    resultats = await lecteur.lire("/resultats?n=500") or {}
    gardiens = assembler_les_gardiens(etat, resultats.get("lignes") or [], _gestes_des_gardiens(journal))
    return {"joignable": True, "gardiens": gardiens, "interrupteurs": etat.get("interrupteurs") or {}}


# ── Toutes les tâches automatiques, une seule liste ───────────────────────


def _triggers(inventaire: list[dict[str, Any]], pilote: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Triggers de wikichat : l'inventaire des gardiens et le pilote, fusionnés par id."""
    par_id: dict[str, dict[str, Any]] = {}
    for a in inventaire:
        if a.get("genre") != "trigger":
            continue
        ident = str(a.get("id") or "").removeprefix("wikichat.trigger.")
        if not ident:
            continue
        quand = a.get("quand") if isinstance(a.get("quand"), dict) else {}
        par_id[ident] = {
            "id": f"trigger.{ident}",
            "genre": "trigger",
            "titre": a.get("titre") or ident,
            "proprietaire": a.get("proprietaire") or "wikichat",
            "derniere": a.get("derniere"),
            "prochaine": a.get("prochaine"),
            "plafond": {"par_jour": a.get("plafond_par_jour"), "budget": a.get("budget")},
            "etat": a.get("etat") or "actif",
            "active": a.get("etat") != "coupe",
            "detail": {"quand": quand, "lancements": a.get("lancements"), "action": a.get("action")},
        }
    if isinstance(pilote, dict):
        for agent in pilote.get("agents") or []:
            if not isinstance(agent, dict) or not agent.get("id"):
                continue
            ident = str(agent["id"])
            fiche = par_id.setdefault(
                ident,
                {
                    "id": f"trigger.{ident}",
                    "genre": "trigger",
                    "proprietaire": "wikichat",
                    "prochaine": None,
                    "plafond": {"par_jour": None, "budget": None},
                    "detail": {"quand": {"cron": agent.get("cron")}},
                },
            )
            fiche["titre"] = agent.get("name") or fiche.get("titre") or ident
            fiche["agent"] = True
            fiche["active"] = bool(agent.get("enabled"))
            fiche["derniere"] = agent.get("lastFired") or fiche.get("derniere")
            fiche["prochaine_texte"] = agent.get("next")
            cap = (agent.get("trigger") or {}).get("cap") if isinstance(agent.get("trigger"), dict) else None
            if cap not in (None, "", "—") and not (fiche.get("plafond") or {}).get("par_jour"):
                try:
                    fiche.setdefault("plafond", {})["par_jour"] = int(cap)
                except (TypeError, ValueError):
                    pass
        for s in pilote.get("system_agents") or []:
            if not isinstance(s, dict) or not s.get("id"):
                continue
            ident = str(s["id"])
            fiche = par_id.setdefault(
                ident,
                {
                    "id": f"trigger.{ident}",
                    "genre": "trigger",
                    "proprietaire": "plateforme",
                    "prochaine": None,
                    "plafond": {"par_jour": None, "budget": None},
                    "detail": {"quand": {"evenement": s.get("type")}},
                },
            )
            fiche["titre"] = s.get("name") or fiche.get("titre") or ident
            fiche["active"] = bool(s.get("enabled"))
            fiche["derniere"] = s.get("lastFired") or fiche.get("derniere")
    for fiche in par_id.values():
        if not fiche.get("active", True):
            fiche["etat"] = "coupe"
        elif fiche.get("etat") in (None, "", "coupe"):
            fiche["etat"] = "actif"
        fiche["gestes"] = ["lancer", "couper"] if fiche.get("active", True) else ["activer"]
    return sorted(par_id.values(), key=lambda f: str(f.get("titre") or "").lower())


def _routines(inventaire: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sortie = []
    for a in inventaire:
        if a.get("genre") != "routine":
            continue
        ident = str(a.get("id") or "").removeprefix("wikichat.routine.")
        sortie.append(
            {
                "id": f"routine.{ident}",
                "genre": "routine",
                "titre": a.get("titre") or ident,
                "proprietaire": a.get("proprietaire") or "wikichat",
                "derniere": a.get("derniere"),
                "prochaine": None,
                "plafond": {"budget": a.get("budget")},
                "etat": a.get("etat") or "actif",
                "detail": {
                    "etapes": a.get("etapes"),
                    "dernier_resultat": a.get("dernier_resultat"),
                    "passes_semaine": (a.get("cout_semaine") or {}).get("passes"),
                },
                "gestes": [],
            }
        )
    return sortie


_ETATS_CREATION = {"pret": "actif", "demarrage": "actif", "redemarrage": "actif", "arrete": "coupe",
                   "arret": "coupe", "en_echec": "en_echec"}


def _creations(apps: Any, inventaire: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Les créations servies, lues au superviseur de l'Atelier (à défaut, à l'inventaire)."""
    superviseur = getattr(apps, "superviseur", None) if apps is not None else None
    sortie = []
    if superviseur is not None:
        try:
            infos = superviseur.lister()
        except Exception:  # noqa: BLE001
            infos = []
        for info in infos:
            d = info.en_dict() if hasattr(info, "en_dict") else dict(info)
            sortie.append(
                {
                    "id": f"creation.{d.get('slug')}/{d.get('nom')}",
                    "genre": "creation",
                    "titre": d.get("nom"),
                    "proprietaire": f"projet {d.get('slug')}",
                    "projet": d.get("slug"),
                    "derniere": None,
                    "prochaine": None,
                    "plafond": {
                        "redemarrages": getattr(superviseur, "redemarrages_max", None),
                        "fenetre_min": int(getattr(superviseur, "fenetre_redemarrages_s", 0) // 60) or None,
                        "recents": d.get("redemarrages_recents"),
                    },
                    "etat": _ETATS_CREATION.get(str(d.get("etat")), str(d.get("etat") or "inconnu")),
                    "detail": {"raison": d.get("raison")},
                    "gestes": [],
                }
            )
        return sortie
    for a in inventaire:
        if not str(a.get("id") or "").startswith("creation."):
            continue
        cle = str(a["id"]).removeprefix("creation.")
        slug, _, nom = cle.partition("/")
        sortie.append(
            {
                "id": f"creation.{cle}",
                "genre": "creation",
                "titre": nom or cle,
                "proprietaire": f"projet {slug}",
                "projet": slug,
                "derniere": a.get("derniere"),
                "prochaine": None,
                "plafond": {},
                "etat": a.get("etat") or "actif",
                "detail": {},
                "gestes": [],
            }
        )
    return sortie


def _gardiens_comme_automates(vue: dict[str, Any]) -> list[dict[str, Any]]:
    sortie = []
    for g in vue.get("gardiens") or []:
        gestes = [n for n in GESTES_GARDIEN if (g.get("actions") or {}).get(n)]
        sortie.append(
            {
                "id": f"gardien.{g['id']}",
                "genre": "gardien",
                "titre": g["id"],
                "proprietaire": "Atelier",
                "derniere": g.get("derniere"),
                "prochaine": g.get("prochaine"),
                "plafond": {"jetons": 0},
                "etat": g.get("etat"),
                "detail": {"alertes": len(g.get("alertes") or []), "controles": len(g.get("controles") or [])},
                "gestes": gestes,
            }
        )
    return sortie


async def liste_des_automates(
    lecteur: LecteurGardiens, journal: Any, apps: Any, pilote: dict[str, Any] | None, pilote_note: str = ""
) -> dict[str, Any]:
    vue = await vue_des_gardiens(lecteur, journal)
    inventaire_brut = await lecteur.lire("/automates") if vue.get("joignable") else None
    inventaire = [a for a in (inventaire_brut or {}).get("automates") or [] if isinstance(a, dict)]
    notes = []
    if not vue.get("joignable"):
        notes.append(vue.get("note"))
    elif inventaire_brut is None:
        notes.append("L'inventaire des gardiens n'a pas encore tourné : les routines n'apparaissent qu'après lui.")
    if pilote_note:
        notes.append(pilote_note)
    automates = (
        _gardiens_comme_automates(vue)
        + _triggers(inventaire, pilote)
        + _routines(inventaire)
        + _creations(apps, inventaire)
    )
    return {
        "automates": automates,
        "sources": {
            "gardiens": bool(vue.get("joignable")),
            "inventaire": inventaire_brut is not None,
            "pilote": pilote is not None,
        },
        "notes": [n for n in notes if n],
    }


# ── Routes ────────────────────────────────────────────────────────────────


class CorpsGeste(BaseModel):
    id: str
    geste: str


def _journaliser(journal: Any, *, acteur: str, origine: str, objet: dict[str, Any], geste: str,
                 avant: Any, apres: Any, resultat: str) -> None:
    if journal is None:
        return
    try:
        from mcp_gateway.atelier.commandes.journal import Evenement

        journal.ecrire(
            Evenement(
                source="automate",
                acteur=acteur,
                objet=objet,
                action={"commande": f"automate_{geste}", "origine": origine, "avant": avant, "apres": apres},
                resultat=resultat,
            )
        )
    except Exception:  # noqa: BLE001 — le journal ne doit pas faire échouer le geste
        log.exception("geste %s non journalisé", geste)


async def _pilote(app: Any, methode: str, chemin: str) -> Any:
    from mcp_gateway.atelier.pilote_client import pilote_get, pilote_post

    settings = app.state.settings
    if methode == "GET":
        return await pilote_get(settings, chemin)
    return await pilote_post(settings, chemin, {})


def construire_le_routeur(app: Any) -> APIRouter:
    router = APIRouter(prefix="/v1")

    def qui(request: Request, authorization: Annotated[str | None, Header()] = None) -> str:
        """`personne` (session de l'interface) ou `cle-proprietaire` (agents du pod)."""
        genre = app.state.auth.check_api(
            bearer_from_header(authorization),
            request.cookies.get(COOKIE_NAME),
            request.headers.get(ENTETE_INTERFACE) == "1",
        )
        return "personne" if genre == "session" else "cle-proprietaire"

    def lecteur() -> LecteurGardiens:
        return app.state.lecteur_gardiens

    def journal() -> Any:
        return getattr(app.state, "journal_unique", None)

    async def lire_le_pilote() -> tuple[dict[str, Any] | None, str]:
        if getattr(app.state, "use_fake", False):
            return None, "Le pilote de wikichat n'est pas branché ici (mode factice)."
        try:
            donnees = await _pilote(app, "GET", "/pilote/api/data")
        except Exception as exc:  # noqa: BLE001
            return None, f"Le pilote de wikichat ne répond pas ({type(exc).__name__})."
        return (donnees if isinstance(donnees, dict) else None), ""

    @router.get("/gardiens")
    async def gardiens(_qui: str = Depends(qui)) -> dict[str, Any]:
        return await vue_des_gardiens(lecteur(), journal())

    @router.get("/automates")
    async def automates(_qui: str = Depends(qui)) -> dict[str, Any]:
        pilote, note = await lire_le_pilote()
        return await liste_des_automates(lecteur(), journal(), getattr(app.state, "apps", None), pilote, note)

    @router.post("/automates/action")
    async def geste(corps: CorpsGeste, acteur: str = Depends(qui)) -> dict[str, Any]:
        ident = corps.id.strip()
        nom = corps.geste.strip().lower()
        origine = "interface" if acteur == "personne" else "cle"
        genre, _, cible = ident.partition(".")
        if not cible:
            raise HTTPException(422, "id : gardien.<nom>, controle.<id> ou trigger.<id>")

        if genre in ("gardien", "controle"):
            if nom not in GESTES_GARDIEN:
                raise HTTPException(422, f"geste : {', '.join(GESTES_GARDIEN)}")
            objet = {"type": "gardien" if genre == "gardien" else "controle", "id": cible}
            if nom == "couper" and acteur != "personne":
                _journaliser(journal(), acteur=acteur, origine=origine, objet=objet, geste=nom,
                             avant=None, apres=None, resultat="refus")
                raise HTTPException(403, "couper un gardien est réservé à la personne")
            try:
                retour = await lecteur().piloter(
                    nom,
                    gardien=cible if genre == "gardien" else None,
                    controle=cible if genre == "controle" else None,
                    par=acteur,
                )
            except ErreurDePilotage as exc:
                _journaliser(journal(), acteur=acteur, origine=origine, objet=objet, geste=nom,
                             avant=None, apres={"erreur": exc.message}, resultat="erreur")
                raise HTTPException(exc.statut, exc.message) from None
            touches = retour.get("controles") or []
            _journaliser(journal(), acteur=acteur, origine=origine, objet=objet, geste=nom,
                         avant=None, apres={"controles": touches}, resultat="fait")
            return {"id": ident, "geste": nom, "controles": touches}

        if genre == "trigger":
            if nom not in GESTES_TRIGGER:
                raise HTTPException(422, f"geste : {', '.join(GESTES_TRIGGER)}")
            objet = {"type": "tache", "id": cible}
            if nom == "activer" and acteur != "personne":
                # J-b2 : un agent coupe un trigger, il ne l'active jamais.
                _journaliser(journal(), acteur=acteur, origine=origine, objet=objet, geste=nom,
                             avant=None, apres=None, resultat="refus")
                raise HTTPException(403, "activer une tâche automatique est réservé à la personne")
            if getattr(app.state, "use_fake", False):
                raise HTTPException(503, "le pilote de wikichat n'est pas branché ici (mode factice)")
            from urllib.parse import quote

            chemin = f"/pilote/api/agent/{quote(cible, safe='')}"
            if nom == "lancer":
                try:
                    retour = await _pilote(app, "POST", chemin + "/fire")
                except Exception as exc:  # noqa: BLE001
                    raise HTTPException(502, f"pilote : {type(exc).__name__}") from None
                _journaliser(journal(), acteur=acteur, origine=origine, objet=objet, geste=nom,
                             avant=None, apres=None, resultat="fait")
                return {"id": ident, "geste": nom, "pilote": retour}
            # Couper et activer : le pilote ne sait que basculer. On lit l'état
            # d'abord, pour qu'un double clic ne rallume pas ce qu'on coupait.
            pilote, note = await lire_le_pilote()
            if pilote is None:
                raise HTTPException(503, note)
            actuel = None
            for a in list(pilote.get("agents") or []) + list(pilote.get("system_agents") or []):
                if isinstance(a, dict) and str(a.get("id")) == cible:
                    actuel = bool(a.get("enabled"))
            if actuel is None:
                raise HTTPException(404, f"tâche automatique inconnue : {cible}")
            voulu = nom == "activer"
            if actuel == voulu:
                return {"id": ident, "geste": nom, "active": actuel, "deja": True}
            try:
                retour = await _pilote(app, "POST", chemin + "/toggle")
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(502, f"pilote : {type(exc).__name__}") from None
            _journaliser(journal(), acteur=acteur, origine=origine, objet=objet, geste=nom,
                         avant={"active": actuel}, apres={"active": voulu}, resultat="fait")
            return {"id": ident, "geste": nom, "active": voulu, "pilote": retour}

        raise HTTPException(422, "seuls les gardiens et les tâches automatiques se pilotent ici")

    return router


def enregistrer_les_automates(app: Any) -> None:
    """La ligne que `api.py` appelle : le lecteur des gardiens et les routes."""
    if not hasattr(app.state, "lecteur_gardiens"):
        app.state.lecteur_gardiens = LecteurGardiens.depuis_reglages(app.state.settings)
    app.include_router(construire_le_routeur(app))


__all__ = [
    "ErreurDePilotage",
    "LecteurGardiens",
    "assembler_les_gardiens",
    "enregistrer_les_automates",
    "liste_des_automates",
    "vue_des_gardiens",
]
