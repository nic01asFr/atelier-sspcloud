"""Client HTTP vers le pilote Wikichat (:3777) — backend inchangé, API Atelier au-dessus."""

from __future__ import annotations

from typing import Any

import httpx

from mcp_gateway.atelier.auth import OwnerAuth
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.wikichat_pilote_proxy import wikichat_http_origin


def _auth_headers(settings: AtelierSettings) -> dict[str, str]:
    key = OwnerAuth(settings).owner_key
    return {"Authorization": f"Bearer {key}"}


def _base(settings: AtelierSettings) -> str:
    return wikichat_http_origin(settings)


async def pilote_get(settings: AtelierSettings, path: str) -> Any:
    url = f"{_base(settings)}{path}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url, headers=_auth_headers(settings))
        resp.raise_for_status()
        return resp.json()


async def pilote_post(
    settings: AtelierSettings,
    path: str,
    body: dict[str, Any] | None = None,
) -> Any:
    url = f"{_base(settings)}{path}"
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            url,
            headers={**_auth_headers(settings), "Content-Type": "application/json"},
            json=body or {},
        )
        resp.raise_for_status()
        return resp.json()


async def pilote_delete(settings: AtelierSettings, path: str) -> Any:
    url = f"{_base(settings)}{path}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.delete(url, headers=_auth_headers(settings))
        resp.raise_for_status()
        return resp.json()
