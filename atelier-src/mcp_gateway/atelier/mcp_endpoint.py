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

import logging
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse

from mcp_gateway.auth import bearer_from_header, client_key

log = logging.getLogger("atelier.mcp_endpoint")


def _est_initialize(body: object) -> bool:
    """Vrai si la requête ouvre la session — lot JSON-RPC compris."""
    if isinstance(body, dict):
        return body.get("method") == "initialize"
    if isinstance(body, list):
        return any(isinstance(m, dict) and m.get("method") == "initialize" for m in body)
    return False


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
    """Branche `/mcp` sur la passerelle intégrée, sous la clé propriétaire."""

    def _autoriser(request: Request) -> str:
        # Même garde que le reste du service : la porte MCP n'ouvre pas un
        # accès distinct, elle donne au processus agent ce que l'interface a
        # déjà. Un agent la franchit avec la clé, lue par son helper d'en-têtes.
        return auth.check_token(bearer_from_header(request.headers.get("Authorization")))

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

        resultat = await passerelle.handle_jsonrpc(body, mcp_session_id)
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
