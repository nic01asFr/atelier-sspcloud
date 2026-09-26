"""G3, gardien Cohérence : chaque surface donne-t-elle à l'agent ce que dit son profil ?

Le contrôle quotidien `coherence.surfaces` lance le vérificateur de cohérence
(`bin/atelier-verifier-coherence --rapide --json`) : un projet par profil, les
quatre surfaces (app, VS Code, terminal, `bash -lc`), le vrai binaire `claude`
arrêté sitôt `system/init` lu, adresse de modèle morte. Aucun modèle n'est
appelé, aucun jeton consommé (docs/vision/profils-acces.md, « Vérification »).

Chaque écart du rapport devient un constat, donc une alerte de la vue Agents,
qui se ferme d'elle-même quand l'écart disparaît. Rien n'est réparé : un écart
de cohérence se corrige dans le code ou la configuration, par la personne ou
un agent qu'elle charge de le faire.

Le vérificateur tourne dans un processus à part, dans son propre groupe, sous
un plafond de durée (`params.plafond_s`) : au-delà, tout le groupe est tué, et
le contrôle rend une erreur, qui ne ferme aucune alerte.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from mcp_gateway.gardiens.controles.commun import Contexte, constat, resultat

SCRIPT = "atelier-verifier-coherence"
PLAFOND_PAR_DEFAUT_S = 540.0
DELAI_PAR_SURFACE_S = 45.0


def _script(ctx: Contexte) -> Path | None:
    """Le vérificateur du code déployé, sinon la copie de `~/work/bin`."""
    for dossier in (Path(ctx.atelier_src) / "bin", Path(ctx.work) / "bin"):
        chemin = dossier / SCRIPT
        if chemin.is_file():
            return chemin
    return None


def commande(ctx: Contexte, c: Any) -> list[str]:
    script = _script(ctx)
    if script is None:
        return []
    argv = [sys.executable, str(script), "--json",
            "--delai", str(float(c.params.get("delai_par_surface_s", DELAI_PAR_SURFACE_S)))]
    if c.params.get("rapide", True):
        argv.append("--rapide")
    projets = c.params.get("projets")
    if isinstance(projets, list) and projets:
        argv += ["--projets", ",".join(str(p) for p in projets)]
    return argv


def _empreinte(c: Any, dossier: str, ecart: str) -> str:
    return f"{c.id}:{dossier}:{hashlib.sha256(ecart.encode('utf-8')).hexdigest()[:12]}"


def surfaces(ctx: Contexte, c: Any) -> dict[str, Any]:
    """Lance le vérificateur, fait de chaque écart un constat."""
    argv = commande(ctx, c)
    if not argv:
        return {
            "etat": "alerte",
            "erreur": True,
            "constats": [constat(f"{c.id}:introuvable", c.id, "vérificateur de cohérence introuvable",
                                 f"{SCRIPT} absent de {ctx.atelier_src}/bin et de {ctx.work}/bin")],
        }
    plafond = float(c.params.get("plafond_s", PLAFOND_PAR_DEFAUT_S))
    code, sortie = ctx.commande_longue(argv, plafond, str(ctx.work))
    if code == 124:
        return {
            "etat": "alerte",
            "erreur": True,
            "constats": [constat(f"{c.id}:plafond", c.id, f"vérification arrêtée au plafond de {plafond:.0f} s",
                                 "le vérificateur et les `claude` qu'il avait lancés ont été arrêtés")],
        }
    try:
        rapport = json.loads(sortie)
    except (json.JSONDecodeError, TypeError):
        rapport = None
    if code not in (0, 1) or not isinstance(rapport, dict):
        return {
            "etat": "alerte",
            "erreur": True,
            "constats": [constat(f"{c.id}:echec", c.id, "le vérificateur n'a pas rendu de rapport",
                                 f"code {code}")],
        }

    constats = []
    for manque in rapport.get("hooks_introuvables") or []:
        texte = str(manque)
        constats.append(constat(_empreinte(c, "hooks", texte), "hooks", f"hook introuvable : {texte}"[:300]))
    dossiers = [d for d in rapport.get("dossiers") or [] if isinstance(d, dict)]
    for d in dossiers:
        slug = str(d.get("slug") or "?")
        for ecart in d.get("ecarts") or []:
            texte = str(ecart)
            # Un écart que le vérificateur attribue à un chantier en cours
            # (« (équipe A) ») se surveille ; les autres sont des alertes.
            niveau = "attention" if texte.endswith("(équipe A)") else "alerte"
            constats.append(constat(_empreinte(c, slug, texte), f"projet.{slug}",
                                    f"{slug} ({d.get('profil') or '?'}) : {texte}"[:300], "", niveau))
    if rapport.get("ecarts") and not constats:
        # Le compte dit « écart » sans que la liste en donne un : on ne se tait pas.
        constats.append(constat(f"{c.id}:compte", c.id, f"{rapport.get('ecarts')} écart(s) sans détail"))
    return resultat(
        constats,
        dossiers=[f"{d.get('slug')}:{d.get('profil')}" for d in dossiers],
        surfaces=sorted({s for d in dossiers for s in (d.get("surfaces") or {})}),
        version_extension=rapport.get("version_extension") or "",
        ecarts=int(rapport.get("ecarts") or 0),
    )
