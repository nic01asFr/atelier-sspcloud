"""Une application amont, vraie, pour éprouver le mandataire de l'hôte des applications.

Lancée par le superviseur comme une application de projet :
`python app_amont.py --port {port}`. Starlette et uvicorn, déjà là pour
l'Atelier. Ses routes montrent ce qui lui arrive et produisent ce que le
mandataire doit transformer :

- `/health` ;
- `/entetes` : les en-têtes reçus, et le chemin vu ;
- `/sse` : trois événements espacés d'une seconde ;
- `/compter` (POST) : lit le corps en flux et rend sa taille ;
- `/cookie` : pose des cookies (Domain, Path, `__Host-`) ;
- `/redirige` : un `Location` vers la racine, un autre vers l'amont lui-même ;
- `/csp` : une CSP à elle, sans `frame-ancestors`, et `Service-Worker-Allowed` ;
- `/ws` : écho texte et binaire, sous-protocole `echo.v1`, fermeture 4001
  sur le message « ferme ».
"""

from __future__ import annotations

import argparse
import asyncio

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

PORT = {"valeur": 0}


async def health(request: Request) -> Response:
    return JSONResponse({"sante": "ok"})


async def entetes(request: Request) -> Response:
    return JSONResponse(
        {"chemin": request.url.path, "requete": request.url.query, "entetes": [[k, v] for k, v in request.headers.items()]}
    )


async def sse(request: Request) -> Response:
    async def flux():
        for i in range(3):
            yield f"data: evenement {i}\n\n".encode()
            await asyncio.sleep(1.0)

    return StreamingResponse(flux(), media_type="text/event-stream")


async def compter(request: Request) -> Response:
    total = 0
    async for morceau in request.stream():
        total += len(morceau)
    return JSONResponse({"octets": total})


async def cookie(request: Request) -> Response:
    r = PlainTextResponse("ok")
    r.raw_headers.append((b"set-cookie", b"simple=1; Path=/; HttpOnly"))
    r.raw_headers.append((b"set-cookie", b"domaine=2; Domain=.lab.sspcloud.fr; Path=/sous"))
    r.raw_headers.append((b"set-cookie", b"__Host-vol=3; Path=/; Secure"))
    r.raw_headers.append((b"set-cookie", b"__Host-atelier_apps=4; Path=/; Secure"))
    return r


async def redirige(request: Request) -> Response:
    if request.query_params.get("vers") == "amont":
        return RedirectResponse(f"http://127.0.0.1:{PORT['valeur']}/health?x=1", 302)
    if request.query_params.get("vers") == "ailleurs":
        return RedirectResponse("https://exemple.org/page", 302)
    return RedirectResponse("/health", 302)


async def csp(request: Request) -> Response:
    return PlainTextResponse(
        "ok",
        headers={"Content-Security-Policy": "default-src 'self'", "Service-Worker-Allowed": "/"},
    )


async def ws(websocket: WebSocket) -> None:
    demandes = websocket.scope.get("subprotocols") or []
    await websocket.accept(subprotocol="echo.v1" if "echo.v1" in demandes else None)
    try:
        while True:
            msg = await websocket.receive()
            if msg["type"] == "websocket.disconnect":
                return
            if msg.get("text") is not None:
                if msg["text"] == "ferme":
                    await websocket.close(code=4001, reason="demande")
                    return
                await websocket.send_text("echo:" + msg["text"])
            elif msg.get("bytes") is not None:
                await websocket.send_bytes(b"echo:" + msg["bytes"])
    except WebSocketDisconnect:
        return


app = Starlette(
    routes=[
        Route("/health", health),
        Route("/entetes", entetes, methods=["GET", "POST"]),
        Route("/sse", sse),
        Route("/compter", compter, methods=["POST"]),
        Route("/cookie", cookie),
        Route("/redirige", redirige),
        Route("/csp", csp),
        WebSocketRoute("/ws", ws),
    ]
)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, required=True)
    a = p.parse_args()
    PORT["valeur"] = a.port
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
