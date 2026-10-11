"""Lecture tolérante d'un appel à `gateway_call_tool`.

Dans le journal réel, les modèles se trompent de quatre façons, toujours les
mêmes, et chaque erreur coûte un tour : les arguments envoyés sous forme de
texte JSON, les arguments posés à côté du nom au lieu d'être imbriqués, un
mauvais nom de champ (`tool`, `parameters`, `input`…), et l'appel de
`gateway_call_tool` par lui-même. On comprend ces formes au lieu de les
refuser, et on le dit une fois, pour que l'agent prenne la bonne habitude.

Rien ici n'élargit un périmètre : la cible reste appelée par le même chemin,
donc par les mêmes gardes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

NOMS_DE_CIBLE = ("name", "tool", "tool_name", "toolName")
NOMS_D_ARGUMENTS = ("arguments", "parameters", "params", "input", "args")
_PROFONDEUR_MAX = 2


@dataclass
class AppelLu:
    cible: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    remarques: list[str] = field(default_factory=list)
    erreur: str | None = None


def _objet(valeur: Any) -> dict[str, Any] | None:
    """Un dict, ou le dict qu'un texte JSON contient ; sinon None."""
    if isinstance(valeur, dict):
        return valeur
    if isinstance(valeur, str):
        texte = valeur.strip()
        if texte.startswith("{"):
            try:
                lu = json.loads(texte)
            except ValueError:
                return None
            return lu if isinstance(lu, dict) else None
    return None


def lire_appel(brut: dict[str, Any], *, _profondeur: int = 0) -> AppelLu:
    lu = AppelLu()
    reste = dict(brut)

    for cle in NOMS_DE_CIBLE:
        valeur = reste.pop(cle, None)
        if isinstance(valeur, str) and valeur.strip():
            lu.cible = valeur.strip()
            if cle != "name":
                lu.remarques.append(f"le champ s'appelle `name`, pas `{cle}`")
            break
    if not lu.cible:
        lu.erreur = (
            "Argument 'name' requis : le nom exact de l'outil, tel que "
            "gateway_find_tools le rend. Exemple : "
            '{"name": "atelier_projets", "arguments": {}}.'
        )
        return lu

    args: dict[str, Any] | None = None
    for cle in NOMS_D_ARGUMENTS:
        if cle not in reste:
            continue
        valeur = reste.pop(cle)
        if valeur in (None, ""):
            args = args or {}
            continue
        objet = _objet(valeur)
        if objet is None:
            lu.erreur = (
                f"`{cle}` doit être un objet JSON ({{\"champ\": valeur}}), pas "
                f"{type(valeur).__name__}. Le schéma de l'outil est rendu par "
                "gateway_find_tools."
            )
            return lu
        if isinstance(valeur, str):
            lu.remarques.append("`arguments` est un objet JSON, pas un texte")
        if cle != "arguments":
            lu.remarques.append(f"le champ s'appelle `arguments`, pas `{cle}`")
        args = {**(args or {}), **objet}

    if reste:
        # Les paramètres posés à côté du nom : on les rassemble.
        if args is None or not args:
            args = dict(reste)
            lu.remarques.append(
                "les paramètres vont dans `arguments`, pas à côté de `name`"
            )
        else:
            lu.erreur = (
                "Champs inattendus à côté de `name` et `arguments` : "
                + ", ".join(sorted(reste))
                + ". Mettez-les dans `arguments`."
            )
            return lu

    lu.arguments = args or {}

    if lu.cible == "gateway_call_tool":
        # `gateway_call_tool(name="gateway_call_tool", arguments={name, arguments})`
        if _profondeur >= _PROFONDEUR_MAX or not lu.arguments:
            lu.erreur = (
                "Appel récursif refusé : appelez directement l'outil visé, "
                '{"name": "<outil>", "arguments": {…}}.'
            )
            return lu
        interieur = lire_appel(lu.arguments, _profondeur=_profondeur + 1)
        interieur.remarques = [
            "gateway_call_tool n'est pas à appeler par lui-même",
            *lu.remarques,
            *interieur.remarques,
        ]
        return interieur
    return lu


def rappel(lu: AppelLu) -> str:
    """La ligne de correction ajoutée à la réponse, vide si l'appel était juste."""
    if not lu.remarques:
        return ""
    return (
        "\n\n(Appel compris, mais la forme attendue est "
        '{"name": "<outil>", "arguments": {…}} : '
        + " ; ".join(dict.fromkeys(lu.remarques))
        + ".)"
    )
