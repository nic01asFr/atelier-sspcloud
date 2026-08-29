"""Suivi des changements du pool tools/list (MCP listChanged)."""
from __future__ import annotations

from typing import Any


class ToolsChangeTracker:
    def __init__(self) -> None:
        self._revision = 0

    @property
    def revision(self) -> int:
        return self._revision

    def bump(self) -> int:
        self._revision += 1
        return self._revision


def bump_tools_revision(app: Any) -> int:
    tracker: ToolsChangeTracker | None = getattr(app.state, "tools_change_tracker", None)
    if tracker is None:
        return 0
    return tracker.bump()


__all__ = ["ToolsChangeTracker", "bump_tools_revision"]
