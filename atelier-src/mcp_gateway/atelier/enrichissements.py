"""Ce que l'Atelier sait dire d'un connecteur, au-delà de ce qu'il déclare.

Un serveur MCP annonce des noms techniques et des descriptions écrites pour
un modèle : `search_dataservices`, quatre lignes en anglais. L'interface, elle,
doit présenter un métier à quelqu'un qui découvre le service.

Cet écart, on l'a comblé à la main pour le coordinateur — huit familles et une
trentaine de libellés écrits en dur. Cela vaut pour lui et pour rien d'autre :
un connecteur branché ce matin arrive à plat.

Ce module tient l'enrichissement à part, un fichier par service, lisible et
corrigeable. Ce qu'une main a corrigé n'est jamais réécrit : `revise_par`
vaut « user », et la production automatique s'arrête là — même règle que pour
le titre d'une conversation.

La description d'origine n'est jamais remplacée, seulement complétée. Un
libellé inventé qui trompe est pire qu'un nom technique : celui-là au moins
ne ment pas.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("atelier.enrichissements")

# Ce qu'un outil fait au monde, pour prévenir avant de le cocher.
RISQUES = ("lecture", "ecriture", "destructif")


def dossier(settings: Any) -> Path:
    return Path(settings.work_dir) / ".atelier" / "connecteurs"


def chemin(settings: Any, service: str) -> Path:
    return dossier(settings) / f"{service}.json"


def charger(settings: Any, service: str) -> dict[str, Any]:
    """L'enrichissement d'un service, ou un dictionnaire vide."""
    p = chemin(settings, service)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.info("enrichissement illisible pour %s : %s", service, exc)
        return {}
    return data if isinstance(data, dict) else {}


def enregistrer(settings: Any, service: str, data: dict[str, Any]) -> Path:
    p = chemin(settings, service)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def services_decrits(settings: Any) -> set[str]:
    d = dossier(settings)
    if not d.is_dir():
        return set()
    return {p.stem for p in d.glob("*.json")}


def appliquer_a_outil(outil: dict[str, str], enrichi: dict[str, Any]) -> dict[str, str]:
    """Complète un outil sans jamais effacer ce que le serveur a déclaré.

    `description` reste celle d'origine ; ce que l'enrichissement apporte
    vient à côté, sous des clés qui lui sont propres.
    """
    info = (enrichi.get("outils") or {}).get(outil.get("name", ""))
    if not isinstance(info, dict):
        return outil
    sortie = dict(outil)
    if info.get("libelle"):
        sortie["label"] = str(info["libelle"])
    if info.get("resume"):
        sortie["resume"] = str(info["resume"])
    if info.get("risque") in RISQUES:
        sortie["risque"] = info["risque"]
    hints = info.get("parametres")
    if isinstance(hints, dict) and hints:
        sortie["hints"] = {str(k): str(v) for k, v in hints.items()}
    return sortie


def appliquer_a_service(service: dict[str, Any], enrichi: dict[str, Any]) -> dict[str, Any]:
    """Complète la fiche d'un service et celle de chacun de ses outils."""
    if not enrichi:
        return service
    sortie = dict(service)
    if enrichi.get("libelle"):
        sortie["label"] = str(enrichi["libelle"])
    if enrichi.get("resume"):
        sortie["resume"] = str(enrichi["resume"])
    if enrichi.get("detail"):
        sortie["detail"] = str(enrichi["detail"])
    sortie["tools"] = [appliquer_a_outil(t, enrichi) for t in service.get("tools") or []]
    return sortie


def familles_declarees(enrichi: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    """Regroupements proposés pour un service qui en a trop pour une liste.

    Le format est celui déjà employé pour le coordinateur : un nom de famille,
    les outils qu'elle contient. Un outil absent de toute famille reste à sa
    place plutôt que d'être caché.
    """
    brut = enrichi.get("familles")
    if not isinstance(brut, dict):
        return {}
    sortie: dict[str, tuple[str, ...]] = {}
    for nom, outils in brut.items():
        if isinstance(nom, str) and isinstance(outils, list) and outils:
            sortie[nom] = tuple(str(o) for o in outils)
    return sortie


def revise_a_la_main(enrichi: dict[str, Any]) -> bool:
    return str(enrichi.get("revise_par") or "").strip().lower() == "user"
