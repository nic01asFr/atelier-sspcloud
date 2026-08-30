from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator
from urllib.parse import urljoin

import httpx

logger = logging.getLogger("mcp_gateway.upstream")


class TransportFerme(RuntimeError):
    """Le flux d'événements est tombé — la session amont n'existe plus.

    Distincte d'une erreur métier : elle ne se remonte pas à l'appelant mais
    demande de rouvrir la session, puis de rejouer l'appel.
    """


@dataclass
class SseEvent:
    event: str = "message"
    data: str = ""


def parse_sse_block(text: str) -> list[SseEvent]:
    """Parse un buffer SSE complet en événements."""
    events: list[SseEvent] = []
    current = SseEvent()
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if line.startswith("event:"):
            current.event = line[6:].strip()
        elif line.startswith("data:"):
            chunk = line[5:]
            if chunk.startswith(" "):
                chunk = chunk[1:]
            current.data = f"{current.data}{chunk}\n" if current.data else chunk
        elif line == "":
            if current.data or current.event != "message":
                if current.data.endswith("\n"):
                    current.data = current.data[:-1]
                events.append(current)
            current = SseEvent()
    if current.data or current.event != "message":
        if current.data.endswith("\n"):
            current.data = current.data[:-1]
        events.append(current)
    return events


def parse_json_rpc_response(response: httpx.Response) -> dict[str, Any]:
    """Extrait la réponse JSON-RPC depuis JSON ou SSE (streamable HTTP)."""
    ctype = response.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        return _json_rpc_from_sse(response.text)
    if response.status_code == 202:
        return {}
    return response.json()


def _json_rpc_from_sse(body: str) -> dict[str, Any]:
    matched: dict[str, Any] = {}
    for evt in parse_sse_block(body):
        if evt.event not in ("message", ""):
            continue
        payload = evt.data.strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if "result" in data or "error" in data:
            matched = data
    return matched


async def iter_sse_events(stream: AsyncIterator[str]) -> AsyncIterator[SseEvent]:
    current = SseEvent()
    async for raw in stream:
        line = raw.rstrip("\r")
        if line.startswith("event:"):
            current.event = line[6:].strip()
        elif line.startswith("data:"):
            chunk = line[5:]
            if chunk.startswith(" "):
                chunk = chunk[1:]
            current.data = f"{current.data}{chunk}\n" if current.data else chunk
        elif line == "":
            if current.data or current.event != "message":
                if current.data.endswith("\n"):
                    current.data = current.data[:-1]
                yield current
            current = SseEvent()
    if current.data or current.event != "message":
        if current.data.endswith("\n"):
            current.data = current.data[:-1]
        yield current


@dataclass
class SseMcpSession:
    """Client HTTP+SSE MCP (spec 2024-11-05)."""

    client: httpx.AsyncClient
    sse_url: str
    message_url: str | None = None
    _pending: dict[int, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)
    _reader_task: asyncio.Task[None] | None = None
    _ready: asyncio.Event = field(default_factory=asyncio.Event)
    _open_error: Exception | None = None
    _sse_cm: Any = None
    _sse_response: httpx.Response | None = None
    ferme: bool = False

    async def open(self) -> None:
        self._sse_cm = self.client.stream(
            "GET",
            self.sse_url,
            headers={"Accept": "text/event-stream", "Cache-Control": "no-cache"},
        )
        self._sse_response = await self._sse_cm.__aenter__()
        self._sse_response.raise_for_status()
        self._reader_task = asyncio.create_task(self._read_stream())
        await asyncio.wait_for(self._ready.wait(), timeout=30.0)
        if self._open_error:
            raise self._open_error
        if not self.message_url:
            raise RuntimeError("Flux SSE terminé sans événement endpoint")

    async def _read_stream(self) -> None:
        assert self._sse_response is not None
        try:
            async for evt in iter_sse_events(self._sse_response.aiter_lines()):
                if evt.event == "endpoint" and not self.message_url:
                    endpoint = evt.data.strip()
                    if not endpoint:
                        self._open_error = RuntimeError("SSE endpoint event vide")
                    else:
                        self.message_url = urljoin(self.sse_url, endpoint)
                    self._ready.set()
                    continue
                if evt.event not in ("message", ""):
                    continue
                payload = evt.data.strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    logger.debug("SSE payload non JSON ignoré: %s", payload[:120])
                    continue
                req_id = data.get("id")
                if req_id is None:
                    continue
                fut = self._pending.pop(req_id, None)
                if fut and not fut.done():
                    fut.set_result(data)
            # Fin normale du flux : le serveur d'en face a fermé, souvent
            # parce qu'il vient de redémarrer. Sans ce traitement, la boucle
            # se terminait en silence — la session paraissait vivante et tout
            # appel suivant expirait au bout d'une minute.
            self._tomber(TransportFerme(f"Flux SSE clos par {self.sse_url}"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Lecteur SSE interrompu (%s): %s", self.sse_url, exc)
            self._tomber(exc)

    def _tomber(self, cause: Exception) -> None:
        """Marque la session morte et libère ce qui l'attendait."""
        self.ferme = True
        self._open_error = cause
        self._ready.set()
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(cause)
        self._pending.clear()

    async def post(self, payload: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
        if self.ferme:
            raise TransportFerme(f"Session SSE close ({self.sse_url})")
        if not self.message_url:
            raise RuntimeError("Session SSE non ouverte")
        req_id = payload.get("id")
        fut: asyncio.Future[dict[str, Any]] | None = None
        if req_id is not None:
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            self._pending[req_id] = fut
        response = await self.client.post(self.message_url, json=payload)
        # Le serveur ne connaît plus cette session : inutile d'attendre une
        # réponse qui ne viendra pas sur un flux qu'il a oublié.
        if response.status_code in (400, 404, 410):
            self._pending.pop(req_id, None)
            self._tomber(TransportFerme(f"Session SSE rejetée ({response.status_code})"))
            raise self._open_error
        if req_id is None:
            response.raise_for_status()
            return {}
        if response.is_success and response.content:
            ctype = response.headers.get("content-type", "")
            if "application/json" in ctype:
                data = response.json()
                pending = self._pending.pop(req_id, None)
                if pending and not pending.done():
                    pending.set_result(data)
        if not fut:
            return {}
        try:
            data = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError as exc:
            self._pending.pop(req_id, None)
            raise TimeoutError(f"Timeout SSE pour requête id={req_id}") from exc
        if data.get("error"):
            raise RuntimeError(str(data["error"]))
        return data

    async def close(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._sse_cm is not None:
            await self._sse_cm.__aexit__(None, None, None)
            self._sse_cm = None
            self._sse_response = None
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
