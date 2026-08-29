"""Proxy HTTP vers le pilote Wikichat (agents planifiés)."""

from __future__ import annotations

import httpx
from fastapi import HTTPException, Request, Response

from mcp_gateway.atelier.config import AtelierSettings


def wikichat_http_origin(settings: AtelierSettings) -> str:
    raw = (settings.wikichat_url or "http://127.0.0.1:3777/sse").strip().rstrip("/")
    if raw.endswith("/sse"):
        raw = raw[:-4]
    return raw or "http://127.0.0.1:3777"


HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
    }
)


async def proxy_wikichat_pilote(
    request: Request,
    settings: AtelierSettings,
    subpath: str = "",
) -> Response:
    origin = wikichat_http_origin(settings)
    path = "/pilote" + (f"/{subpath}" if subpath else "")
    target = f"{origin}{path}"
    if request.url.query:
        target = f"{target}?{request.url.query}"

    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP
    }
    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            upstream = await client.request(
                request.method,
                target,
                headers=headers,
                content=body if body else None,
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            503,
            f"Wikichat pilote indisponible ({origin}) : {exc}",
        ) from exc

    out_headers = {
        k: v
        for k, v in upstream.headers.items()
        if k.lower() not in HOP_BY_HOP
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=out_headers,
        media_type=upstream.headers.get("content-type"),
    )
