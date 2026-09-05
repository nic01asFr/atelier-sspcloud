"""Événements typés du flux harness (pas de JSON brut vers le client)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

EventKind = Literal[
    "texte",
    "outil_debut",
    "outil_fin",
    "permission_demandee",
    "decision_attendue",
    "decision_rendue",
    "fin",
    "erreur",
    "heartbeat",
    "systeme",
]


@dataclass
class AtelierEvent:
    kind: EventKind
    session_id: str
    text: str = ""
    tool: str = ""
    cause: str = ""
    raw_type: str = ""
    tool_id: str = ""

    def as_sse(self) -> str:
        payload = asdict(self)
        return f"event: {self.kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def sortie_outil(block: dict[str, Any]) -> str:
    """Ce qu'un outil a rendu, quelle qu'en soit la forme.

    Claude écrit ce retour tantôt d'une pièce, tantôt en blocs. Ne
    reconnaître que la seconde forme laissait la sortie vide.
    """
    contenu = block.get("content")
    if isinstance(contenu, str):
        return contenu
    if not isinstance(contenu, list):
        return ""
    morceaux = [
        str(c["text"])
        for c in contenu
        if isinstance(c, dict) and c.get("type") == "text" and c.get("text")
    ]
    return chr(10).join(morceaux)


def parse_stream_json_line(session_id: str, line: str) -> list[AtelierEvent]:
    """Convertit une ligne stream-json CLI en événements typés."""
    line = line.strip()
    if not line:
        return []
    try:
        obj: dict[str, Any] = json.loads(line)
    except json.JSONDecodeError:
        return [AtelierEvent(kind="systeme", session_id=session_id, text=line, raw_type="unparsed")]

    t = obj.get("type") or ""
    events: list[AtelierEvent] = []

    if t == "assistant":
        msg = obj.get("message") or {}
        content = msg.get("content") or []
        if isinstance(content, str) and content:
            events.append(AtelierEvent(kind="texte", session_id=session_id, text=content, raw_type=t))
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                bt = block.get("type")
                if bt == "text" and block.get("text"):
                    events.append(
                        AtelierEvent(
                            kind="texte", session_id=session_id, text=str(block["text"]), raw_type=t
                        )
                    )
                elif bt == "thinking" and block.get("thinking"):
                    events.append(
                        AtelierEvent(
                            kind="texte",
                            session_id=session_id,
                            text=str(block["thinking"]),
                            raw_type="thinking",
                        )
                    )
                elif bt == "tool_use":
                    events.append(
                        AtelierEvent(
                            kind="outil_debut",
                            session_id=session_id,
                            tool=str(block.get("name") or ""),
                            text=json.dumps(block.get("input") or {}, ensure_ascii=False),
                            tool_id=str(block.get("id") or ""),
                            raw_type=t,
                        )
                    )
                elif bt == "tool_result":
                    events.append(
                        AtelierEvent(
                            kind="outil_fin",
                            session_id=session_id,
                            tool_id=str(block.get("tool_use_id") or ""),
                            text=sortie_outil(block),
                            raw_type="tool_result",
                        )
                    )
    elif t == "result":
        subtype = obj.get("subtype") or ""
        # Un tour qui épuise ses tours d'outils sort avec le code 0 et un
        # `result` d'apparence normale : il se lisait comme une fin ordinaire,
        # alors que le modèle s'est arrêté au milieu de son travail sans rien
        # conclure. Le dire est le minimum — sinon on lit un silence comme une
        # réponse.
        if subtype == "error_max_turns":
            events.append(
                AtelierEvent(
                    kind="erreur",
                    session_id=session_id,
                    cause="plafond de tours atteint : la réponse est incomplète",
                    raw_type=t,
                )
            )
        elif obj.get("is_error") or subtype == "error_during_execution":
            errs = obj.get("errors") or []
            if isinstance(errs, list) and errs:
                cause = "; ".join(str(x) for x in errs if x)
            else:
                cause = str(obj.get("error") or subtype or "result_error")
            if isinstance(obj.get("result"), str) and obj["result"] and not errs:
                cause = obj["result"]
            events.append(
                AtelierEvent(
                    kind="erreur",
                    session_id=session_id,
                    cause=cause,
                    raw_type=t,
                )
            )
        else:
            denials = obj.get("permission_denials") or []
            if isinstance(denials, list) and denials:
                events.append(
                    AtelierEvent(
                        kind="permission_demandee",
                        session_id=session_id,
                        text=json.dumps(denials, ensure_ascii=False),
                        raw_type="permission_denials",
                    )
                )
            if isinstance(obj.get("result"), str) and obj["result"]:
                events.append(
                    AtelierEvent(
                        kind="texte",
                        session_id=session_id,
                        text=str(obj["result"]),
                        raw_type="result_text",
                    )
                )
            events.append(AtelierEvent(kind="fin", session_id=session_id, cause=str(subtype), raw_type=t))
    elif t == "user":
        # Le CLI renvoie les résultats d'outils dans des messages « user ».
        # Faute de cette branche, aucun « outil_fin » n'était émis : à l'écran
        # les outils restaient « en cours » jusqu'à ce qu'on recharge la page,
        # alors même que le tour était terminé.
        msg = obj.get("message") or {}
        content = msg.get("content") or []
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                events.append(
                    AtelierEvent(
                        kind="outil_fin",
                        session_id=session_id,
                        tool_id=str(block.get("tool_use_id") or ""),
                        text=sortie_outil(block),
                        raw_type="tool_result",
                    )
                )
    elif t == "stream_event":
        ev = obj.get("event") or {}
        et = ev.get("type") if isinstance(ev, dict) else ""
        if et == "content_block_delta":
            delta = (ev.get("delta") or {}) if isinstance(ev, dict) else {}
            if delta.get("type") == "text_delta" and delta.get("text"):
                events.append(
                    AtelierEvent(
                        kind="texte", session_id=session_id, text=str(delta["text"]), raw_type=et
                    )
                )
            if delta.get("type") == "thinking_delta" and delta.get("thinking"):
                events.append(
                    AtelierEvent(
                        kind="texte",
                        session_id=session_id,
                        text=str(delta["thinking"]),
                        raw_type="thinking_delta",
                    )
                )
            if delta.get("type") == "input_json_delta" and delta.get("partial_json"):
                events.append(
                    AtelierEvent(
                        kind="outil_debut",
                        session_id=session_id,
                        text=str(delta["partial_json"]),
                        raw_type="input_json_delta",
                    )
                )
        elif et == "content_block_start":
            block = (ev.get("content_block") or {}) if isinstance(ev, dict) else {}
            if block.get("type") == "tool_use":
                events.append(
                    AtelierEvent(
                        kind="outil_debut",
                        session_id=session_id,
                        tool=str(block.get("name") or ""),
                        text=json.dumps(block.get("input") or {}, ensure_ascii=False),
                        tool_id=str(block.get("id") or ""),
                        raw_type=et,
                    )
                )
            elif block.get("type") == "tool_result":
                events.append(
                    AtelierEvent(
                        kind="outil_fin",
                        session_id=session_id,
                        tool_id=str(block.get("tool_use_id") or ""),
                        text=sortie_outil(block),
                        raw_type="tool_result",
                    )
                )
        elif et == "content_block_stop":
            events.append(AtelierEvent(kind="outil_fin", session_id=session_id, raw_type=et))
    elif t == "system":
        events.append(
            AtelierEvent(
                kind="systeme",
                session_id=session_id,
                text=str(obj.get("subtype") or obj.get("message") or ""),
                raw_type=t,
            )
        )
    else:
        events.append(AtelierEvent(kind="systeme", session_id=session_id, text=t, raw_type=t))

    return events
