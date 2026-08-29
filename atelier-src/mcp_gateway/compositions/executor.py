from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Awaitable

from mcp_gateway.compositions.refs import resolve_value

SYNC_STEP_TYPES = {"tool"}
DURABLE_STEP_TYPES = {"tool", "elicit", "wait_until", "approval"}
SUSPENDING_STEP_TYPES = {"elicit", "wait_until", "wait_callback", "approval", "subcomposition"}


def _sans_bruit_http(detail: str) -> str:
    """Élague ce qu'une erreur HTTP transporte pour le développeur.

    Les clients HTTP ajoutent un renvoi vers la documentation du code de
    statut, et répètent l'URL appelée. Affiché à quelqu'un qui veut savoir
    pourquoi son analyse n'a pas tourné, ce contexte noie la cause.
    """
    texte = re.split(r"\s*For more information check:", detail, maxsplit=1)[0]
    texte = re.sub(r"\s*for url '[^']*'", "", texte)
    texte = re.sub(r"^Upstream error:\s*", "", texte.strip())
    return texte.strip() or detail.strip()


class StepFailed(Exception):
    """Un outil a répondu qu'il avait échoué (isError), sans lever d'exception."""

    def __init__(self, step_id: str, tool: str | None, detail: str) -> None:
        self.step_id = step_id
        self.tool = tool
        self.detail = (detail or "").strip()
        shown = _sans_bruit_http(self.detail)[:300] or "sans détail"
        super().__init__(f"Étape « {step_id} » ({tool or 'outil inconnu'}) : {shown}")


@dataclass
class CompositionStep:
    step_id: str
    type: str = "tool"
    tool: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    optional: bool = False
    timeout_seconds: int | None = None
    elicit: dict[str, Any] | None = None
    wait_until: dict[str, Any] | None = None
    approval: dict[str, Any] | None = None
    _raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CompositionStep:
        step_id = raw.get("step_id") or raw.get("id")
        if not step_id:
            raise ValueError("step_id requis")
        return cls(
            step_id=str(step_id),
            type=str(raw.get("type", "tool")),
            tool=raw.get("tool"),
            parameters=dict(raw.get("parameters") or {}),
            optional=bool(raw.get("optional", False)),
            timeout_seconds=raw.get("timeout_seconds"),
            elicit=dict(raw["elicit"]) if raw.get("elicit") else None,
            wait_until=dict(raw["wait_until"]) if raw.get("wait_until") else None,
            approval=dict(raw["approval"]) if raw.get("approval") else None,
            _raw=dict(raw),
        )

    def to_dict(self) -> dict[str, Any]:
        out = dict(self._raw)
        out.update(
            {
                "step_id": self.step_id,
                "type": self.type,
                "tool": self.tool,
                "parameters": self.parameters,
                "optional": self.optional,
                "timeout_seconds": self.timeout_seconds,
            }
        )
        if self.elicit:
            out["elicit"] = self.elicit
        if self.wait_until:
            out["wait_until"] = self.wait_until
        if self.approval:
            out["approval"] = self.approval
        return out


