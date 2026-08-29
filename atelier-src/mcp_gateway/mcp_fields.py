"""Champs MCP optionnels relayés depuis outils upstream (sans dépendance mcp.*)."""
from __future__ import annotations

from typing import Any


def upstream_tool_fields(tool: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if tool.get("title"):
        out["title"] = tool["title"]
    if tool.get("annotations"):
        out["annotations"] = tool["annotations"]
    if tool.get("outputSchema"):
        out["outputSchema"] = tool["outputSchema"]
    return out


__all__ = ["upstream_tool_fields"]
