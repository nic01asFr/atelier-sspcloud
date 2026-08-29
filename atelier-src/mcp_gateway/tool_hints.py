"""Hints MCP (Tool.title, ToolAnnotations) pour outils gateway et inférences upstream."""
from __future__ import annotations

import re
from typing import Any

_GATEWAY_META: dict[str, dict[str, Any]] = {
    "gateway_status": {
        "title": "Statut gateway",
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    "gateway_list_bundles": {
        "title": "Lister les presets",
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    "gateway_use_bundle": {
        "title": "Activer un preset",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    },
    "gateway_list_profiles": {
        "title": "Lister les profils",
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    "gateway_get_profile": {
        "title": "Détail profil actif",
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    "gateway_use_profile": {
        "title": "Activer un profil",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    },
    "gateway_create_profile": {
        "title": "Créer un profil perso",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
    },
    "gateway_update_profile": {
        "title": "Modifier un profil perso",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    },
    "gateway_list_compositions": {
        "title": "Lister les compositions",
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    "gateway_run_composition": {
        "title": "Exécuter une composition",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    },
    "gateway_composition_run_status": {
        "title": "Statut run composition",
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    "gateway_resume_composition": {
        "title": "Reprendre composition suspendue",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    },
}

_READ_ONLY_RE = re.compile(
    r"(search|list|get|describe|read|resolve|status|fetch|query|preview|corpus|facets|metrics|info)",
    re.I,
)
_WRITE_RE = re.compile(
    r"(run_recipe|deploy|exec|delete|export|create|add|patch|upload|write|apply|upsert|save|promote)",
    re.I,
)


def gateway_tool_hints(name: str) -> dict[str, Any]:
    return dict(_GATEWAY_META.get(name) or {})


def infer_tool_hints(name: str, *, kind: str = "", variant: bool = False) -> dict[str, Any]:
    if name in _GATEWAY_META:
        return gateway_tool_hints(name)

    hints: dict[str, Any] = {}
    short = name.split("__")[-1] if "__" in name else name

    if kind == "composition" or name.startswith("composition_"):
        hints["title"] = short.replace("_", " ").strip() or name
        hints["annotations"] = {
            "readOnlyHint": False,
            "destructiveHint": not variant,
            "openWorldHint": True,
        }
        return hints

    if "__" in name:
        prefix, base = name.split("__", 1)
        hints["title"] = f"{prefix}: {base.replace('_', ' ')}"

    annotations: dict[str, Any] = {"openWorldHint": True}
    if _READ_ONLY_RE.search(short) and not _WRITE_RE.search(short):
        annotations["readOnlyHint"] = True
        annotations["destructiveHint"] = False
    elif _WRITE_RE.search(short):
        annotations["readOnlyHint"] = False
        annotations["destructiveHint"] = "delete" in short.lower()
    else:
        annotations["readOnlyHint"] = False
        annotations["destructiveHint"] = True

    hints["annotations"] = annotations
    return hints


def apply_tool_hints(item: dict[str, Any]) -> dict[str, Any]:
    """Enrichit un outil interne avec title/annotations (sans écraser upstream)."""
    name = str(item.get("name") or "")
    kind = str(item.get("kind") or "")
    variant = bool(item.get("variant"))
    defaults = infer_tool_hints(name, kind=kind, variant=variant)

    if not item.get("title") and defaults.get("title"):
        item["title"] = defaults["title"]
    if not item.get("annotations") and defaults.get("annotations"):
        item["annotations"] = defaults["annotations"]
    return item


__all__ = [
    "apply_tool_hints",
    "gateway_tool_hints",
    "infer_tool_hints",
]