@dataclass
class CompositionDefinition:
    name: str
    description: str = ""
    status: str = "temporary"
    input_schema: dict[str, Any] = field(default_factory=dict)
    steps: list[CompositionStep] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CompositionDefinition:
        steps = [CompositionStep.from_dict(s) for s in raw.get("steps") or []]
        return cls(
            name=str(raw["name"]),
            description=str(raw.get("description") or ""),
            status=str(raw.get("status") or "temporary"),
            input_schema=dict(raw.get("input_schema") or {"type": "object", "properties": {}}),
            steps=steps,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "input_schema": self.input_schema,
            "steps": [s.to_dict() for s in self.steps],
        }

    def has_suspending_steps(self) -> bool:
        return any(s.type in SUSPENDING_STEP_TYPES for s in self.steps)

    def is_tool_variant(self) -> bool:
        """Composition 1 étape tool sans suspension → variante personnalisée d'un outil."""
        if self.has_suspending_steps() or len(self.steps) != 1:
            return False
        step = self.steps[0]
        if step.type != "tool" or not step.tool:
            return False
        if str(step.tool).startswith("composition_"):
            return False
        return True

    def source_tool(self) -> str | None:
        if not self.is_tool_variant():
            return None
        return str(self.steps[0].tool or "")

    def validate_sync(self) -> None:
        self._validate(allowed=SYNC_STEP_TYPES, label="sync v0.4")

    def validate_durable(self) -> None:
        self._validate(allowed=DURABLE_STEP_TYPES, label="durable v0.5")
        for step in self.steps:
            if step.type == "elicit":
                _validate_elicit_config(step.elicit, step.step_id)
            if step.type == "wait_until":
                _validate_wait_until_config(step.wait_until, step.step_id)
            if step.type == "approval":
                _validate_approval_config(step.approval, step.step_id)

    def _validate(self, allowed: set[str], label: str) -> None:
        if not self.name.strip():
            raise ValueError("name requis")
        if not self.steps:
            raise ValueError("au moins un step requis")
        seen: set[str] = set()
        for step in self.steps:
            if step.step_id in seen:
                raise ValueError(f"step_id dupliqué: {step.step_id}")
            seen.add(step.step_id)
            if step.type not in allowed:
                raise ValueError(
                    f"step {step.step_id}: type '{step.type}' non supporté en {label} "
                    f"(types: {sorted(allowed)})"
                )
            if step.type == "tool" and not step.tool:
                raise ValueError(f"step {step.step_id}: tool requis")


def _validate_elicit_config(elicit: dict[str, Any] | None, step_id: str) -> None:
    if not elicit or not isinstance(elicit, dict):
        raise ValueError(f"step {step_id}: bloc elicit requis")
    if not str(elicit.get("message", "")).strip():
        raise ValueError(f"step {step_id}: elicit.message requis")
    schema = elicit.get("schema")
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise ValueError(f"step {step_id}: elicit.schema object requis")


def _validate_wait_until_config(wait_until: dict[str, Any] | None, step_id: str) -> None:
    if not wait_until or not isinstance(wait_until, dict):
        raise ValueError(f"step {step_id}: bloc wait_until requis")
    if (
        not wait_until.get("wait_seconds")
        and not wait_until.get("resume_at")
        and not wait_until.get("until")
    ):
        raise ValueError(f"step {step_id}: wait_seconds, resume_at ou until requis")


def _validate_approval_config(approval: dict[str, Any] | None, step_id: str) -> None:
    if not approval or not isinstance(approval, dict):
        raise ValueError(f"step {step_id}: bloc approval requis")
    if not str(approval.get("message", "")).strip():
        raise ValueError(f"step {step_id}: approval.message requis")


