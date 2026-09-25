"""G0 : l'inventaire des automates, lu de wikichat et de l'Atelier, en lecture seule.

Rend la liste au schéma « Automate » (`coherence-croisee.md` §1.2) :
`id, genre (controle|entretien|routine|trigger|demon), proprietaire, source,
quand, budget, derniere, prochaine, cout_semaine, etat (actif|coupe|sans_declaration)`.

Ce qui n'est pas déclaré devient `sans_declaration` et un constat :

- un trigger ou une routine wikichat actif sans `budget` (décision J-b : budget
  obligatoire) ;
- un processus qui écoute sur le pod sans être un démon connu ni une création
  lancée par le superviseur.

Rien n'est coupé ici : l'inventaire voit, la personne décide.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp_gateway.gardiens.controles.commun import Contexte, constat, lire_json, resultat
from mcp_gateway.gardiens.declaration import Cron

SEMAINE_S = 7 * 24 * 3600


def _epoch(texte: Any) -> float | None:
    if not isinstance(texte, str) or not texte:
        return None
    try:
        return datetime.fromisoformat(texte.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _iso(t: float | None) -> str | None:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)) if t else None


def _budget(objet: dict[str, Any]) -> dict[str, Any] | None:
    b = objet.get("budget")
    return b if isinstance(b, dict) and b else None


def _proprietaire(objet: dict[str, Any], defaut: str) -> str:
    for cle in ("proprietaire", "owner", "created_by"):
        if isinstance(objet.get(cle), str) and objet[cle]:
            return objet[cle]
    return defaut


def triggers(ctx: Contexte, maintenant: float) -> list[dict[str, Any]]:
    chemin = ctx.wikichat_dir / "triggers.json"
    brut = lire_json(chemin)
    if isinstance(brut, dict) and isinstance(brut.get("triggers"), (list, dict)):
        brut = brut["triggers"]
    elements = list(brut.values()) if isinstance(brut, dict) else (brut if isinstance(brut, list) else [])
    sortie = []
    for t in elements:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        config = t.get("config") if isinstance(t.get("config"), dict) else {}
        genre_t = t.get("type", "?")
        if genre_t == "cron" and config.get("schedule"):
            quand: dict[str, Any] | None = {"cron": config["schedule"], "tz": config.get("tz")}
        elif genre_t == "cron":
            quand = None  # cron sans expression : il ne partira jamais
        else:
            quand = {"evenement": genre_t}
        prochaine = None
        if quand and "cron" in quand and t.get("enabled"):
            try:
                prochaine = Cron(quand["cron"], quand.get("tz")).suivante(maintenant)
            except ValueError:
                prochaine = None
        action = t.get("action") if isinstance(t.get("action"), dict) else {}
        budget = _budget(t)
        if not t.get("enabled"):
            etat = "coupe"
        elif budget is None:
            etat = "sans_declaration"
        else:
            etat = "actif"
        sortie.append(
            {
                "id": f"wikichat.trigger.{t['id']}",
                "genre": "trigger",
                "proprietaire": _proprietaire(t, "wikichat"),
                "source": f"{chemin}#{t['id']}",
                "titre": (t.get("description") or "")[:120],
                "action": action.get("type"),
                "quand": quand,
                "budget": budget,
                "plafond_par_jour": t.get("max_per_day"),
                "lancements": t.get("fire_count"),
                "derniere": t.get("last_fired"),
                "prochaine": _iso(prochaine),
                "cout_semaine": None,
                "etat": etat,
            }
        )
    return sortie


def routines(ctx: Contexte, maintenant: float) -> list[dict[str, Any]]:
    chemin = ctx.wikichat_dir / "routines.json"
    brut = lire_json(chemin)
    if isinstance(brut, dict) and isinstance(brut.get("routines"), (list, dict)):
        brut = brut["routines"]
    elements = list(brut.values()) if isinstance(brut, dict) else (brut if isinstance(brut, list) else [])
    passes: dict[str, int] = {}
    for ligne in _lignes(ctx.wikichat_dir / "routine-runs.jsonl"):
        debut = _epoch(ligne.get("startedAt"))
        if debut and maintenant - debut <= SEMAINE_S:
            passes[str(ligne.get("routineId"))] = passes.get(str(ligne.get("routineId")), 0) + 1
    sortie = []
    for r in elements:
        if not isinstance(r, dict) or not r.get("id"):
            continue
        budget = _budget(r)
        etat = "coupe" if not r.get("enabled", True) else ("actif" if budget else "sans_declaration")
        sortie.append(
            {
                "id": f"wikichat.routine.{r['id']}",
                "genre": "routine",
                "proprietaire": _proprietaire(r, "wikichat"),
                "source": f"{chemin}#{r['id']}",
                "titre": (r.get("description") or "")[:120],
                "etapes": len(r.get("steps") or []),
                "quand": {"par": "trigger"},
                "budget": budget,
                "derniere": r.get("last_run_at"),
                "dernier_resultat": r.get("last_run_status"),
                "prochaine": None,
                "cout_semaine": {"jetons": None, "passes": passes.get(str(r["id"]), 0)},
                "etat": etat,
            }
        )
    return sortie


def _lignes(chemin: Path, maximum: int = 5000) -> list[dict[str, Any]]:
    try:
        with chemin.open(encoding="utf-8") as f:
            lignes = f.readlines()[-maximum:]
    except OSError:
        return []
    sortie = []
    for l in lignes:
        try:
            d = json.loads(l)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict):
            sortie.append(d)
    return sortie


def demons(ctx: Contexte, declares: list[dict[str, Any]], ports_exclus: set[int] = frozenset()) -> list[dict[str, Any]]:
    """Les démons connus (présents ou non), puis tout autre processus qui écoute.

    `ports_exclus` : ceux des créations supervisées, inventoriées à part.
    """
    ecoutes = ctx.ecoutes()
    par_port = {}
    for e in ecoutes:
        par_port.setdefault(e.port, e)
    sortie = []
    ports_connus: set[int] = set()
    for d in declares:
        ports = [int(p) for p in d.get("ports", [])]
        ports_connus.update(ports)
        presents = [par_port[p] for p in ports if p in par_port]
        sortie.append(
            {
                "id": f"demon.{d['id']}",
                "genre": "demon",
                "proprietaire": d.get("proprietaire", "atelier"),
                "source": d.get("source", "install/atelier-init.sh"),
                "titre": d.get("titre", d["id"]),
                "ports": ports,
                "pid": presents[0].pid if presents else None,
                "quand": {"en_continu": True},
                "budget": None,
                "derniere": None,
                "prochaine": None,
                "cout_semaine": None,
                "etat": "actif" if presents else "absent",
            }
        )
    ignores = {int(p) for p in ctx.reglages.get("ports_plateforme", [])} | set(ports_exclus)
    for e in sorted(ecoutes, key=lambda x: x.port):
        if e.port in ports_connus or e.port in ignores or e.port in (0,):
            continue
        # Les ports éphémères des noyaux Jupyter du service (plateforme) sont
        # nombreux et sans intérêt : on ne garde que les commandes qui ne sont
        # pas des noyaux.
        if "ipykernel_launcher" in e.commande and e.adresse in ("127.0.0.1", "::1"):
            continue
        sortie.append(
            {
                "id": f"demon.port-{e.port}",
                "genre": "demon",
                "proprietaire": "?",
                "source": f"écoute {e.adresse}:{e.port}",
                "titre": e.commande[:120],
                "ports": [e.port],
                "pid": e.pid,
                "quand": {"en_continu": True},
                "budget": None,
                "derniere": None,
                "prochaine": None,
                "cout_semaine": None,
                "etat": "sans_declaration",
            }
        )
    return sortie


def creations_supervisees(ctx: Contexte) -> tuple[list[dict[str, Any]], set[int]]:
    """Les créations lancées par le superviseur (`~/work/.atelier-etat/apps.json`)."""
    etat = lire_json(ctx.work / ".atelier-etat" / "apps.json")
    apps = etat.get("apps") if isinstance(etat, dict) else None
    sortie, ports = [], set()
    for cle, a in (apps or {}).items():
        if not isinstance(a, dict):
            continue
        if a.get("port"):
            ports.add(int(a["port"]))
        sortie.append(
            {
                "id": f"creation.{cle}",
                "genre": "demon",
                "proprietaire": f"projet {cle.split('/')[0]}",
                "source": "superviseur des applications",
                "titre": cle,
                "ports": [a["port"]] if a.get("port") else [],
                "pid": a.get("pid"),
                "quand": {"en_continu": True},
                "budget": None,
                "derniere": _iso(a.get("lance_a")),
                "prochaine": None,
                "cout_semaine": None,
                "etat": "actif",
            }
        )
    return sortie, ports


def controles_des_gardiens(ctx: Contexte) -> list[dict[str, Any]]:
    sortie = []
    for c in ctx.etat_executeur():
        sortie.append(
            {
                "id": f"gardiens.{c['id']}",
                "genre": "controle",
                "proprietaire": f"gardien {c.get('gardien')}",
                "source": c.get("source", "gardiens.json"),
                "quand": c.get("quand"),
                "budget": {"jetons_par_jour": 0},
                "derniere": c.get("derniere"),
                "prochaine": c.get("prochaine"),
                "cout_semaine": {"jetons": 0},
                "etat": "actif" if c.get("actif", True) else "coupe",
            }
        )
    return sortie


def inventaire(ctx: Contexte, c: Any) -> dict[str, Any]:
    maintenant = ctx.maintenant()
    liste = controles_des_gardiens(ctx) + triggers(ctx, maintenant) + routines(ctx, maintenant)
    creations, ports_crees = creations_supervisees(ctx)
    liste += creations + demons(ctx, list(ctx.reglages.get("demons_connus", [])), ports_crees)
    constats = []
    for a in liste:
        if a["etat"] == "sans_declaration":
            if a["genre"] == "demon":
                resume = "processus qui écoute sans déclaration"
            else:
                resume = f"{a['genre']} actif sans budget déclaré"
            constats.append(
                constat(
                    f"{c.id}:{a['id']}",
                    a["id"],
                    resume,
                    f"source {a['source']}" + (f", {a.get('lancements')} lancements" if a.get("lancements") else ""),
                    "attention",
                )
            )
    par_etat: dict[str, int] = {}
    for a in liste:
        par_etat[a["etat"]] = par_etat.get(a["etat"], 0) + 1
    # L'absence d'un démon connu n'est pas un constat ici : c'est l'affaire des
    # sondes de santé (G1). L'inventaire dit seulement « absent ».
    return resultat(constats, automates=liste, par_etat=par_etat, lu_a=_iso(maintenant))
