"""Le défaut de mode d'un projet, pour l'interface : `/v1/projets/{slug}/mode`.

Le choix d'une conversation passe par `PATCH /v1/sessions/{id}` ; celui-ci
règle le défaut du projet, écrit dans `.claude/settings.local.json`, que le CLI
résout de lui-même au terminal et dans VS Code (`modes_permission`).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.modes_permission import (
    BYPASS,
    MODES,
    ecrire_mode_du_projet,
    mode_du_projet,
    mode_du_service,
    normaliser,
)

_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ModeDuProjet(BaseModel):
    mode: str = ""


def _dossier(settings: AtelierSettings, slug: str) -> Path:
    if not _SLUG.match(slug) or ".." in slug:
        raise HTTPException(400, "identifiant de projet invalide")
    dossier = settings.projects_dir / slug
    if not dossier.is_dir():
        raise HTTPException(404, "projet inconnu")
    return dossier


def _etat(settings: AtelierSettings, dossier: Path) -> dict[str, Any]:
    propre = mode_du_projet(dossier)
    return {
        "mode": propre,
        "effectif": propre or mode_du_service(settings),
        "source": "projet" if propre else "service",
        "modes": list(MODES),
    }


def register_modes_routes(app: FastAPI, settings: AtelierSettings, auth_dep: Callable[..., Any]) -> None:
    """Monte `GET` et `PUT /v1/projets/{slug}/mode`."""

    @app.get("/v1/projets/{slug}/mode")
    def lire_le_mode_du_projet(slug: str, _owner: str = Depends(auth_dep)) -> dict[str, Any]:
        return _etat(settings, _dossier(settings, slug))

    @app.put("/v1/projets/{slug}/mode")
    def regler_le_mode_du_projet(
        slug: str, corps: ModeDuProjet, _owner: str = Depends(auth_dep)
    ) -> dict[str, Any]:
        dossier = _dossier(settings, slug)
        demande = (corps.mode or "").strip()
        if demande and not normaliser(demande):
            raise HTTPException(400, f"mode inconnu : {demande} ({', '.join(MODES)})")
        ecrire_mode_du_projet(settings, dossier, demande)
        etat = _etat(settings, dossier)
        etat["avertissement"] = (
            "Sans garde-fou : l'agent agit sans rien demander, y compris hors du projet."
            if etat["mode"] == BYPASS
            else ""
        )
        return etat
