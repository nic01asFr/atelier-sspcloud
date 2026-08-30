from __future__ import annotations

import logging
from typing import Any

import httpx

from mcp_gateway import __version__
from mcp_gateway.upstream.transports import (
    SseMcpSession,
    TransportFerme,
    parse_json_rpc_response,
)

logger = logging.getLogger("mcp_gateway.upstream")

_VERSIONS = ["2025-03-26", "2024-11-05"]


class UpstreamError(Exception):
    pass


class UpstreamClient:
    """Client MCP upstream — Streamable HTTP + fallback HTTP+SSE."""

    def __init__(
        self,
        server_id: str,
        url: str,
        transport: str = "streamable-http",
        auth_header: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ):
        self.server_id = server_id
        self.url = url.rstrip("/")
        self.transport = transport
        self.session_id: str | None = None
        self.tools: list[dict[str, Any]] = []
        self.error: str | None = None
        self._mode: str = transport
        headers: dict[str, str] = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
        if auth_header and "Authorization" not in headers and "authorization" not in headers:
            headers["Authorization"] = (
                auth_header if auth_header.startswith("Bearer ") else f"Bearer {auth_header}"
            )
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0),
            headers=headers,
            follow_redirects=True,
        )
        self._req_id = 0
        self._sse: SseMcpSession | None = None

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _mcp_endpoint(self) -> str:
        if self._mode == "sse":
            if self.url.endswith("/sse"):
                return self.url
            if self.url.endswith("/mcp"):
                return f"{self.url}/sse"
        return self.url

    def _request_headers(self, method: str | None = None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if method:
            headers["Mcp-Method"] = method
        return headers

    @staticmethod
    def _is_modern_json_rpc_error(response: httpx.Response) -> bool:
        if not response.content:
            return False
        ctype = response.headers.get("content-type", "")
        if "json" not in ctype:
            return False
        try:
            body = response.json()
        except Exception:
            return False
        return isinstance(body, dict) and ("error" in body or "jsonrpc" in body)

    async def connect(self) -> bool:
        if self.transport == "sse":
            return await self._connect_sse()

        for version in _VERSIONS:
            if await self._try_streamable_initialize(version):
                return True

        return await self._try_sse_fallback()

    async def _reset_sse(self) -> None:
        if self._sse:
            await self._sse.close()
            self._sse = None

    async def _try_streamable_initialize(self, version: str) -> bool:
        mcp_url = self._mcp_endpoint()
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": version,
                "capabilities": {},
                "clientInfo": {"name": "passerelle", "version": __version__},
            },
        }
        try:
            headers = self._request_headers("initialize" if version == "2025-03-26" else None)
            if version == "2025-03-26":
                headers["MCP-Protocol-Version"] = version
            response = await self._client.post(
                mcp_url,
                json=payload,
                headers=headers,
            )
            if response.status_code in (400, 404, 405) and not self._is_modern_json_rpc_error(
                response
            ):
                return False
            response.raise_for_status()
            self.session_id = response.headers.get("mcp-session-id") or response.headers.get(
                "Mcp-Session-Id"
            )
            data = parse_json_rpc_response(response)
            if data.get("error"):
                self.error = str(data["error"])
                return False
            self._mode = "streamable-http"
            await self._notify_initialized(mcp_url)
            tools = await self._streamable_call(mcp_url, "tools/list", {})
            self.tools = tools.get("tools", [])
            self.error = None
            logger.info(
                "Upstream %s OK (streamable-http) — %d tools",
                self.server_id,
                len(self.tools),
            )
            return True
        except Exception as exc:
            self.error = str(exc)
            logger.warning(
                "Upstream %s streamable init failed (%s): %s",
                self.server_id,
                version,
                exc,
            )
            return False

    async def _try_sse_fallback(self) -> bool:
        try:
            ok = await self._connect_sse()
            if ok:
                logger.info(
                    "Upstream %s OK (sse fallback) — %d tools",
                    self.server_id,
                    len(self.tools),
                )
            return ok
        except Exception as exc:
            self.error = str(exc)
            logger.warning("Upstream %s sse fallback failed: %s", self.server_id, exc)
            return False

    async def _connect_sse(self) -> bool:
        sse_url = self._mcp_endpoint()
        self._sse = SseMcpSession(self._client, sse_url)
        try:
            await self._sse.open()
        except Exception as exc:
            self.error = str(exc)
            await self._reset_sse()
            return False
        self._mode = "sse"

        for version in _VERSIONS:
            payload = {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": version,
                    "capabilities": {},
                    "clientInfo": {"name": "passerelle", "version": __version__},
                },
            }
            try:
                data = await self._sse.post(payload)
                if data.get("error"):
                    continue
                await self._sse.post(
                    {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
                )
                list_data = await self._sse.post(
                    {
                        "jsonrpc": "2.0",
                        "id": self._next_id(),
                        "method": "tools/list",
                        "params": {},
                    }
                )
                self.tools = list_data.get("result", {}).get("tools", [])
                self.error = None
                return True
            except Exception as exc:
                self.error = str(exc)
                logger.warning("Upstream %s sse init failed (%s): %s", self.server_id, version, exc)
        await self._reset_sse()
        return False

    async def _notify_initialized(self, mcp_url: str) -> None:
        payload = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        headers = self._request_headers()
        try:
            response = await self._client.post(
                mcp_url,
                json=payload,
                headers=headers,
                timeout=httpx.Timeout(connect=10.0, read=8.0, write=10.0, pool=10.0),
            )
            if response.status_code not in (200, 202, 204):
                response.raise_for_status()
        except httpx.ReadTimeout:
            # Certains bridges (Passerelle Onyxia) gardent la connexion ouverte sans corps.
            pass

    async def _streamable_call(self, mcp_url: str, method: str, params: dict) -> dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": self._next_id(), "method": method, "params": params}
        headers = self._request_headers()
        response = await self._client.post(mcp_url, json=payload, headers=headers)
        response.raise_for_status()
        data = parse_json_rpc_response(response)
        if data.get("error"):
            raise UpstreamError(str(data["error"]))
        return data.get("result", {})

    async def _sse_call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        data = await self._sse.post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            }
        )
        if data.get("error"):
            raise UpstreamError(str(data["error"]))
        return data.get("result", {})

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._mode == "sse" and self._sse:
            try:
                return await self._sse_call_tool(tool_name, arguments)
            except TransportFerme as exc:
                # Le service d'en face a redémarré. Rouvrir une session et
                # rejouer une fois vaut mieux que remonter une panne à
                # l'utilisateur, qui n'a rien fait de mal et devrait sinon
                # penser à rafraîchir le pool lui-même.
                logger.info("Upstream %s : session perdue (%s) — réouverture", self.server_id, exc)
                await self._reset_sse()
                if not await self._connect_sse():
                    raise UpstreamError(
                        f"{self.server_id} injoignable : {self.error or 'session close'}"
                    ) from exc
                return await self._sse_call_tool(tool_name, arguments)

        mcp_url = self._mcp_endpoint()
        return await self._streamable_call(
            mcp_url,
            "tools/call",
            {"name": tool_name, "arguments": arguments},
        )

    async def close(self) -> None:
        await self._reset_sse()
        await self._client.aclose()
