from __future__ import annotations

import re
from typing import Any

_REF = re.compile(r"\$\{([^}]+)\}")


def resolve_value(value: Any, inputs: dict[str, Any], step_results: dict[str, Any]) -> Any:
    if isinstance(value, str):
        if value.startswith("${") and value.endswith("}"):
            return _resolve_ref(value[2:-1], inputs, step_results)
        return _REF.sub(
            lambda m: _stringify(_resolve_ref(m.group(1), inputs, step_results)),
            value,
        )
    if isinstance(value, list):
        return [resolve_value(v, inputs, step_results) for v in value]
    if isinstance(value, dict):
        return {k: resolve_value(v, inputs, step_results) for k, v in value.items()}
    return value


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    import json

    return json.dumps(value, ensure_ascii=False)


def _resolve_ref(path: str, inputs: dict[str, Any], step_results: dict[str, Any]) -> Any:
    parts = path.split(".")
    if not parts:
        return None
    if parts[0] == "input":
        root: Any = inputs
        parts = parts[1:]
    elif parts[0].startswith("step_"):
        step_id = parts[0][5:]
        root = step_results.get(step_id)
        parts = parts[1:]
    elif parts[0] in step_results:
        root = step_results.get(parts[0])
        parts = parts[1:]
    else:
        return None
    for part in parts:
        if root is None:
            return None
        if isinstance(root, dict):
            root = root.get(part)
        elif isinstance(root, list):
            # Un outil de recherche rend une liste, et l'étape suivante veut
            # presque toujours agir sur le premier résultat. Sans index, il
            # fallait s'arrêter là et demander l'identifiant à l'utilisateur —
            # alors que l'étape précédente venait de le trouver.
            root = root[int(part)] if _est_index(part, root) else None
        else:
            return None
    return root


def _est_index(part: str, liste: list) -> bool:
    """Un index valide, et rien d'autre : « -1 » et « 99 » ne doivent pas
    renvoyer silencieusement un élément qu'on n'a pas demandé."""
    if not part.isdigit():
        return False
    return int(part) < len(liste)
