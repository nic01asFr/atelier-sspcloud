"""Les routes des notifications : s'inscrire, régler, essayer, répondre.

Cinq routes pour la personne (même porte que le reste de l'interface), et une
pour la notification elle-même, qui ne s'ouvre qu'avec un jeton de décision :
voir `push.py`.
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request

from mcp_gateway.atelier.push import (
    CATEGORIES,
    Notifieur,
    ecrire_les_preferences,
    lire_le_jeton,
    lire_les_preferences,
)


def _identifiant(endpoint: str) -> str:
    """Une forme courte et stable d'un abonnement, pour pouvoir le retirer sans l'exposer."""
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()[:12]


def construire_le_routeur_push(
    app: Any,
    settings: Any,
    require_owner: Callable[..., str],
    trancher: Callable[[str, bool], dict[str, Any]],
) -> tuple[APIRouter, APIRouter]:
    """Rend (routes de la personne, route de la notification).

    `trancher(request_id, accordee)` applique la réponse comme le fait l'écran :
    une seule façon de décider, deux portes.
    """
    personne = APIRouter(prefix="/v1/push")
    notification = APIRouter(prefix="/v1/decisions")

    def notifieur() -> Notifieur:
        return app.state.notifieur

    @personne.get("/etat")
    def etat(_owner: str = Depends(require_owner)) -> dict[str, Any]:
        """Tout ce que l'écran des notifications montre, en un appel."""
        n = notifieur()
        disponible = n.disponible()
        cle_publique = ""
        if disponible:
            try:
                from mcp_gateway.notifications import cles_vapid

                _, cle_publique = cles_vapid(n.db)
            except Exception:  # noqa: BLE001 — sans clés, rien n'est possible : on le dit
                disponible = False
        return {
            "disponible": disponible,
            "cle_publique": cle_publique,
            "appareils": [
                {
                    "id": _identifiant(a["endpoint"]),
                    "appareil": a.get("appareil") or "Appareil sans nom",
                    "depuis": a.get("created_at") or "",
                }
                for a in n.appareils()
            ],
            "preferences": lire_les_preferences(settings),
            "categories": [{"id": nom, "libelle": libelle} for nom, (libelle, _) in CATEGORIES.items()],
        }

    @personne.post("/abonnements", status_code=201)
    async def abonner(request: Request, _owner: str = Depends(require_owner)) -> dict[str, Any]:
        from mcp_gateway.notifications import enregistrer_abonnement

        corps = await request.json()
        abonnement = (corps or {}).get("abonnement") or corps or {}
        cles = abonnement.get("keys") or {}
        if not abonnement.get("endpoint") or not cles.get("p256dh") or not cles.get("auth"):
            raise HTTPException(400, "abonnement incomplet : adresse et clés attendues")
        enregistrer_abonnement(notifieur().db, abonnement, str((corps or {}).get("appareil") or ""))
        return {"enregistre": True}

    @personne.delete("/abonnements")
    async def desabonner(request: Request, _owner: str = Depends(require_owner)) -> dict[str, Any]:
        from mcp_gateway.notifications import oublier_abonnement

        corps = await request.json() or {}
        n = notifieur()
        endpoint = str(corps.get("endpoint") or "")
        if not endpoint and corps.get("id"):
            endpoint = next(
                (a["endpoint"] for a in n.appareils() if _identifiant(a["endpoint"]) == corps["id"]), ""
            )
        return {"oublie": bool(endpoint) and oublier_abonnement(n.db, endpoint)}

    @personne.put("/preferences")
    async def regler(request: Request, _owner: str = Depends(require_owner)) -> dict[str, Any]:
        corps = await request.json()
        if not isinstance(corps, dict):
            raise HTTPException(400, "des préférences attendues")
        return {"preferences": ecrire_les_preferences(settings, corps)}

    @personne.post("/essai")
    def essayer(_owner: str = Depends(require_owner)) -> dict[str, Any]:
        return notifieur().essai()

    @notification.post("/{request_id}/notification")
    async def repondre_depuis_la_notification(request_id: str, request: Request) -> dict[str, Any]:
        """La réponse donnée par un bouton de la notification.

        Pas de cookie ni de clé : seul le jeton compte, et il ne vaut que pour
        **cette** question. Le choix est le seul geste permis.
        """
        corps = await request.json()
        if not isinstance(corps, dict):
            raise HTTPException(400, "jeton et décision attendus")
        if lire_le_jeton(app.state.auth.owner_key, str(corps.get("jeton") or "")) != request_id:
            raise HTTPException(403, "ce jeton ne permet pas de répondre à cette question")
        choix = str(corps.get("decision") or "").strip().lower()
        if choix not in ("allow", "deny"):
            raise HTTPException(400, "decision must be allow or deny")
        return trancher(request_id, choix == "allow")

    return personne, notification
