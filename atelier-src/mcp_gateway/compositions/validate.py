from __future__ import annotations

import re
from typing import Any

from mcp_gateway.compositions.executor import CompositionDefinition

_REF = re.compile(r"\$\{([^}]+)\}")


def validate_for_promotion(definition: CompositionDefinition) -> list[str]:
    """Gate promotion : définition complète et cohérente."""
    errors: list[str] = []

    if not definition.name.strip():
        errors.append("Nom de composition requis")
    elif not re.match(r"^[a-zA-Z][a-zA-Z0-9_]*$", definition.name):
        errors.append("Nom : identifiant alphanumérique (ex. deploy_garde)")

    if not definition.steps:
        errors.append("Au moins une étape requise")

    props = (definition.input_schema or {}).get("properties") or {}
    required_inputs = set((definition.input_schema or {}).get("required") or [])

    for key in required_inputs:
        if key not in props:
            errors.append(f"Entrée requise « {key} » absente du schéma")

    step_ids: set[str] = set()
    for i, step in enumerate(definition.steps):
        if step.step_id in step_ids:
            errors.append(f"step_id dupliqué : {step.step_id}")
        step_ids.add(step.step_id)

        if step.type == "tool":
            if not step.tool or step.tool.endswith("__unavailable"):
                label = step._raw.get("label") or step.step_id
                errors.append(f"Étape « {label} » : outil MCP requis")
        elif step.type == "elicit":
            msg = (step.elicit or {}).get("message", "")
            if not str(msg).strip():
                errors.append(f"Étape « {step.step_id} » : message elicit requis")
        elif step.type == "approval":
            msg = (step.approval or {}).get("message", "")
            if not str(msg).strip():
                errors.append(f"Étape « {step.step_id} » : message approval requis")
        elif step.type == "wait_until":
            wu = step.wait_until or {}
            if not (wu.get("wait_seconds") or wu.get("resume_at") or wu.get("until")):
                errors.append(f"Étape « {step.step_id} » : durée wait_until requise")

        prior_ids = {s.step_id for s in definition.steps[:i]}
        for ref in _collect_refs(step):
            err = _check_ref(ref, props, prior_ids)
            if err:
                errors.append(err)

    return errors


def _collect_refs(step: Any) -> list[str]:
    refs: list[str] = []
    raw = step.to_dict()
    _walk_refs(raw, refs)
    return refs


def _walk_refs(value: Any, out: list[str]) -> None:
    if isinstance(value, str):
        out.extend(_REF.findall(value))
    elif isinstance(value, dict):
        for v in value.values():
            _walk_refs(v, out)
    elif isinstance(value, list):
        for v in value:
            _walk_refs(v, out)


def _check_ref(
    ref: str,
    input_props: dict[str, Any],
    prior_step_ids: set[str],
) -> str | None:
    parts = ref.split(".")
    if not parts:
        return None
    if parts[0] == "input":
        key = parts[1] if len(parts) > 1 else ""
        if key and key not in input_props:
            return f"Référence ${{{ref}}} : entrée « {key} » non déclarée"
        return None
    elif parts[0].startswith("step_"):
        step_key = parts[0][5:]
    else:
        step_key = parts[0]
    if step_key not in prior_step_ids:
        return f"Référence ${{{ref}}} : étape « {step_key} » inconnue ou ordre invalide"
    return None
