"""Liste des modèles disponibles pour Atelier (settings Claude du pod)."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from mcp_gateway.atelier.config import MODELES_ECARTES, AtelierSettings


def _settings_paths(settings: AtelierSettings) -> list[Path]:
    home = Path.home()
    return [
        home / ".claude" / "settings.json",
        settings.work_dir / ".claude" / "settings.json",
    ]


def _load_claude_settings(settings: AtelierSettings) -> dict[str, Any]:
    for path in _settings_paths(settings):
        try:
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return {}


DUREE_DU_CACHE_S = 300
DELAI_AMONT_S = 3.0
# (instant, ids) de la dernière lecture réussie, par adresse d'API.
_cache: dict[str, tuple[float, list[str]]] = {}


def _cle(settings: AtelierSettings) -> str:
    depuis_env = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if depuis_env:
        return depuis_env
    try:
        return settings.llm_key_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


_TYPES_DE_CONVERSATION = {"text-generation", "image-text-to-text"}


def _est_un_modele_de_conversation(entree: dict[str, Any]) -> bool:
    """Écarte les préréglages, les plongements, la voix et les modèles sans identifiant."""
    mid = str(entree.get("id") or "")
    if not mid or entree.get("preset") or "embed" in mid.lower() or "whisper" in mid.lower():
        return False
    # Albert type ses modèles ; SSPCloud non.
    if entree.get("type") and entree["type"] not in _TYPES_DE_CONVERSATION:
        return False
    return mid not in MODELES_ECARTES


def _lire_modeles(base: str, cle: str, *, en_direct: bool) -> list[str]:
    """Identifiants annoncés par `GET <base>/models`, avec cache.

    `en_direct=False` ne lit que le cache : l'appelant n'attend jamais le
    réseau. Toute panne rend la dernière liste connue, ou rien.
    """
    connu = _cache.get(base)
    if connu and (not en_direct or time.monotonic() - connu[0] < DUREE_DU_CACHE_S):
        return list(connu[1])
    if not en_direct or not cle:
        return []
    requete = urllib.request.Request(
        f"{base}/models", headers={"Authorization": f"Bearer {cle}", "x-api-key": cle}
    )
    try:
        with urllib.request.urlopen(requete, timeout=DELAI_AMONT_S) as reponse:
            data = json.loads(reponse.read().decode("utf-8"))
        entrees = data.get("data") if isinstance(data, dict) else None
        ids = [
            str(e["id"]) for e in entrees or [] if isinstance(e, dict) and _est_un_modele_de_conversation(e)
        ]
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError):
        return list(connu[1]) if connu else []
    _cache[base] = (time.monotonic(), ids)
    return ids


def modeles_de_l_api(settings: AtelierSettings, *, en_direct: bool) -> list[str]:
    """Modèles de l'API SSPCloud (format Anthropic)."""
    return _lire_modeles(settings.anthropic_base_url.rstrip("/"), _cle(settings), en_direct=en_direct)


def modeles_des_fournisseurs(settings: AtelierSettings, *, en_direct: bool) -> list[tuple[str, str]]:
    """(id préfixé, libellé) des modèles des fournisseurs OpenAI, Albert compris."""
    from mcp_gateway.atelier.fournisseurs import charger_fournisseurs

    sortie: list[tuple[str, str]] = []
    for f in charger_fournisseurs(settings):
        for mid in _lire_modeles(f.base_url, f.cle, en_direct=en_direct):
            sortie.append((f"{f.prefixe()}{mid}", f"{f.nom} · {mid}"))
    return sortie


def list_available_models(settings: AtelierSettings, *, en_direct: bool = False) -> dict[str, Any]:
    """Modèles exposés à l'UI (select) : ~/.claude/settings.json, puis l'API.

    Les créneaux des réglages passent en premier (le défaut y est choisi) ;
    les autres modèles que l'API annonce s'y ajoutent, Albert compris dès
    qu'elle les expose.
    """
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

    for mid in modeles_de_l_api(settings, en_direct=en_direct):
        add(mid, None)
    for mid, libelle in modeles_des_fournisseurs(settings, en_direct=en_direct):
        add(mid, libelle)

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
