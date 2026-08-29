"""Liste des modèles disponibles pour Atelier (settings Claude du pod)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp_gateway.atelier.config import AtelierSettings


def _settings_paths(settings: AtelierSettings) -> list[Path]:
    home = Path.home()
    return [
        home / ".claude" / "settings.json",
        settings.work_dir / ".claude" / "settings.json",
        Path("/home/onyxia/.claude/settings.json"),
    ]


def _load_claude_settings(settings: AtelierSettings) -> dict[str, Any]:
    for path in _settings_paths(settings):
        try:
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def list_available_models(settings: AtelierSettings) -> dict[str, Any]:
    """Modèles exposés à l'UI (select), dérivés de ~/.claude/settings.json."""
    raw = _load_claude_settings(settings)
    env = raw.get("env") if isinstance(raw.get("env"), dict) else {}

    default = (
        (settings.default_model or "").strip()
        or str(raw.get("model") or "").strip()
        or str(env.get("ANTHROPIC_DEFAULT_MODEL") or env.get("ANTHROPIC_MODEL") or "").strip()
    )

    ordered: list[str] = []
    labels: dict[str, str] = {}

    def add(mid: str, label: str | None = None) -> None:
        mid = (mid or "").strip()
        if not mid or mid in ordered:
            return
        ordered.append(mid)
        if label:
            labels[mid] = label

    # Alias Claude Code → modèles pod (lisibles)
    sonnet = str(env.get("ANTHROPIC_DEFAULT_SONNET_MODEL") or "").strip()
    opus = str(env.get("ANTHROPIC_DEFAULT_OPUS_MODEL") or "").strip()
    haiku = str(env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL") or "").strip()

    if default:
        add(default, "Recommandé")
    if sonnet:
        add(sonnet, labels.get(sonnet) or "Équilibré")
    if opus:
        add(opus, "Plus capable")
    if haiku:
        add(haiku, "Plus rapide")

    fallback = raw.get("fallbackModel")
    if isinstance(fallback, list):
        for m in fallback:
            add(str(m), None)
    elif isinstance(fallback, str) and fallback.strip():
        add(fallback.strip(), None)

    # Alias symboliques utiles si le CLI les accepte encore
    for alias, target, label in (
        ("sonnet", sonnet or default, "Équilibré (alias)"),
        ("opus", opus or default, "Plus capable (alias)"),
        ("haiku", haiku or default, "Plus rapide (alias)"),
    ):
        if target and alias not in ordered:
            # n'ajoute les alias que s'ils pointent vers un id réel distinct
            pass

    models = [
        {
            "id": mid,
            "label": labels.get(mid) or mid,
            "default": mid == default,
        }
        for mid in ordered
    ]

    if not models and default:
        models = [{"id": default, "label": "Recommandé", "default": True}]

    return {
        "default": default or (models[0]["id"] if models else ""),
        "models": models,
        "source": "claude_settings",
    }