def tool_name_for_composition(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")
    return f"composition_{slug or 'unnamed'}"


ToolCaller = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class RunState:
    inputs: dict[str, Any] = field(default_factory=dict)
    step_results: dict[str, Any] = field(default_factory=dict)
    step_status: dict[str, str] = field(default_factory=dict)
    current_step_id: str | None = None
    error: str | None = None
    suspension: dict[str, Any] | None = None
    next_step_index: int = 0
    skipped_steps: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "inputs": self.inputs,
            "step_results": self.step_results,
            "step_status": self.step_status,
            "current_step_id": self.current_step_id,
            "error": self.error,
            "suspension": self.suspension,
            "next_step_index": self.next_step_index,
            "skipped_steps": self.skipped_steps,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RunState:
        return cls(
            inputs=dict(raw.get("inputs") or {}),
            step_results=dict(raw.get("step_results") or {}),
            step_status=dict(raw.get("step_status") or {}),
            current_step_id=raw.get("current_step_id"),
            error=raw.get("error"),
            suspension=raw.get("suspension"),
            next_step_index=int(raw.get("next_step_index") or 0),
            skipped_steps=dict(raw.get("skipped_steps") or {}),
        )


@dataclass
class ExecutionOutcome:
    status: str
    state: RunState

    @property
    def suspended(self) -> bool:
        return self.status == "suspended"


class SyncCompositionExecutor:
    def __init__(self, call_tool: ToolCaller):
        self._call_tool = call_tool

    async def run(
        self, definition: CompositionDefinition, inputs: dict[str, Any] | None = None
    ) -> RunState:
        definition.validate_sync()
        outcome = await DurableCompositionExecutor(self._call_tool).run(definition, inputs)
        return outcome.state


class DurableCompositionExecutor:
    def __init__(self, call_tool: ToolCaller):
        self._call_tool = call_tool

    async def run(
        self, definition: CompositionDefinition, inputs: dict[str, Any] | None = None
    ) -> ExecutionOutcome:
        definition.validate_durable()
        state = RunState(inputs=dict(inputs or {}))
        return await self._run_from_index(definition, state, 0)

    async def resume(
        self, definition: CompositionDefinition, state: RunState, response: Any
    ) -> ExecutionOutcome:
        definition.validate_durable()
        if not state.suspension:
            raise ValueError("Run non suspendu")
        step_id = state.suspension.get("step_id") or state.current_step_id
        if not step_id:
            raise ValueError("step_id suspension manquant")
        step = _find_step(definition, step_id)
        if step.type == "elicit":
            _validate_elicit_response(step.elicit or {}, response)
            state.step_results[step_id] = _wrap_structured(response)
            state.step_status[step_id] = "succeeded"
        elif step.type == "wait_until":
            state.step_results[step_id] = _wrap_structured(response or {"resumed_at": _utcnow_iso()})
            state.step_status[step_id] = "succeeded"
        elif step.type == "approval":
            if not isinstance(response, dict) or "approved" not in response:
                raise ValueError("Réponse approval doit contenir approved (bool)")
            if response.get("approved") is False and not step.optional:
                state.step_status[step_id] = "failed"
                state.error = str(response.get("reason") or "Rejeté")
                state.suspension = None
                state.current_step_id = None
                return ExecutionOutcome("failed", state)
            state.step_results[step_id] = _wrap_structured(response)
            state.step_status[step_id] = "succeeded"
        else:
            raise ValueError(f"Reprise non supportée pour type {step.type}")
        start_index = state.next_step_index
        state.suspension = None
        state.current_step_id = None
        return await self._run_from_index(definition, state, start_index)

    async def _run_from_index(
        self, definition: CompositionDefinition, state: RunState, start_index: int
    ) -> ExecutionOutcome:
        steps = definition.steps
        for index in range(start_index, len(steps)):
            step = steps[index]
            if state.step_status.get(step.step_id) == "succeeded":
                continue
            state.current_step_id = step.step_id
            state.next_step_index = index
            state.step_status[step.step_id] = "in_progress"
            try:
                suspend = await self._execute_step(step, state)
                if suspend:
                    state.step_status[step.step_id] = "suspended"
                    state.suspension = suspend
                    state.next_step_index = index + 1
                    return ExecutionOutcome("suspended", state)
                state.step_status[step.step_id] = "succeeded"
            except Exception as exc:
                state.step_status[step.step_id] = "failed"
                state.current_step_id = None
                if not step.optional:
                    state.error = str(exc)
                    return ExecutionOutcome("failed", state)
                # Une étape déclarée facultative ne doit pas condamner le run :
                # sa panne est consignée, le statut final reste celui des autres.
                state.skipped_steps[step.step_id] = str(exc)
        state.current_step_id = None
        state.suspension = None
        state.next_step_index = len(steps)
        status = "failed" if state.error else "completed"
        return ExecutionOutcome(status, state)

    async def _execute_step(
        self, step: CompositionStep, state: RunState
    ) -> dict[str, Any] | None:
        if step.type == "tool":
            params = resolve_value(step.parameters, state.inputs, state.step_results)
            assert step.tool
            raw = await self._call_tool(step.tool, params if isinstance(params, dict) else {})
            result = _normalize_tool_result(raw)
            state.step_results[step.step_id] = result
            if result["isError"]:
                # Un outil MCP signale son échec dans une réponse valide, pas par
                # une exception : sans cette lecture, l'étape passerait pour réussie.
                raise StepFailed(step.step_id, step.tool, result["text"])
            return None
        if step.type == "elicit":
            return _build_elicit_suspend(step, state)
        if step.type == "wait_until":
            return _build_wait_until_suspend(step, state)
        if step.type == "approval":
            return _build_approval_suspend(step, state)
        raise ValueError(f"Type step inconnu: {step.type}")


def _find_step(definition: CompositionDefinition, step_id: str) -> CompositionStep:
    for step in definition.steps:
        if step.step_id == step_id:
            return step
    raise KeyError(step_id)


def _build_elicit_suspend(step: CompositionStep, state: RunState) -> dict[str, Any]:
    cfg = step.elicit or {}
    message = resolve_value(cfg.get("message", ""), state.inputs, state.step_results)
    return {
        "reason": "elicit",
        "step_id": step.step_id,
        "message": message,
        "schema": cfg.get("schema") or {"type": "object", "properties": {}},
        "ttl_seconds": int(cfg.get("ttl_seconds") or 300),
    }


def _build_wait_until_suspend(step: CompositionStep, state: RunState) -> dict[str, Any]:
    cfg = step.wait_until or {}
    now = datetime.now(timezone.utc)
    if cfg.get("resume_at"):
        resume_at = str(cfg["resume_at"])
    elif cfg.get("until"):
        seconds = _parse_duration(str(cfg["until"]))
        resume_at = (now + timedelta(seconds=seconds)).isoformat()
    else:
        seconds = int(cfg.get("wait_seconds") or 0)
        resume_at = (now + timedelta(seconds=seconds)).isoformat()
    return {
        "reason": "wait_until",
        "step_id": step.step_id,
        "resume_at": resume_at,
        "ttl_seconds": int(cfg.get("ttl_seconds") or 86400),
    }


def _parse_duration(spec: str) -> int:
    """Parse +5m, +1h, +30s ou entier secondes."""
    s = spec.strip()
    if s.startswith("+"):
        s = s[1:]
    if s.endswith("s") and s[:-1].isdigit():
        return int(s[:-1])
    if s.endswith("m") and s[:-1].isdigit():
        return int(s[:-1]) * 60
    if s.endswith("h") and s[:-1].isdigit():
        return int(s[:-1]) * 3600
    if s.isdigit():
        return int(s)
    raise ValueError(f"Durée wait_until invalide: {spec}")


def _build_approval_suspend(step: CompositionStep, state: RunState) -> dict[str, Any]:
    cfg = step.approval or {}
    message = resolve_value(cfg.get("message", ""), state.inputs, state.step_results)
    schema = cfg.get("response_schema") or {
        "type": "object",
        "properties": {
            "approved": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": ["approved"],
    }
    return {
        "reason": "approval",
        "step_id": step.step_id,
        "message": message,
        "schema": schema,
        "allowed_roles": cfg.get("allowed_roles") or [],
        "ttl_seconds": int(cfg.get("ttl_seconds") or 86400),
    }


def _validate_elicit_response(schema: dict[str, Any], response: Any) -> None:
    if not isinstance(response, dict):
        raise ValueError("Réponse elicit doit être un objet JSON")
    required = schema.get("required") or []
    for key in required:
        if key not in response:
            raise ValueError(f"Champ requis manquant: {key}")


def _wrap_structured(value: Any) -> dict[str, Any]:
    return {"structured": value, "text": json.dumps(value, ensure_ascii=False)}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    structured = result.get("structuredContent")
    content = result.get("content") or []
    texts: list[str] = []
    if structured is None:
        for block in content:
            if block.get("type") == "text":
                texts.append(block.get("text", ""))
                try:
                    structured = json.loads(block.get("text", ""))
                except (json.JSONDecodeError, TypeError):
                    pass
    else:
        texts.append(json.dumps(structured, ensure_ascii=False))
    # Une étape qui rend une image — une carte QGIS, par exemple — n'exposait
    # rien d'utilisable : seuls les blocs texte étaient relevés, donc « .text »
    # restait vide et « .structured » nul. L'image était bien dans le résultat
    # et n'atteignait jamais l'étape suivante, alors qu'un modèle sait la lire.
    #
    # Elle devient une partie nommée, comme les deux autres : « .image » rend
    # les données du premier bloc image, « .image_type » son type MIME — ce que
    # réclame l'outil qui les reçoit.
    image = None
    image_type = None
    for block in content:
        if block.get("type") == "image" and block.get("data"):
            image = block["data"]
            image_type = block.get("mimeType") or "image/png"
            break

    return {
        "content": content,
        "text": "\n".join(texts),
        "structured": structured,
        "image": image,
        "image_type": image_type,
        "isError": bool(result.get("isError")),
    }


def new_run_id() -> str:
    return uuid.uuid4().hex[:16]
