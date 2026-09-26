"""Expose la passerelle de l'Atelier en MCP.

L'Atelier fabrique des outils — compositions, variantes aux paramètres figés —
et sait chercher puis appeler n'importe quel outil de son pool. Jusqu'ici ces
capacités ne servaient que l'interface : un agent lancé par l'Atelier ne voyait
que les serveurs déclarés dans le `.mcp.json` de son dossier, et rien de ce
qu'on lui montrait à l'écran ne lui était réellement accessible.

Ce module ferme cet écart. Il ne réimplémente rien : la passerelle intégrée
(`app.state.mcp`) répond déjà au protocole, il lui manquait une porte.
"""

from __future__ import annotations

import secrets

import logging
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from mcp_gateway.auth import (
    bearer_from_header,
    client_key,
    validate_credential as valider,
)
from mcp_gateway.oauth import adresse_publique

log = logging.getLogger("atelier.mcp_endpoint")


def _est_initialize(body: object) -> bool:
    """Vrai si la requête ouvre la session — lot JSON-RPC compris."""
    if isinstance(body, dict):
        return body.get("method") == "initialize"
    if isinstance(body, list):
        return any(isinstance(m, dict) and m.get("method") == "initialize" for m in body)
    return False


def _methodes(body: object) -> list[str]:
    if isinstance(body, dict):
        return [str(body.get("method") or "")]
    if isinstance(body, list):
        return [str(m.get("method") or "") for m in body if isinstance(m, dict)]
    return []


def _magasin(request: Request, passerelle: Any) -> Any:
    """Le magasin des conversations, d'où le profil se déduit."""
    store = getattr(request.app.state, "store", None)
    if store is not None:
        return store
    outils = getattr(getattr(passerelle, "outils_locaux", None), "outils", None)
    return getattr(outils, "store", None)


def _renommer(resultat: object) -> None:
    """Le serveur se présente sous le nom de l'Atelier.

    Le moteur est celui de la passerelle, mais deux passerelles peuvent être
    branchées au même client : les distinguer à l'annonce évite de croire
    qu'on parle à l'autre.
    """
    if not isinstance(resultat, dict):
        return
    info = (resultat.get("result") or {}).get("serverInfo")
    if isinstance(info, dict):
        info["name"] = "atelier"
        info["title"] = "Atelier"


