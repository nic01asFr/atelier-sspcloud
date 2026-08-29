"""Réglages UI compte (PVC) — liens faces, etc."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp_gateway.atelier.config import AtelierSettings


def ui_settings_path(settings: AtelierSettings) -> Path:
    return settings.work_dir / ".atelier" / "ui.json"


def load_ui_settings(settings: AtelierSettings) -> dict[str, Any]:
    path = ui_settings_path(settings)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def save_ui_settings(settings: AtelierSettings, patch: dict[str, Any]) -> dict[str, Any]:
    path = ui_settings_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = load_ui_settings(settings)
    for k, v in patch.items():
        if v is None or v == "":
            data.pop(k, None)
        else:
            data[k] = v
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return data


def resolve_vscode_url(settings: AtelierSettings) -> str | None:
    env = (settings.vscode_url or "").strip().rstrip("/")
    if env:
        return env
    stored = load_ui_settings(settings).get("vscode_url")
    if isinstance(stored, str) and stored.strip():
        return stored.strip().rstrip("/")
    return None
