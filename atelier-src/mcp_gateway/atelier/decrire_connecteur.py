"""Fait décrire un connecteur, pour qu'il soit lisible dans l'Atelier.

Un serveur MCP annonce ce qu'il faut à un modèle : des noms techniques et des
descriptions souvent anglaises, parfois longues de plusieurs lignes. Sur un
écran, il faut autre chose — un intitulé qu'on lit d'un coup d'œil, un
regroupement quand il y a trente outils, une phrase par paramètre.

On l'a écrit à la main pour le coordinateur ; c'est intenable pour chaque
connecteur qu'on branche. Ce module pose la question une fois, au modèle, et
range la réponse dans un fichier qui reste corrigeable.

Ce qui n'est pas demandé : appeler les outils. Les qualifier — lit, écrit,
détruit — se déduit de leur nom et de ce qu'ils annoncent, sans risquer de
déclencher ce qu'on cherchait seulement à comprendre.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp_gateway.atelier.enrichissements import (
    RISQUES,
    charger,
    enregistrer,
    revise_a_la_main,
)
from mcp_gateway.atelier.llm import demander_json

log = logging.getLogger("atelier.decrire")

CONSIGNE = """Tu décris un connecteur pour l'interface d'un atelier de travail, {langue}.

Rends un objet JSON, et rien d'autre, de cette forme :

{
  "libelle": "nom court du service, 2 à 4 mots",
  "resume": "ce qu'il apporte, une phrase",
  "detail": "deux ou trois phrases : ce qu'on peut en faire, ce qu'il faut savoir",
  "familles": {"Nom de famille": ["outil_1", "outil_2"]},
  "outils": {
    "nom_exact_de_l_outil": {
      "libelle": "verbe à l'infinitif, 2 à 5 mots",
      "resume": "une phrase, {langue}",
      "risque": "lecture | ecriture | destructif",
      "parametres": {"nom_du_parametre": "ce qu'on y met, en quelques mots"}
    }
  }
}

Règles :
- Emploie les noms d'outils exactement tels qu'ils te sont donnés.
- Un libellé dit ce que l'outil fait, pas comment il s'appelle.
- « risque » : lecture s'il ne modifie rien, ecriture s'il crée ou met à jour,
  destructif s'il supprime, arrête ou purge.
- « familles » seulement au-delà de huit outils ; chaque outil dans une seule
  famille, et n'invente pas de famille pour un outil isolé.
- « parametres » seulement pour ceux dont le nom ne suffit pas à comprendre.
- N'invente rien : si tu ne sais pas, écris moins."""


def _resume_outils(outils: list[dict[str, Any]]) -> str:
    lignes = []
    for t in outils:
        schema = t.get("schema") or {}
        props = list((schema.get("properties") or {}).keys())
        lignes.append(
            json.dumps(
                {
                    "nom": t.get("name"),
                    "court": t.get("short"),
                    "description": (t.get("description") or "")[:400],
                    "parametres": props[:12],
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(lignes)


def _nettoyer(propose: Any, noms_connus: set[str]) -> dict[str, Any]:
    """Ne retient que ce qui se rapporte à des outils réellement présents.

    Un modèle peut renommer, inventer ou oublier. Ce qui ne correspond à
    rien de connu est écarté sans bruit : mieux vaut un enrichissement
    partiel qu'une description qui parle d'outils absents.
    """
    if not isinstance(propose, dict):
        return {}
    sortie: dict[str, Any] = {}
    for cle in ("libelle", "resume", "detail"):
        if isinstance(propose.get(cle), str) and propose[cle].strip():
            sortie[cle] = propose[cle].strip()

    outils: dict[str, Any] = {}
    for nom, info in (propose.get("outils") or {}).items():
        if nom not in noms_connus or not isinstance(info, dict):
            continue
        garde: dict[str, Any] = {}
        for cle in ("libelle", "resume"):
            if isinstance(info.get(cle), str) and info[cle].strip():
                garde[cle] = info[cle].strip()
        if info.get("risque") in RISQUES:
            garde["risque"] = info["risque"]
        hints = info.get("parametres")
        if isinstance(hints, dict):
            propre = {
                str(k): str(v).strip()
                for k, v in hints.items()
                if isinstance(v, str) and v.strip()
            }
            if propre:
                garde["parametres"] = propre
        if garde:
            outils[nom] = garde
    if outils:
        sortie["outils"] = outils

    familles: dict[str, list[str]] = {}
    for nom, liste in (propose.get("familles") or {}).items():
        if not isinstance(nom, str) or not isinstance(liste, list):
            continue
        retenus = [o for o in liste if o in noms_connus]
        if len(retenus) >= 2:
            familles[nom.strip()] = retenus
    if len(familles) >= 2:
        sortie["familles"] = familles
    return sortie


def decrire(settings: Any, service: str, outils: list[dict[str, Any]]) -> dict[str, Any]:
    """Décrit un service et enregistre le résultat.

    Refuse d'écraser un fichier corrigé à la main : ce que quelqu'un a
    rectifié vaut mieux que ce qu'un modèle reproposerait.
    """
    existant = charger(settings, service)
    if revise_a_la_main(existant):
        raise ValueError(
            f"« {service} » a été corrigé à la main — retirez « revise_par » pour le refaire décrire."
        )
    if not outils:
        raise ValueError(f"aucun outil connu pour « {service} »")

    from mcp_gateway.atelier.ui_settings import consigne_langue

    propose = demander_json(
        settings,
        # Substitution simple : la consigne contient un exemple JSON, dont
        # les accolades ne doivent pas être prises pour des champs à remplir.
        CONSIGNE.replace("{langue}", consigne_langue(settings)),
        f"Connecteur « {service} », {len(outils)} outils :\n\n" + _resume_outils(outils),
        # Décrire trente outils tient dans ce budget ; en dessous, la
        # réponse se coupe au milieu d'un objet JSON.
        max_tokens=16000,
    )
    retenu = _nettoyer(propose, {str(t.get("name")) for t in outils})
    if not retenu:
        raise ValueError("le modèle n'a rien rendu d'exploitable")

    retenu["service"] = service
    retenu["revise_par"] = ""
    enregistrer(settings, service, retenu)
    log.info(
        "connecteur %s décrit : %d outils, %d familles",
        service,
        len(retenu.get("outils") or {}),
        len(retenu.get("familles") or {}),
    )
    return retenu