def register_mcp_endpoint(app: FastAPI, auth: Any) -> None:
    """Branche `/mcp` sur la passerelle intégrée.

    Deux porteurs la franchissent : la clé propriétaire, qu'un agent du pod lit
    dans son helper d'en-têtes, et un jeton OAuth émis à un client distant
    après consentement. Ce jeton ne vaut que pour cette porte — il n'ouvre ni
    `/v1`, ni l'interface.
    """

    def _autoriser(request: Request) -> None:
        jeton = bearer_from_header(request.headers.get("Authorization"))
        if valider(request.app.state.db, jeton or "", auth.owner_key):
            return
        # RFC 9728 : un client MCP qui se heurte à un 401 sans cet en-tête n'a
        # aucun moyen de savoir où demander son jeton. Il abandonne, et le
        # branchement reste à faire à la main.
        base = adresse_publique(request)
        raise HTTPException(
            status_code=401,
            detail="unauthorized",
            headers={
                "WWW-Authenticate": (
                    'Bearer realm="atelier", '
                    f'resource_metadata="{base}/.well-known/oauth-protected-resource/mcp"'
                )
            },
        )

    @app.post("/mcp")
    async def mcp_post(
        request: Request,
        mcp_session_id: str | None = Header(default=None, alias="Mcp-Session-Id"),
    ):
        _autoriser(request)
        passerelle = getattr(app.state, "mcp", None)
        if passerelle is None:
            return JSONResponse(
                {"error": "gateway indisponible"},
                status_code=503,
            )
        body = await request.json()

        # Le transport streamable HTTP veut que le serveur attribue
        # l'identifiant de session à l'initialisation ; le client le renvoie
        # ensuite. Sans cela chaque appel ouvre une session neuve, et ce qui
        # tient à la session — le profil retenu — retombe au défaut.
        assigne: str | None = None
        if not mcp_session_id and _est_initialize(body):
            assigne = uuid4().hex
            mcp_session_id = assigne

        bundles = getattr(app.state, "bundles", None)
        if mcp_session_id and bundles is not None:
            cle = client_key(bearer_from_header(request.headers.get("Authorization")))
            bundles.bind_client(mcp_session_id, cle)
            if assigne:
                bundles.restore_for_client(cle, mcp_session_id)

        # Qui appelle : les outils `atelier_artefact*` s'en servent pour ne
        # pas agir sur l'artefact d'une autre conversation. Un en-tête, pas
        # une preuve : c'est une règle de voisinage entre agents du même
        # propriétaire, pas une frontière.
        from mcp_gateway.atelier.outils_conversation import (
            APPEL_INTERACTIF,
            CONVERSATION_APPELANTE,
        )

        from mcp_gateway.atelier.commandes.profils import (
            ENTETE_PROFIL,
            ENTETE_PROJET,
            PROFIL_APPELANT,
            PROJET_ANNONCE,
            noter_un_appel_sans_profil,
            profil_effectif,
        )

        conversation = (request.headers.get("x-atelier-conversation") or "").strip()[:200]
        jeton = CONVERSATION_APPELANTE.set(conversation)
        # Le profil borne ce que la passerelle montre et laisse appeler
        # (`commandes/profils.py`). C'est la conversation qui le décide ;
        # l'en-tête ne peut que restreindre. Sans conversation : tout, comme
        # avant, et on le note.
        annonce = request.headers.get(ENTETE_PROFIL)
        profil = profil_effectif(annonce, conversation, _magasin(request, passerelle))
        if not conversation or not (annonce or "").strip():
            actives = [m for m in _methodes(body) if m in ("initialize", "tools/list", "tools/call")]
            if actives:
                noter_un_appel_sans_profil(conversation, actives[0], profil=profil)
        jeton_profil = PROFIL_APPELANT.set(profil)
        # Le projet annoncé : pour une conversation inconnue, en profil code seulement.
        jeton_projet = PROJET_ANNONCE.set((request.headers.get(ENTETE_PROJET) or "").strip()[:100])
        # La clé du propriétaire est celle des agents du pod et de wikichat :
        # des automates. Un jeton OAuth vient d'un client distant où une
        # personne lit (claude.ai). Voir `atelier_envoyer`, `peut_attendre`.
        presente = bearer_from_header(request.headers.get("Authorization")) or ""
        cle = auth.owner_key or ""
        interactif = APPEL_INTERACTIF.set(
            not (cle and secrets.compare_digest(presente.encode(), cle.encode()))
        )
        try:
            resultat = await passerelle.handle_jsonrpc(body, mcp_session_id)
        finally:
            CONVERSATION_APPELANTE.reset(jeton)
            APPEL_INTERACTIF.reset(interactif)
            PROFIL_APPELANT.reset(jeton_profil)
            PROJET_ANNONCE.reset(jeton_projet)
        _renommer(resultat)
        entetes = {"Mcp-Session-Id": assigne} if assigne else None
        return JSONResponse(content=resultat or {}, headers=entetes)

    @app.delete("/mcp")
    async def mcp_delete(
        request: Request,
        mcp_session_id: str | None = Header(default=None, alias="Mcp-Session-Id"),
    ):
        """Fin de session explicite : libère ce que la session retenait."""
        _autoriser(request)
        if not mcp_session_id:
            return JSONResponse({"error": "missing session"}, status_code=400)
        bundles = getattr(app.state, "bundles", None)
        if bundles is not None:
            bundles.drop(mcp_session_id)
        return Response(status_code=204)
