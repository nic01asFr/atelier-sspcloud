"""Les noms des secrets qu'on peut accorder à un connecteur, jamais leurs valeurs.

L'écran des connecteurs propose « Accorder un secret » : la personne choisit un
fichier du dossier des secrets (`~/work/.secrets/`), et la commande réservée
`atelier_connecteur_accorder` (équipe K) le lit côté serveur. Pour choisir, il
faut la liste des noms ; ce module la rend, et rien d'autre :

- `GET /v1/secrets/noms` : `{noms: [{nom, protege}]}`, trié ;
- réservé à la personne (session de l'interface) : la clé du propriétaire,
  que lisent les agents du pod, reçoit 403. Un nom n'est pas une valeur, mais
  la carte de ce qu'on détient n'a pas à circuler ;
- aucun fichier n'est ouvert : on lit le dossier, pas les contenus ;
- les secrets de l'Atelier lui-même (clé du propriétaire, secret interne, clé
  du modèle, fichier d'environnement, script git) ne sont pas proposés : les
  donner à un service tiers le rendrait maître de l'Atelier ;
- `protege` dit si le fichier est fermé aux autres (0600) : sinon la commande
  refusera de le lire, et l'écran le dit avant.

`enregistrer_les_accords(app)` est la ligne à appeler depuis `api.py`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from mcp_gateway.atelier.apps.secrets import (
    NOMS_DE_L_ATELIER,
    PREFIXES_DE_L_ATELIER,
    reference_valide,
)
from mcp_gateway.atelier.auth import ENTETE_INTERFACE
from mcp_gateway.atelier.vscode_bridge import COOKIE_NAME
from mcp_gateway.auth import bearer_from_header


def noms_des_secrets(dossier: Path) -> list[dict[str, Any]]:
    """Les fichiers ordinaires du dossier, au nom valide, hors ceux de l'Atelier."""
    dossier = Path(dossier)
    if not dossier.is_dir():
        return []
    sortie = []
    for chemin in dossier.iterdir():
        nom = chemin.name
        # Les noms connus, et tout ce que l'Atelier range sous son préfixe : une
        # clé qu'il ajouterait demain (celle du lanceur l'a montré) reste à lui.
        if nom in NOMS_DE_L_ATELIER or nom.startswith(PREFIXES_DE_L_ATELIER) or not reference_valide(nom):
            continue
        if nom.endswith((".avant", ".tmp", ".bak")) or ".avant-" in nom:
            continue
        try:
            infos = chemin.lstat()
        except OSError:
            continue
        if chemin.is_symlink() or not chemin.is_file():
            continue
        protege = not (os.name == "posix" and infos.st_mode & 0o077)
        sortie.append({"nom": nom, "protege": protege})
    return sorted(sortie, key=lambda x: x["nom"].lower())


def construire_le_routeur(app: Any) -> APIRouter:
    router = APIRouter(prefix="/v1")

    def la_personne(request: Request, authorization: Annotated[str | None, Header()] = None) -> None:
        genre = app.state.auth.check_api(
            bearer_from_header(authorization),
            request.cookies.get(COOKIE_NAME),
            request.headers.get(ENTETE_INTERFACE) == "1",
        )
        if genre != "session":
            raise HTTPException(403, "la liste des secrets est réservée à la personne, dans l'interface")

    @router.get("/secrets/noms")
    def lister(_: None = Depends(la_personne)) -> dict[str, Any]:
        return {"noms": noms_des_secrets(app.state.settings.secrets_dir)}

    return router


def enregistrer_les_accords(app: Any) -> None:
    app.include_router(construire_le_routeur(app))


__all__ = ["NOMS_DE_L_ATELIER", "enregistrer_les_accords", "noms_des_secrets"]
