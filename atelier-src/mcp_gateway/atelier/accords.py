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

Et la section « Secrets » de Réglages, pour **écrire** les valeurs (la fenêtre « Accorder un secret » reste sans valeur : elle ne manipule que des noms) :

- `GET /v1/secrets` : les noms, la date de modification, et quels connecteurs utilisent chaque secret ;
- `PUT /v1/secrets/{nom}` : crée ou change la valeur. Elle part une fois, depuis la session de l'interface, et ne revient jamais : ni dans la réponse, ni au
  journal, ni dans une erreur. Le fichier est écrit en 0600. Les connecteurs qui l'utilisent reçoivent aussitôt la nouvelle valeur ;
- `DELETE /v1/secrets/{nom}` : retire le fichier, sauf si un connecteur l'utilise ;
- tout est réservé à la personne : la clé du propriétaire (que lisent les agents du pod) reçoit 403 ;
- le jeton GitHub (`github_token`) et les secrets de l'Atelier ne s'y écrivent pas : le premier se change dans la section GitHub, les autres sont à l'Atelier.

`enregistrer_les_accords(app)` est la ligne à appeler depuis `api.py`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from mcp_gateway.atelier.apps.secrets import (
    NOMS_DE_L_ATELIER,
    PREFIXES_DE_L_ATELIER,
    reference_valide,
    reserve_a_l_atelier,
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


VALEUR_MAX = 8192


class ValeurDeSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valeur: str


def usages(settings: Any) -> dict[str, list[str]]:
    """Quels connecteurs utilisent quel secret : `{nom_du_secret: [connecteurs]}`, lu dans les accords posés par la personne. Jamais une valeur."""
    from mcp_gateway.db import connect
    from mcp_gateway.registry import list_registry_servers

    sortie: dict[str, list[str]] = {}
    conn = connect(settings.gateway_db_path)
    try:
        for e in list_registry_servers(conn):
            accords = (((e.config or {}).get("_metadata") or {}).get("atelier") or {}).get("accords") or {}
            for accord in accords.values():
                nom = (accord or {}).get("secret")
                if nom and e.server_id not in sortie.setdefault(nom, []):
                    sortie[nom].append(e.server_id)
    finally:
        conn.close()
    return sortie


def _noter(app: Any, action: str, nom: str, resultat: str, **details: Any) -> None:
    """Une ligne au journal unique : qu'un secret a été écrit ou retiré, jamais sa valeur."""
    journal = getattr(app.state, "journal_unique", None)
    if journal is None:
        return
    from mcp_gateway.atelier.commandes.journal import Evenement, nouvel_identifiant

    try:
        journal.ecrire(
            Evenement(
                id=nouvel_identifiant(),
                source="commande",
                acteur="personne",
                objet={"type": "secret", "id": nom},
                action={"commande": action, "origine": "interface", "arguments": details},
                resultat=resultat,
            )
        )
    except OSError:
        pass


def _nom_ecrivable(settings: Any, nom: str) -> None:
    """Refuse ce qu'on n'écrit pas depuis cet écran, en le disant (jamais la valeur)."""
    if not reference_valide(nom):
        raise HTTPException(422, "Nom refusé : des lettres, chiffres, point, tiret ou souligné, sans espace ni « / », 64 caractères au plus.")
    if reserve_a_l_atelier(nom):
        raise HTTPException(403, f"« {nom} » est réservé à l'Atelier : on n'y écrit pas depuis cet écran.")
    if nom == settings.github_token_path.name:
        raise HTTPException(409, "Le jeton GitHub se change dans la section GitHub de Réglages (Déconnecter, puis Connecter).")
    if nom.endswith((".avant", ".tmp", ".bak")) or ".avant-" in nom:
        raise HTTPException(422, "Ce nom est celui d'une copie de sauvegarde : choisissez-en un autre.")


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

    @router.get("/secrets")
    def detail(_: None = Depends(la_personne)) -> dict[str, Any]:
        """Les secrets, avec la date de modification et les connecteurs qui s'en servent. Jamais une valeur."""
        dossier = Path(app.state.settings.secrets_dir)
        utilises = usages(app.state.settings)
        sortie = []
        for ligne in noms_des_secrets(dossier):
            try:
                modifie = datetime.fromtimestamp((dossier / ligne["nom"]).stat().st_mtime, tz=timezone.utc).isoformat()
            except OSError:
                modifie = ""
            sortie.append({**ligne, "modifie": modifie, "utilise_par": sorted(utilises.get(ligne["nom"], []))})
        return {"secrets": sortie, "dossier": str(dossier)}

    @router.put("/secrets/{nom}")
    def ecrire(nom: str, corps: ValeurDeSecret, _: None = Depends(la_personne)) -> dict[str, Any]:
        """Crée ou change un secret. La valeur ne revient jamais ; les connecteurs qui l'utilisent reçoivent la nouvelle."""
        from mcp_gateway.atelier.fournisseurs_gestion import _ecrire

        settings = app.state.settings
        _nom_ecrivable(settings, nom)
        valeur = corps.valeur.strip()
        if not valeur:
            raise HTTPException(422, "La valeur est vide.")
        if len(valeur) > VALEUR_MAX:
            raise HTTPException(422, f"La valeur est trop longue ({VALEUR_MAX} caractères au plus).")
        if any(ord(c) < 32 or ord(c) == 127 for c in valeur):
            raise HTTPException(422, "La valeur tient sur une seule ligne, sans caractère de contrôle (un jeton ne contient ni retour à la ligne ni tabulation).")
        chemin = Path(settings.secrets_dir) / nom
        if chemin.is_symlink() or (chemin.exists() and not chemin.is_file()):
            raise HTTPException(409, f"« {nom} » existe mais n'est pas un fichier ordinaire : on n'y écrit pas.")
        nouveau = not chemin.exists()
        _ecrire(chemin, valeur)
        renouveles: list[str] = []
        renouveler = getattr(app.state, "renouveler_les_secrets", None)
        if renouveler is not None and not nouveau:
            try:
                renouveles = sorted({r["connecteur"] for r in renouveler(secret=nom) if r["etat"] == "renouvele"})
            except Exception as exc:  # noqa: BLE001 — le secret est écrit ; le connecteur se renouvellera à la main
                import logging

                logging.getLogger("atelier.secrets").warning("renouvellement après l'écriture d'un secret : %s", exc)
        _noter(app, "secret_ecrire", nom, "fait", nouveau=nouveau, renouveles=len(renouveles))
        return {"nom": nom, "protege": True, "nouveau": nouveau, "renouveles": renouveles}

    @router.delete("/secrets/{nom}")
    def retirer(nom: str, _: None = Depends(la_personne)) -> dict[str, Any]:
        """Retire un secret, sauf si un connecteur l'utilise : il garderait une copie sans pouvoir la renouveler."""
        settings = app.state.settings
        _nom_ecrivable(settings, nom)
        chemin = Path(settings.secrets_dir) / nom
        if not chemin.exists() or chemin.is_symlink() or not chemin.is_file():
            raise HTTPException(404, f"« {nom} » n'est pas un secret de ce dossier.")
        utilisateurs = usages(settings).get(nom, [])
        if utilisateurs:
            _noter(app, "secret_retirer", nom, "refus", utilise_par=len(utilisateurs))
            raise HTTPException(409, f"« {nom} » est utilisé par {', '.join(sorted(utilisateurs))} : changez d'abord leur secret.")
        chemin.unlink()
        _noter(app, "secret_retirer", nom, "fait")
        return {"nom": nom, "retire": True}

    @router.get("/secrets/noms")
    def lister(_: None = Depends(la_personne)) -> dict[str, Any]:
        return {"noms": noms_des_secrets(app.state.settings.secrets_dir)}

    return router


def enregistrer_les_accords(app: Any) -> None:
    app.include_router(construire_le_routeur(app))


__all__ = ["NOMS_DE_L_ATELIER", "enregistrer_les_accords", "noms_des_secrets"]
