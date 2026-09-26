"""Événements typés du flux harness (pas de JSON brut vers le client)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

_SUBSTITUT_MIN = chr(0xD800)
_SUBSTITUT_MAX = chr(0xDFFF)


def texte_sur(texte: str) -> str:
    """Le texte sans demi-caractère : un emoji coupé en deux ne casse plus rien.

    Le CLI est écrit en JavaScript, où une chaîne est en UTF-16. Un fragment
    de flux peut s'arrêter entre les deux moitiés d'un emoji : le JSON porte
    alors l'échappement d'une moitié seule (U+D83D), que Python lit comme un
    substitut isolé. Rien ne l'écrit ensuite en UTF-8 — ni le journal, ni le
    flux vers le navigateur : « surrogates not allowed », et le tour tombait.
    Deux moitiés voisines se recollent ; une moitié seule devient U+FFFD.

    Aucun substitut littéral dans ce fichier : écrit dans une chaîne, il
    empêchait le module lui-même de s'importer sous Linux.
    """
    if not texte or not any(_SUBSTITUT_MIN <= c <= _SUBSTITUT_MAX for c in texte):
        return texte
    return texte.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def sans_substituts(valeur: Any) -> Any:
    """`texte_sur` appliqué à toute chaîne d'une structure JSON lue."""
    if isinstance(valeur, str):
        return texte_sur(valeur)
    if isinstance(valeur, list):
        return [sans_substituts(v) for v in valeur]
    if isinstance(valeur, dict):
        return {texte_sur(k) if isinstance(k, str) else k: sans_substituts(v) for k, v in valeur.items()}
    return valeur


# Les sous-types de ligne `system` qui peuvent porter un message pour la
# personne. Le `systemMessage` d'un hook (relance `Stop` de wikichat,
# docs/hooks-et-dialogue.md §4.3) arrive selon les versions du CLI sous l'un de
# ces noms, ou dans le champ `systemMessage` lui-même. Non mesuré sur le pod.
SOUS_TYPES_MESSAGE = ("informational", "hook_response", "hook_system_message", "stop_hook_summary")


def message_systeme(obj: dict[str, Any]) -> str:
    """Le message qu'un hook adresse à la personne, s'il y en a un."""
    direct = obj.get("systemMessage")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    sous_type = obj.get("subtype")
    if sous_type not in SOUS_TYPES_MESSAGE:
        return ""
    for cle in ("output", "stdout"):
        brut = obj.get(cle)
        if isinstance(brut, str) and brut.strip().startswith("{"):
            try:
                sortie = json.loads(brut)
            except ValueError:
                continue
            if isinstance(sortie, dict) and isinstance(sortie.get("systemMessage"), str):
                return sortie["systemMessage"].strip()
    messages = obj.get("hookSystemMessages") or obj.get("systemMessages")
    if isinstance(messages, list):
        dits = [m.strip() for m in messages if isinstance(m, str) and m.strip()]
        if dits:
            return "\n".join(dits)
    if sous_type == "informational":
        contenu = obj.get("content") or obj.get("message")
        if isinstance(contenu, str):
            return contenu.strip()
    return ""


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
    # Ce qui identifie ce que l'événement rapporte, pour qu'un onglet qui le
    # reçoit par deux flux (celui de l'envoi et le flux en direct) le
    # reconnaisse sans comparer des textes : `message_id` est l'identifiant du
    # message du modèle (`message.id`), `uuid` celui de la ligne du CLI, et
    # `envoi` celui de l'envoi qui a lancé le tour (posé par la route).
    message_id: str = ""
    uuid: str = ""
    envoi: str = ""

    def as_sse(self) -> str:
        payload = sans_substituts(asdict(self))
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
        obj: dict[str, Any] = sans_substituts(json.loads(line))
    except json.JSONDecodeError:
        return [AtelierEvent(kind="systeme", session_id=session_id, text=texte_sur(line), raw_type="unparsed")]
    if not isinstance(obj, dict):
        return []

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
        dit = message_systeme(obj)
        if dit:
            # Un message pour la personne : l'interface l'affiche dans le fil.
            events.append(
                AtelierEvent(
                    kind="systeme", session_id=session_id, text=dit, cause="message_systeme", raw_type=t
                )
            )
        else:
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

    return _identifier(obj, events)


def _identifier(obj: dict[str, Any], events: list[AtelierEvent]) -> list[AtelierEvent]:
    """Pose sur les événements d'une ligne l'identité de ce qu'ils rapportent.

    Le `uuid` de la ligne, et pour un message du modèle son `message.id`. Un
    fragment de flux partiel ne nomme pas son message, sauf `message_start`
    qui l'ouvre ; un bloc complet (`assistant`) porte les deux.
    """
    uid = str(obj.get("uuid") or "")
    message_id = ""
    message = obj.get("message")
    if obj.get("type") == "assistant" and isinstance(message, dict):
        message_id = str(message.get("id") or "")
    else:
        ev_flux = obj.get("event")
        if isinstance(ev_flux, dict) and isinstance(ev_flux.get("message"), dict):
            message_id = str(ev_flux["message"].get("id") or "")
    for ev in events:
        ev.uuid = uid
        ev.message_id = message_id
    return events
