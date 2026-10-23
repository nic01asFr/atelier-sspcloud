"""Une connexion refusée dit pourquoi : ce que le serveur a répondu, pas seulement « 401 »."""

from __future__ import annotations

import asyncio

import httpx

from mcp_gateway.upstream.client import UpstreamClient, decrire


def _client(gestionnaire) -> UpstreamClient:
    c = UpstreamClient("github-mcp", "https://api.example.test/mcp/", auth_header="ghp_secret")
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(gestionnaire))
    return c


def test_un_401_garde_la_reponse_du_serveur_et_jamais_le_jeton() -> None:
    def refuse(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, text="bad credentials", headers={"www-authenticate": 'Bearer error="invalid_token", error_description="expired"'}
        )

    c = _client(refuse)
    assert asyncio.run(c.connect()) is False
    assert c.error is not None
    assert "401" in c.error and 'error="invalid_token"' in c.error and "bad credentials" in c.error
    assert "ghp_secret" not in c.error
    assert "For more information" not in c.error


def test_une_erreur_sans_reponse_reste_telle_quelle() -> None:
    assert decrire(RuntimeError("boum")) == "boum"
